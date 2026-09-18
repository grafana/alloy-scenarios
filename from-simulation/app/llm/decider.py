"""
Optional Anthropic-powered action picker.

When ``Config.anthropic_api_key`` is None, ``LLMDecider`` is a no-op: every
``maybe_decide(...)`` call returns None and no network requests are made.

When enabled:
  * A token-bucket caps global throughput at ``LLM_GLOBAL_RPM``.
  * A per-actor cooldown (``LLM_MIN_TICK_GAP`` ticks) prevents one chatty
    character from monopolising the budget.
  * Results are cached by ``functools.lru_cache`` keyed by
    ``(actor_id, current_state, phase, fear_bucket, tuple(menu))`` so identical
    decision contexts within a short window reuse the model's answer.
  * The model is called with a single tool (``choose_action`` — see
    ``llm/actions.py``) whose ``state`` enum is the supplied menu.
  * Every call increments ``from_sim_llm_calls_total{outcome,actor}``.

The decider is "best effort": any exception (network, JSON, missing SDK)
returns None. The caller falls back to the weighted transition table.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from typing import List, Optional, Tuple

from contracts import Config, Metric, Phase, SimTelemetry, State

try:
    import anthropic  # type: ignore
except Exception:  # pragma: no cover — sdk may be absent locally
    anthropic = None  # type: ignore

from llm.actions import build_tool_schema


_log = logging.getLogger(__name__)


class _TokenBucket:
    """Minute-window token bucket. Thread-safe."""

    def __init__(self, rpm: int) -> None:
        self.capacity = max(1, int(rpm))
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def try_consume(self, n: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            # Refill linearly: capacity tokens per 60 s.
            self.tokens = min(self.capacity, self.tokens + elapsed * (self.capacity / 60.0))
            self.last_refill = now
            if self.tokens >= n:
                self.tokens -= n
                return True
            return False


class LLMDecider:
    """Decides the next FSM state for an actor using Claude. Optional."""

    def __init__(self, config: Config, telemetry: Optional[SimTelemetry] = None) -> None:
        self.config = config
        self.telemetry = telemetry
        # Honour the deterministic-mode gate: even if a key is set, refuse to
        # call out so SEED-pinned runs stay byte-identical.
        deterministic = bool(getattr(config, "deterministic_mode", False))
        self.enabled = (
            bool(config.anthropic_api_key)
            and anthropic is not None
            and not deterministic
        )
        self._client = None
        if self.enabled:
            try:
                self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
            except Exception:
                _log.exception("anthropic client init failed; disabling LLM decider")
                self.enabled = False
        # v9 — split the budget. State-choice keeps the lion's share, the
        # rest funds reflective "thinking" calls (Yellow Man tactics, Mind
        # reflection labels). If the split would zero out either bucket, we
        # back off to the legacy single bucket sized at ``llm_global_rpm``.
        thinking_rpm = max(0, int(getattr(config, "llm_thinking_rpm", 0)))
        state_rpm = max(1, int(config.llm_global_rpm) - thinking_rpm)
        self._state_bucket = _TokenBucket(state_rpm)
        self._thinking_bucket = _TokenBucket(max(1, thinking_rpm)) if thinking_rpm > 0 else self._state_bucket
        # Compat alias — some callers still reach for ``_bucket``.
        self._bucket = self._state_bucket
        self._last_tick_by_actor: dict[str, int] = {}
        # Separate cooldown table for thinking calls so a reflection doesn't
        # block the next state choice (and vice versa).
        self._last_think_tick_by_actor: dict[str, int] = {}
        # Bind the cache to the instance, keyed on the parts we want.
        self._cached = functools.lru_cache(maxsize=2048)(self._call_uncached)
        # World handle for pushing narrations; attached lazily by app.py.
        self._world = None

    def attach_world(self, world) -> None:
        """Hook the decider up to a World so successful decisions can
        publish a one-line 'reason' to the UI narration panel."""
        self._world = world

    # --------------------------------------------------------- public API
    def maybe_decide(
        self,
        actor_id: str,
        current_state: State,
        phase: Phase,
        fear: float,
        menu: List[State],
        current_tick: int,
        extra_context: str = "",
    ) -> Optional[Tuple[State, str]]:
        """Return (chosen state, reason) or None if we should fall back."""
        if not self.enabled or not menu:
            return None

        # Per-actor cooldown.
        last = self._last_tick_by_actor.get(actor_id, -10**9)
        if current_tick - last < self.config.llm_min_tick_gap:
            return None

        # Token bucket guard (state-choice slice).
        if not self._state_bucket.try_consume():
            self._inc_counter("rate_limited", actor_id, purpose="state_choice")
            return None

        fear_bucket = int(min(100.0, max(0.0, fear))) // 25  # 0..4
        menu_key = tuple(s.value for s in menu)
        try:
            result = self._cached(actor_id, current_state.value, phase.value, fear_bucket, menu_key, extra_context)
        except Exception:
            self._inc_counter("error", actor_id, purpose="state_choice")
            return None

        # Cooldown is consumed whether or not we got a usable answer.
        self._last_tick_by_actor[actor_id] = current_tick

        if result is None:
            self._inc_counter("no_decision", actor_id, purpose="state_choice")
            return None

        state_str, reason = result
        try:
            chosen = State(state_str)
        except ValueError:
            self._inc_counter("invalid_state", actor_id, purpose="state_choice")
            return None
        if chosen not in menu:
            self._inc_counter("off_menu", actor_id, purpose="state_choice")
            return None
        self._inc_counter("ok", actor_id, purpose="state_choice")
        # Publish the narration line if we've been attached to a world.
        if self._world is not None and reason:
            try:
                self._world.narrations.append({"actor": actor_id, "reason": reason, "state": chosen.value})
                # Cap the rolling window — snapshot only emits the last 10 anyway.
                if len(self._world.narrations) > 50:
                    del self._world.narrations[: len(self._world.narrations) - 50]
            except Exception:  # never let narration bookkeeping kill a tick
                pass
        return chosen, reason

    # --------------------------------------------- public API — generic picker
    def maybe_pick_string(
        self,
        actor_id: str,
        options: List[str],
        current_tick: int,
        system: str,
        prompt: str,
    ) -> Optional[str]:
        """Pick one of ``options`` for a non-State decision (e.g. Yellow Man
        imposter action). Uses the thinking bucket and a longer cooldown so
        these calls never starve the state-choice budget.

        Returns the chosen string (must be a member of ``options``) or None
        when disabled / rate-limited / off-menu.
        """
        if not self.enabled or not options:
            return None
        # Per-actor thinking cooldown — 4x the state cooldown so reflective
        # calls are rarer than tactical ones.
        last = self._last_think_tick_by_actor.get(actor_id, -10**9)
        cd = max(60, int(self.config.llm_min_tick_gap) * 4)
        if current_tick - last < cd:
            return None
        if not self._thinking_bucket.try_consume():
            self._inc_counter("rate_limited", actor_id, purpose="thinking")
            return None
        try:
            chosen = self._call_pick_string(actor_id, tuple(options), system, prompt)
        except Exception:
            self._inc_counter("error", actor_id, purpose="thinking")
            return None
        self._last_think_tick_by_actor[actor_id] = current_tick
        if chosen is None:
            self._inc_counter("no_decision", actor_id, purpose="thinking")
            return None
        if chosen not in options:
            self._inc_counter("off_menu", actor_id, purpose="thinking")
            return None
        self._inc_counter("ok", actor_id, purpose="thinking")
        return chosen

    # ------------------------------------------------------- internals
    def _inc_counter(self, outcome: str, actor: str, *, purpose: str = "state_choice") -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.counter_inc(
                Metric.LLM_CALLS_TOTAL,
                1.0,
                {"outcome": outcome, "actor": actor, "purpose": purpose},
            )
        except Exception:
            pass

    def _call_uncached(
        self,
        actor_id: str,
        current_state_str: str,
        phase_str: str,
        fear_bucket: int,
        menu_key: Tuple[str, ...],
        extra_context: str,
    ) -> Optional[Tuple[str, str]]:
        """The cache-miss path. Returns (state_str, reason) or None."""
        if self._client is None:
            return None
        menu = [State(s) for s in menu_key]
        tool = build_tool_schema(menu)
        system = (
            "You are the inner voice of a villager in the small mountain town of From. "
            "It is forever beset by creatures from the forest. "
            "Pick the single best next action from the provided tool. "
            "Be terse — under 140 characters in the 'reason' field."
        )
        prompt = (
            f"Actor: {actor_id}\n"
            f"Current state: {current_state_str}\n"
            f"Phase: {phase_str}\n"
            f"Fear bucket (0=calm, 4=panic): {fear_bucket}\n"
            f"Menu: {', '.join(menu_key)}\n"
            f"{extra_context}".strip()
        )
        try:
            resp = self._client.messages.create(
                model=self.config.llm_model,
                max_tokens=256,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": "choose_action"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception:
            _log.debug("LLM call failed", exc_info=True)
            return None

        # Find the tool_use block in the response.
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "choose_action":
                inp = getattr(block, "input", {}) or {}
                state_str = inp.get("state")
                reason = inp.get("reason", "") or ""
                if isinstance(state_str, str):
                    return state_str, reason
        return None

    def _call_pick_string(
        self,
        actor_id: str,
        options: Tuple[str, ...],
        system: str,
        prompt: str,
    ) -> Optional[str]:
        """Generic single-choice picker. Uses a dynamic tool whose ``choice``
        enum is the options tuple, so the model is structurally constrained
        to a member of the menu. Returns the chosen string or None."""
        if self._client is None or not options:
            return None
        tool = {
            "name": "pick",
            "description": "Pick one option from the menu.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": list(options)},
                    "reason": {"type": "string"},
                },
                "required": ["choice"],
                "additionalProperties": False,
            },
        }
        try:
            resp = self._client.messages.create(
                model=self.config.llm_model,
                max_tokens=200,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": "pick"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception:
            _log.debug("LLM pick_string failed", exc_info=True)
            return None
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "pick":
                inp = getattr(block, "input", {}) or {}
                choice = inp.get("choice")
                reason = inp.get("reason", "") or ""
                if isinstance(choice, str):
                    # Optionally surface a one-line rationale to the UI narration.
                    if self._world is not None and reason:
                        try:
                            self._world.narrations.append(
                                {"actor": actor_id, "reason": reason, "state": choice}
                            )
                            if len(self._world.narrations) > 50:
                                del self._world.narrations[: len(self._world.narrations) - 50]
                        except Exception:
                            pass
                    return choice
        return None
