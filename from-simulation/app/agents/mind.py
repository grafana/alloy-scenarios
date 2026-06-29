"""
v9 — Mind: the per-agent cognitive layer.

Four layers sit between the existing weighted FSM and the existing LLM
decider; they bias the menu, never replace it. The weighted-FSM choice
in characters.py still runs last, so determinism with SEED holds.

    Layer 1 — Memory Stream
        Pulls rows out of ``world.memory`` (the SQLite character_memory
        table) and scores them by recency × importance × structural
        relevance (Jaccard over kind/subject tags). No embeddings,
        no LLM — deterministic retrieval.

    Layer 2 — Beliefs
        On a reflection pass (every ``mind_reflect_every_ticks``), cluster
        recent memories by ``(kind, subject)`` and emit at most three
        beliefs per pass. Beliefs are persisted as ``character_memory``
        rows with ``kind = "belief"`` so they survive process restarts.

    Layer 3 — Goals
        A deterministic rule table maps beliefs (and a few raw drives)
        to one active ``Goal``. One goal at a time per agent.

    Layer 4 — Plan / Intentions
        ``shape_menu`` translates the active goal into additive weight
        deltas on the existing FSM menu. ``goal_context`` produces a
        one-line string for the optional LLM decider's extra_context.

The ``NpcMind`` subclass is lighter — no LLM, no reflection by default,
just the deterministic goal-from-drives rule table. NPCs that have been
promoted to sub-mains opt into the full Mind via ``Mind`` directly.

Telemetry: each cognitive op opens a child span when an OTel tracer is
attached to ``world.telemetry``; metrics for active goals / beliefs are
emitted from ``Mind.maybe_emit_gauges`` (called by the world's gauge
sweep, not here).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from contracts import (
    Metric,
    Phase,
    Role,
    State,
    World,
)


# ---------------------------------------------------------------------------
# Constants — kept module-local so they're discoverable next to the logic.
# ---------------------------------------------------------------------------


# Importance score per persisted event kind. Higher = more memorable.
# Anything not listed gets a baseline of 1 so it still scores recency / relevance.
_IMPORTANCE_TABLE: Dict[str, float] = {
    "village_wipe": 10.0,
    "char_death": 9.0,
    "npc_death": 7.0,
    "imposter_banished": 8.0,
    "creature_breach": 7.0,
    "meeting_outcome": 5.0,
    "trust_shift": 4.0,
    "homecoming": 4.0,
    "journal_entry": 3.0,
    "lighthouse_enter": 3.0,
    "music_box_destroyed": 6.0,
    "sub_main_died": 6.0,
    "item_picked_up": 1.0,
}

# Half-life for the recency component, in ticks. ~1 sim-hour at default tick_hz.
_RECENCY_HALF_LIFE_TICKS = 7200

# All persisted event kinds the Mind can reflect over.
_REFLECT_KINDS = tuple(_IMPORTANCE_TABLE.keys()) + ("belief", "reflection", "goal_open", "goal_closed")

# How many top memories the retrieval returns at most.
_RECALL_K = 8

# How many beliefs a single reflection pass may emit.
_REFLECT_BELIEFS_PER_PASS = 3

# Decay multiplier applied to existing belief confidence every reflection pass.
_BELIEF_DECAY = 0.98

# Drop a belief when confidence falls below this.
_BELIEF_MIN_CONF = 0.1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class GoalKind(str, enum.Enum):
    PROTECT_X = "protect"          # bias SHELTERING + standing near X
    INVESTIGATE_X = "investigate"  # bias INVESTIGATING + path to X
    REVENGE_X = "revenge"          # bias MEETING + pushes argument states
    FLEE_TO_Y = "flee"             # bias FLEEING toward Y
    FIND_ITEM_Z = "find_item"      # bias WANDERING/FORAGING


@dataclass
class Belief:
    key: str                       # e.g. "yellow_suspect:npc_07"
    confidence: float              # 0..1
    polarity: float                # -1..+1 (negative = denial)
    source_event_ids: List[int] = field(default_factory=list)
    created_tick: int = 0
    last_seen_tick: int = 0
    note: str = ""                 # one-line rationale (optional LLM flavour)

    def decay(self) -> None:
        self.confidence *= _BELIEF_DECAY


@dataclass
class Goal:
    kind: GoalKind
    target: str
    priority: float                # 0..1
    expires_at_tick: int
    origin_belief_key: Optional[str] = None
    opened_tick: int = 0


# ---------------------------------------------------------------------------
# Tracing helper — keeps spans optional so a missing tracer never crashes.
# ---------------------------------------------------------------------------


class _NullSpan:
    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def set_attribute(self, *_a: Any, **_k: Any) -> None:
        return None


def _span(world: World, name: str):
    """Start a child span if a tracer is attached; otherwise a no-op."""
    tele = getattr(world, "telemetry", None)
    if tele is None:
        return _NullSpan()
    try:
        tracer = tele.get_tracer()
        return tracer.start_as_current_span(name)
    except Exception:
        return _NullSpan()


# ---------------------------------------------------------------------------
# Mind
# ---------------------------------------------------------------------------


class Mind:
    """Per-agent cognitive state. Cheap to construct; heavy work is gated."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.beliefs: Dict[str, Belief] = {}
        self.active_goal: Optional[Goal] = None
        self.last_reflect_tick: int = -10**9
        self.reflections_count: int = 0
        self.last_recall_rows: int = 0  # for telemetry

    # ------------------------------------------------------------- L1 recall
    def recall(
        self,
        world: World,
        kinds: Tuple[str, ...] = _REFLECT_KINDS,
        lookback_ticks: Optional[int] = None,
        query_tags: Optional[Tuple[str, ...]] = None,
    ) -> List[Dict[str, Any]]:
        """Return up to ``_RECALL_K`` scored memory rows for this agent.

        score = mean(recency, importance, relevance) — all three in [0, 1].
        Relevance is Jaccard overlap of ``(kind, subject)`` tags between the
        query and the row. Falls back to an empty list when memory is off.
        """
        mem = getattr(world, "memory", None)
        if mem is None:
            return []
        lookback = int(lookback_ticks or world.config.memory_recall_window_ticks * 12)
        with _span(world, "mind.recall") as span:
            span.set_attribute("actor", self.agent_id)
            span.set_attribute("kinds", ",".join(kinds))
            try:
                rows = mem.recall_for(world, self.agent_id, kinds, lookback)
            except Exception:
                rows = []
            scored = []
            tags = set(query_tags or ())
            now = int(world.tick_count)
            for r in rows:
                tick = int(r.get("tick", 0))
                kind = str(r.get("kind", ""))
                subject = str(r.get("subject", ""))
                # Recency: exp half-life.
                dt = max(0, now - tick)
                recency = 0.5 ** (dt / _RECENCY_HALF_LIFE_TICKS)
                # Importance: from the deterministic table, normalised.
                importance = _IMPORTANCE_TABLE.get(kind, 1.0) / 10.0
                # Relevance: Jaccard over row tags vs query tags. Empty query
                # gives a neutral 0.5 so recency + importance carry the weight.
                row_tags = {kind, subject} - {""}
                if not tags:
                    relevance = 0.5
                else:
                    inter = len(row_tags & tags)
                    union = len(row_tags | tags) or 1
                    relevance = inter / union
                score = (recency + importance + relevance) / 3.0
                scored.append((score, r))
            scored.sort(key=lambda kv: kv[0], reverse=True)
            top = [r for _, r in scored[:_RECALL_K]]
            self.last_recall_rows = len(top)
            span.set_attribute("rows_returned", len(top))
            return top

    # -------------------------------------------------------- L2 reflection
    def maybe_reflect(self, world: World, agent: Any) -> None:
        """Run reflection if the cadence has elapsed since the last pass."""
        every = max(60, int(getattr(world.config, "mind_reflect_every_ticks", 600)))
        if world.tick_count - self.last_reflect_tick < every:
            # Still decay existing beliefs at a much cheaper cadence.
            return
        self._reflect(world, agent)
        self.last_reflect_tick = world.tick_count

    def _reflect(self, world: World, agent: Any) -> None:
        with _span(world, "mind.reflect") as span:
            span.set_attribute("actor", self.agent_id)
            # 1) Decay existing beliefs uniformly so stale ones fall off.
            for b in list(self.beliefs.values()):
                b.decay()
                if b.confidence < _BELIEF_MIN_CONF:
                    self.beliefs.pop(b.key, None)
            # 2) Pull up to top-50 (we use recall_for directly here to avoid
            #    the recall scoring overhead — clustering wants raw rows).
            mem = getattr(world, "memory", None)
            if mem is None:
                span.set_attribute("clusters", 0)
                span.set_attribute("beliefs_emitted", 0)
                return
            try:
                rows = mem.recall_for(
                    world,
                    self.agent_id,
                    _REFLECT_KINDS,
                    int(world.config.memory_recall_window_ticks * 12),
                )
            except Exception:
                rows = []
            # 3) Cluster by (kind, subject); count + sum-importance.
            clusters: Dict[Tuple[str, str], Dict[str, Any]] = {}
            for r in rows:
                kind = str(r.get("kind", ""))
                subject = str(r.get("subject", ""))
                if not subject or kind in ("belief", "reflection", "goal_open", "goal_closed"):
                    continue
                key = (kind, subject)
                c = clusters.setdefault(
                    key, {"hits": 0, "imp": 0.0, "ticks": [], "last_tick": 0}
                )
                c["hits"] += 1
                c["imp"] += _IMPORTANCE_TABLE.get(kind, 1.0)
                c["last_tick"] = max(int(c["last_tick"]), int(r.get("tick", 0)))
            # 4) Promote clusters into beliefs via the deterministic naming rules.
            emitted = 0
            for (kind, subject), c in clusters.items():
                if emitted >= _REFLECT_BELIEFS_PER_PASS:
                    break
                if c["hits"] < 3 and c["imp"] < 12.0:
                    continue
                belief = self._belief_for_cluster(kind, subject, c, world.tick_count)
                if belief is None:
                    continue
                # Bump confidence on existing belief instead of re-creating.
                existing = self.beliefs.get(belief.key)
                if existing is not None:
                    existing.confidence = min(1.0, existing.confidence + 0.2 * belief.confidence)
                    existing.last_seen_tick = world.tick_count
                else:
                    self.beliefs[belief.key] = belief
                emitted += 1
                self._persist_belief(world, belief)
            span.set_attribute("clusters", len(clusters))
            span.set_attribute("beliefs_emitted", emitted)
            self.reflections_count += 1
            # Telemetry: counter for reflection rate.
            tele = getattr(world, "telemetry", None)
            if tele is not None:
                try:
                    tele.counter_inc(
                        Metric.MIND_REFLECTIONS_TOTAL, 1.0, {"actor": self.agent_id}
                    )
                except Exception:
                    pass
            # 5) Re-evaluate goal after new beliefs may have landed.
            self.regoal(world, agent)

    def _belief_for_cluster(
        self,
        kind: str,
        subject: str,
        cluster: Dict[str, Any],
        tick: int,
    ) -> Optional[Belief]:
        hits = int(cluster["hits"])
        conf = min(1.0, hits / 5.0)
        # Deterministic naming. Subject is usually a building id or an actor id.
        if kind == "creature_breach":
            key = f"house_weak:{subject}"
            return Belief(
                key=key, confidence=conf, polarity=+1.0,
                created_tick=tick, last_seen_tick=tick,
                note=f"breaches at {subject} ×{hits}",
            )
        if kind == "trust_shift":
            # If subject's trust shifted negatively often, mark them suspect.
            key = f"yellow_suspect:{subject}"
            return Belief(
                key=key, confidence=conf, polarity=+1.0,
                created_tick=tick, last_seen_tick=tick,
                note=f"trust shifted around {subject} ×{hits}",
            )
        if kind == "meeting_outcome" and "imposter" in subject.lower():
            key = f"council_distrust:{subject}"
            return Belief(
                key=key, confidence=conf, polarity=+1.0,
                created_tick=tick, last_seen_tick=tick,
                note=f"contested vote on {subject} ×{hits}",
            )
        if kind in ("char_death", "npc_death", "sub_main_died"):
            key = f"loss:{subject}"
            return Belief(
                key=key, confidence=conf, polarity=+1.0,
                created_tick=tick, last_seen_tick=tick,
                note=f"loss of {subject}",
            )
        if kind == "imposter_banished":
            key = f"yellow_resolved:{subject}"
            return Belief(
                key=key, confidence=conf, polarity=-1.0,
                created_tick=tick, last_seen_tick=tick,
                note=f"imposter banished: {subject}",
            )
        return None

    def _persist_belief(self, world: World, belief: Belief) -> None:
        mem = getattr(world, "memory", None)
        if mem is None:
            return
        try:
            mem.record_character_memory(
                world,
                self.agent_id,
                "belief",
                belief.key,
                belief.note,
                {
                    "confidence": belief.confidence,
                    "polarity": belief.polarity,
                    "importance": 6,  # beliefs are mid-importance themselves
                },
            )
        except Exception:
            pass

    # --------------------------------------------------------- L3 goals
    def regoal(self, world: World, agent: Any) -> None:
        """Evaluate beliefs + drives, possibly open or replace the active goal."""
        with _span(world, "mind.regoal") as span:
            span.set_attribute("actor", self.agent_id)
            old = self.active_goal
            # Expire stale goals.
            if old is not None and world.tick_count >= old.expires_at_tick:
                self._close_goal(world, old, reason="expired")
                old = None
            new = self._pick_goal(world, agent)
            if new is None:
                self.active_goal = old
                span.set_attribute("old_goal", _goal_label(old))
                span.set_attribute("new_goal", _goal_label(old))
                return
            # Only swap if the new goal is meaningfully higher priority.
            if old is None or new.priority > old.priority + 0.05 or old.kind == new.kind and old.target != new.target:
                if old is not None:
                    self._close_goal(world, old, reason="replaced")
                self.active_goal = new
                self._open_goal(world, new)
            span.set_attribute("old_goal", _goal_label(old))
            span.set_attribute("new_goal", _goal_label(self.active_goal))

    def _pick_goal(self, world: World, agent: Any) -> Optional[Goal]:
        """Deterministic generator. One active goal at a time, picked by
        highest priority among satisfied triggers."""
        ttl = int(world.config.mind_goal_ttl_ticks)
        candidates: List[Goal] = []
        # PROTECT_X: house_weak:X with conf>0.6 + agent role is CARETAKER / SHERIFF / LEADER_COLONY
        role = getattr(agent, "role", None)
        protector = role in (Role.CARETAKER, Role.SHERIFF, Role.LEADER_COLONY, Role.PRIEST)
        for key, b in self.beliefs.items():
            if not key.startswith("house_weak:") or b.confidence < 0.6:
                continue
            target = key.split(":", 1)[1]
            if not protector:
                continue
            candidates.append(Goal(
                kind=GoalKind.PROTECT_X,
                target=target,
                priority=0.7 * b.confidence,
                expires_at_tick=world.tick_count + ttl,
                origin_belief_key=key,
            ))
        # REVENGE_X: yellow_suspect:Y with conf>0.5 — anyone can carry it.
        for key, b in self.beliefs.items():
            if not key.startswith("yellow_suspect:") or b.confidence < 0.5:
                continue
            target = key.split(":", 1)[1]
            candidates.append(Goal(
                kind=GoalKind.REVENGE_X,
                target=target,
                priority=0.8 * b.confidence,
                expires_at_tick=world.tick_count + ttl,
                origin_belief_key=key,
            ))
        # FIND_ITEM_Z: low food supply + a forager-shaped agent.
        food_low = float(getattr(world, "food_supply", 100.0)) < 30.0
        if food_low and role in (Role.ENGINEER, Role.BRIDGE, Role.INVESTIGATOR, Role.DEPUTY):
            candidates.append(Goal(
                kind=GoalKind.FIND_ITEM_Z,
                target="food",
                priority=0.6,
                expires_at_tick=world.tick_count + ttl,
                origin_belief_key=None,
            ))
        # INVESTIGATE_X: awareness[any_npc] > 0.7.
        aware = getattr(agent, "awareness", None) or {}
        if isinstance(aware, dict):
            for npc_id, score in aware.items():
                try:
                    s = float(score)
                except (TypeError, ValueError):
                    continue
                if s <= 0.7:
                    continue
                candidates.append(Goal(
                    kind=GoalKind.INVESTIGATE_X,
                    target=str(npc_id),
                    priority=0.65 * min(1.0, s),
                    expires_at_tick=world.tick_count + ttl,
                    origin_belief_key=None,
                ))
                break  # one investigation is plenty
        # FLEE_TO_Y: high fear and not yet home.
        fear = float(getattr(agent, "fear", 0.0))
        if fear > 70.0:
            home_id = getattr(agent, "dwelling_id", None) or getattr(agent, "home_id", None)
            if home_id:
                candidates.append(Goal(
                    kind=GoalKind.FLEE_TO_Y,
                    target=str(home_id),
                    priority=0.9,
                    expires_at_tick=world.tick_count + ttl // 2,
                    origin_belief_key=None,
                ))
        if not candidates:
            return None
        candidates.sort(key=lambda g: g.priority, reverse=True)
        chosen = candidates[0]
        chosen.opened_tick = world.tick_count
        return chosen

    def _open_goal(self, world: World, goal: Goal) -> None:
        mem = getattr(world, "memory", None)
        if mem is not None:
            try:
                mem.record_character_memory(
                    world,
                    self.agent_id,
                    "goal_open",
                    str(goal.kind.value),
                    str(goal.target),
                    {
                        "priority": goal.priority,
                        "origin_belief": goal.origin_belief_key or "",
                        "importance": 5,
                    },
                )
            except Exception:
                pass
        tele = getattr(world, "telemetry", None)
        if tele is not None:
            try:
                tele.get_logger().info(
                    "mind.goal_open actor=%s kind=%s target=%s priority=%.2f",
                    self.agent_id, goal.kind.value, goal.target, goal.priority,
                )
            except Exception:
                pass

    def _close_goal(self, world: World, goal: Goal, *, reason: str) -> None:
        mem = getattr(world, "memory", None)
        if mem is not None:
            try:
                mem.record_character_memory(
                    world,
                    self.agent_id,
                    "goal_closed",
                    str(goal.kind.value),
                    str(goal.target),
                    {"reason": reason, "importance": 3},
                )
            except Exception:
                pass

    # ------------------------------------------------------- L4 plan / bias
    def shape_menu(
        self,
        world: World,
        agent: Any,
        menu: List[Tuple[State, float]],
    ) -> List[Tuple[State, float]]:
        """Apply goal-derived additive weight deltas to the candidate menu.

        Returns a NEW list — never mutates the caller's. Unknown states in
        the goal's target table are silently ignored.
        """
        if not menu:
            return menu
        goal = self.active_goal
        if goal is None:
            return menu
        with _span(world, "mind.shape_menu") as span:
            span.set_attribute("actor", self.agent_id)
            span.set_attribute("goal", _goal_label(goal))
            deltas = self._menu_deltas(world, agent, goal)
            span.set_attribute("weight_deltas", _deltas_label(deltas))
            if not deltas:
                return menu
            out: List[Tuple[State, float]] = []
            for s, w in menu:
                out.append((s, max(0.0, float(w) + deltas.get(s, 0.0))))
            return out

    def _menu_deltas(
        self, world: World, agent: Any, goal: Goal
    ) -> Dict[State, float]:
        d: Dict[State, float] = {}
        if goal.kind == GoalKind.PROTECT_X:
            d[State.SHELTERING] = 0.8
            d[State.PATROLLING] = 0.4
        elif goal.kind == GoalKind.REVENGE_X:
            d[State.MEETING] = 1.5
            d[State.ARGUING] = 0.4
        elif goal.kind == GoalKind.INVESTIGATE_X:
            d[State.INVESTIGATING] = 0.7
            d[State.PATROLLING] = 0.3
        elif goal.kind == GoalKind.FLEE_TO_Y:
            d[State.FLEEING] = 1.4
            d[State.SHELTERING] = 0.6
        elif goal.kind == GoalKind.FIND_ITEM_Z:
            # If the barn is down, FORAGING is the right verb; otherwise SCAVENGING.
            if int(getattr(world, "barn_destroyed_until_tick", 0)) > world.tick_count:
                d[State.FORAGING] = 1.0
            else:
                d[State.SCAVENGING] = 0.6
                d[State.WANDERING] = 0.3
        return d

    def goal_context(self) -> str:
        """A ≤140-char string passed as ``extra_context`` to the LLM decider."""
        g = self.active_goal
        if g is None:
            return ""
        return f"Goal: {g.kind.value}({g.target}) priority={g.priority:.2f}"

    # ------------------------------------------------------------ snapshot
    def to_snapshot(self) -> Dict[str, Any]:
        """For the dossier endpoint. Not on the broadcast snapshot."""
        top = sorted(
            self.beliefs.values(), key=lambda b: b.confidence, reverse=True
        )[:3]
        return {
            "active_goal": (
                {
                    "kind": self.active_goal.kind.value,
                    "target": self.active_goal.target,
                    "priority": round(self.active_goal.priority, 2),
                    "origin_belief": self.active_goal.origin_belief_key or "",
                    "opened_tick": self.active_goal.opened_tick,
                }
                if self.active_goal is not None
                else None
            ),
            "beliefs": [
                {
                    "key": b.key,
                    "confidence": round(b.confidence, 2),
                    "polarity": int(b.polarity),
                    "note": b.note,
                    "last_seen_tick": b.last_seen_tick,
                }
                for b in top
            ],
            "reflections_count": self.reflections_count,
            "last_reflect_tick": (
                self.last_reflect_tick if self.last_reflect_tick > -10**8 else None
            ),
        }


