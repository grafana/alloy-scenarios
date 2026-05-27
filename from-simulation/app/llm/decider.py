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
        self.enabled = bool(config.anthropic_api_key) and anthropic is not None
        self._client = None
        if self.enabled:
            try:
                self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
            except Exception:
                _log.exception("anthropic client init failed; disabling LLM decider")
                self.enabled = False
        self._bucket = _TokenBucket(config.llm_global_rpm)
        self._last_tick_by_actor: dict[str, int] = {}
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

        # Token bucket guard.
        if not self._bucket.try_consume():
            self._inc_counter("rate_limited", actor_id)
            return None

        fear_bucket = int(min(100.0, max(0.0, fear))) // 25  # 0..4
        menu_key = tuple(s.value for s in menu)
        try:
            result = self._cached(actor_id, current_state.value, phase.value, fear_bucket, menu_key, extra_context)
        except Exception:
            self._inc_counter("error", actor_id)
            return None

        # Cooldown is consumed whether or not we got a usable answer.
        self._last_tick_by_actor[actor_id] = current_tick

        if result is None:
            self._inc_counter("no_decision", actor_id)
            return None

        state_str, reason = result
        try:
            chosen = State(state_str)
        except ValueError:
            self._inc_counter("invalid_state", actor_id)
            return None
        if chosen not in menu:
            self._inc_counter("off_menu", actor_id)
            return None
        self._inc_counter("ok", actor_id)
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

    # ------------------------------------------------------- internals
    def _inc_counter(self, outcome: str, actor: str) -> None:
        if self.telemetry is None:
            return
        try:
            self.telemetry.counter_inc(
                Metric.LLM_CALLS_TOTAL, 1.0, {"outcome": outcome, "actor": actor}
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