# ---------------------------------------------------------------------------
# NpcMind — lighter cognitive layer for NPCs.
# ---------------------------------------------------------------------------


class NpcMind(Mind):
    """No reflection; deterministic goal table only. Cheap per tick."""

    def maybe_reflect(self, world: World, agent: Any) -> None:
        # NPCs don't reflect by default. Only the deterministic goal path runs.
        self.regoal(world, agent)

    def _pick_goal(self, world: World, agent: Any) -> Optional[Goal]:
        ttl = int(world.config.mind_goal_ttl_ticks)
        candidates: List[Goal] = []
        # FLEE_TO_Y: high fear, has a home, dusk/night.
        fear = float(getattr(agent, "fear", 0.0))
        phase = world.time.phase
        home_id = getattr(agent, "home_id", None)
        if fear > 60.0 and home_id and phase in (Phase.DUSK, Phase.NIGHT):
            candidates.append(Goal(
                kind=GoalKind.FLEE_TO_Y, target=str(home_id),
                priority=0.8, expires_at_tick=world.tick_count + ttl // 3,
            ))
        # FIND_ITEM_Z: food crisis + barn down → forage.
        barn_down = int(getattr(world, "barn_destroyed_until_tick", 0)) > world.tick_count
        food_low = float(getattr(world, "food_supply", 100.0)) < 30.0
        if food_low and barn_down:
            candidates.append(Goal(
                kind=GoalKind.FIND_ITEM_Z, target="food",
                priority=0.55, expires_at_tick=world.tick_count + ttl // 2,
            ))
        if not candidates:
            return None
        candidates.sort(key=lambda g: g.priority, reverse=True)
        chosen = candidates[0]
        chosen.opened_tick = world.tick_count
        return chosen

    def _menu_deltas(self, world: World, agent: Any, goal: Goal) -> Dict[State, float]:
        # NPC menu states are narrower: WORKING, SOCIALIZING, SHELTERING, FLEEING, FORAGING.
        d: Dict[State, float] = {}
        if goal.kind == GoalKind.FLEE_TO_Y:
            d[State.FLEEING] = 1.2
            d[State.SHELTERING] = 0.8
        elif goal.kind == GoalKind.FIND_ITEM_Z:
            d[State.FORAGING] = 0.9
            d[State.WORKING] = 0.3
        return d


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------


def _goal_label(g: Optional[Goal]) -> str:
    if g is None:
        return "none"
    return f"{g.kind.value}:{g.target}"


def _deltas_label(d: Dict[State, float]) -> str:
    if not d:
        return ""
    return ",".join(f"{s.value}={v:+.2f}" for s, v in d.items())


# ---------------------------------------------------------------------------
# World-level gauge emitter — called by simulation.py after tick.
# ---------------------------------------------------------------------------


def emit_mind_gauges(world: World) -> None:
    """Walk world.agents, push two gauges:
        from_sim_mind_beliefs_active (sum across all minds)
        from_sim_mind_goals_active{kind} (count per goal kind)
    """
    tele = getattr(world, "telemetry", None)
    if tele is None:
        return
    beliefs = 0
    by_kind: Dict[str, int] = {}
    for a in world.agents.values():
        m = getattr(a, "mind", None)
        if m is None:
            continue
        beliefs += len(m.beliefs)
        if m.active_goal is not None:
            k = m.active_goal.kind.value
            by_kind[k] = by_kind.get(k, 0) + 1
    try:
        tele.gauge_set(Metric.MIND_BELIEFS_ACTIVE, float(beliefs))
    except Exception:
        pass
    # Push a gauge per kind for cardinality-bounded label series.
    for k, n in by_kind.items():
        try:
            tele.gauge_set(Metric.MIND_GOALS_ACTIVE, float(n), {"kind": k})
        except Exception:
            pass
    # Push zero gauges for the kinds we didn't see so series go to 0 instead of
    # going stale, and the kinds remain enumerable.
    for k in (gk.value for gk in GoalKind):
        if k in by_kind:
            continue
        try:
            tele.gauge_set(Metric.MIND_GOALS_ACTIVE, 0.0, {"kind": k})
        except Exception:
            pass
