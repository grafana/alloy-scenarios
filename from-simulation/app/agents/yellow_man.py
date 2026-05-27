"""
The Man in Yellow — the show's central horror motif.

Runs in three sub-modes stored on ``world.yellow_active.mode``:

    DORMANT       Off-stage. Periodically taints NPCs (``yellow_touched_npcs``)
                  during the day; rolls an appearance schedule.
    VISIBLE_MARCH Walks the ``YELLOW_MARCH_PATH`` waypoints once as a
                  ``MarkerClass.MAN_IN_YELLOW`` supernatural. NPCs within
                  60 px are forced WANDERING for 10 ticks.
    IMPOSTER      Hijacks a random existing NPC. No new marker is drawn —
                  the disguised NPC's existing dot is what the player sees.
                  Internally biases meeting votes and lures children outside
                  talisman-protected doors at NIGHT (unlocks the door).

When an appearance is live, ``world.yellow_active.deadline_tick`` is the
hard timer. If the deadline elapses before the villagers either banish him
(IMPOSTER mode is voted out in an ``imposter_suspicion`` meeting) or he
finishes his visible march, a **village wipe** fires:

    * ``village_wipe`` event (severity=crit)
    * ``from_sim_village_wipes_total`` counter increments
    * ``world.pending_reset = True``  -> Agent A reseeds next tick

Meeting consumption (Agent B emits ``MeetingOutcome`` with
``topic == "imposter_suspicion"``):

    payload {accused_npc_id, guilty}:
        guilty + accused matches disguise  -> imposter_banished, +5 sanity all,
                                              mode -> DORMANT
        guilty + accused != disguise       -> kill the innocent NPC, fear spike
        not guilty                         -> just log it
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from contracts import (
    Agent,
    AgentKind,
    Event,
    MarkerClass,
    MeetingOutcome,
    Metric,
    Phase,
    State,
    Status,
    World,
    YellowMode,
    YELLOW_MARCH_PATH,
)
from agents.npcs import NPC
from agents import music_box as _music_box


# ---------------------------------------------------------------------------
# Visible-march supernatural marker
# ---------------------------------------------------------------------------


class _YellowMarchMarker:
    """Lightweight ``Agent``-shaped object for ``world.supernaturals``.

    We don't subclass ``Agent`` directly because the visible march has no
    autonomous tick — the yellow_man module steps it from ``tick_yellow``.
    But it honours the snapshot contract (``to_dict``) so the frontend
    renders it the same way as any other supernatural.
    """

    kind = AgentKind.SUPERNATURAL
    marker_class = MarkerClass.MAN_IN_YELLOW

    def __init__(self, x: float, y: float) -> None:
        self.id = "yellow_man_march"
        self.x = float(x)
        self.y = float(y)

    def tick(self, world: World) -> None:  # pragma: no cover - stepped externally
        pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "marker_class": self.marker_class.value,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
        }


# ---------------------------------------------------------------------------
# Scheduling state — kept module-local; world only stores the active payload.
# ---------------------------------------------------------------------------


@dataclass
class _Schedule:
    next_appearance_tick: int = 0
    last_taint_day: int = -1
    seen_outcome_count: int = 0  # how many meeting_outcomes we've already scanned


_SCHED = _Schedule()


def _ticks_per_day(world: World) -> int:
    """Best-effort conversion. The engine ticks ``tick_hz`` times per second
    and ``time_scale`` minutes pass per tick. 24h = 1440 sim-minutes, so
    days-of-ticks = 1440 / time_scale.
    """
    scale = max(0.001, float(world.config.time_scale))
    return max(60, int(1440.0 / scale))


def _schedule_next_appearance(world: World) -> None:
    """Roll a 5–10 sim-day timer (configurable)."""
    cfg = world.config
    days_min = max(1, cfg.yellow_appearance_days_min)
    days_max = max(days_min, cfg.yellow_appearance_days_max)
    days = world.rng.randint(days_min, days_max)
    _SCHED.next_appearance_tick = world.tick_count + days * _ticks_per_day(world)


def _maybe_taint_npcs(world: World) -> None:
    """Once per sim-day, taint a few unsuspecting NPCs."""
    today = world.time.day
    if today == _SCHED.last_taint_day:
        return
    _SCHED.last_taint_day = today

    rng = world.rng
    npcs = [
        a for a in world.agents.values()
        if getattr(a, "kind", None) == AgentKind.NPC
        and getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
    ]
    if not npcs:
        return
    n_taint = min(len(npcs), rng.randint(1, 3))
    for npc in rng.sample(npcs, n_taint):
        world.yellow_touched_npcs.add(npc.id)


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


# ---------------------------------------------------------------------------
# Appearance starters
# ---------------------------------------------------------------------------


def _start_appearance(world: World) -> None:
    """Decide IMPOSTER vs VISIBLE_MARCH and arm the deadline.

    v2: in IMPOSTER mode we now pick ``[yellow_hydra_min, yellow_hydra_max]``
    distinct NPC tendrils. ``disguised_as`` points at the "leader" tendril
    (the most visible one); ``tendrils`` lists all of them. OUTSIDERS are
    excluded from the disguise pool — only plain NPCs can be hijacked.
    """
    cfg = world.config
    rng = world.rng
    ya = world.yellow_active

    # Pick mode.
    if rng.random() < cfg.yellow_imposter_prob:
        npcs = [
            a for a in world.agents.values()
            if getattr(a, "kind", None) == AgentKind.NPC
            and getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
        ]
        if not npcs:
            # No NPC to wear -> fall back to a visible march.
            _begin_march(world)
            return

        # Decide how many tendrils, clamped to the available NPC count.
        hydra_min = max(1, cfg.yellow_hydra_min)
        hydra_max = max(hydra_min, cfg.yellow_hydra_max)
        n_hydra = rng.randint(hydra_min, hydra_max)
        n_hydra = max(1, min(n_hydra, len(npcs)))

        chosen = rng.sample(npcs, n_hydra)
        tendril_ids = [n.id for n in chosen]
        leader_id = tendril_ids[0]

        ya.mode = YellowMode.IMPOSTER
        ya.disguised_as = leader_id
        ya.tendrils = list(tendril_ids)
        # Track the initial hydra count so banishments can shorten the deadline
        # proportionally. Stored via setattr because YellowState's dataclass
        # is owned by contracts.py and we don't add fields unilaterally.
        setattr(ya, "_initial_hydra", n_hydra)

        # All tendrils are touched definitionally.
        for tid in tendril_ids:
            world.yellow_touched_npcs.add(tid)
    else:
        _begin_march(world)
        return

    ya.started_at_tick = world.tick_count
    ya.deadline_tick = world.tick_count + cfg.yellow_deadline_ticks
    ya.path_index = 0

    world.emit(
        Event(
            tick=world.tick_count,
            type="yellow_appearance",
            subject="yellow_man",
            detail=(
                f"mode={ya.mode.value} disguised_as={ya.disguised_as} "
                f"tendrils={len(ya.tendrils)}"
            ),
            severity="warn",
        )
    )
    if ya.mode == YellowMode.IMPOSTER:
        world.emit(
            Event(
                tick=world.tick_count,
                type="yellow_imposter_join",
                subject=ya.disguised_as or "yellow_man",
                detail="A stranger has slipped into the village",
                severity="warn",
            )
        )
        for tid in ya.tendrils:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="yellow_tendril_added",
                    subject=tid,
                    detail=f"tendril count now {len(ya.tendrils)}",
                    severity="warn",
                )
            )


def _begin_march(world: World) -> None:
    cfg = world.config
    ya = world.yellow_active
    ya.mode = YellowMode.VISIBLE_MARCH
    ya.disguised_as = None
    ya.path_index = 0
    ya.started_at_tick = world.tick_count
    ya.deadline_tick = world.tick_count + cfg.yellow_deadline_ticks

    # Spawn the visible marker at the first waypoint.
    if YELLOW_MARCH_PATH:
        x, y = YELLOW_MARCH_PATH[0]
        world.supernaturals.append(_YellowMarchMarker(x, y))

    world.emit(
        Event(
            tick=world.tick_count,
            type="yellow_appearance",
            subject="yellow_man",
            detail=f"mode={ya.mode.value}",
            severity="warn",
        )
    )


def _end_appearance(world: World, reason: str) -> None:
    """Return to DORMANT cleanly. Caller decides whether to emit anything."""
    ya = world.yellow_active
    # Strip any march marker from supernaturals.
    world.supernaturals[:] = [
        s for s in world.supernaturals
        if getattr(s, "id", None) != "yellow_man_march"
    ]
    ya.mode = YellowMode.DORMANT
    ya.disguised_as = None
    ya.deadline_tick = 0
    ya.started_at_tick = 0
    ya.path_index = 0
    ya.tendrils.clear()
    # Drop the hydra-count sentinel.
    if hasattr(ya, "_initial_hydra"):
        try:
            delattr(ya, "_initial_hydra")
        except AttributeError:
            pass
    # Touched set persists across appearances by design (per spec).
    _schedule_next_appearance(world)


# ---------------------------------------------------------------------------
# Per-mode tick helpers
# ---------------------------------------------------------------------------


_MARCH_STEP_PX = 8.0
_MARCH_INFLUENCE_RADIUS = 60.0
_WANDER_FORCE_TICKS = 10


def _tick_visible_march(world: World) -> None:
    ya = world.yellow_active
    if not YELLOW_MARCH_PATH:
        _end_appearance(world, "no_path")
        return

    # Find our marker.
    marker: Optional[_YellowMarchMarker] = None
    for s in world.supernaturals:
        if getattr(s, "id", None) == "yellow_man_march":
            marker = s  # type: ignore[assignment]
            break
    if marker is None:
        # Lost it somehow; respawn at current waypoint.
        wx, wy = YELLOW_MARCH_PATH[min(ya.path_index, len(YELLOW_MARCH_PATH) - 1)]
        marker = _YellowMarchMarker(wx, wy)
        world.supernaturals.append(marker)

    # Step toward current waypoint.
    if ya.path_index >= len(YELLOW_MARCH_PATH):
        # Path done.
        _end_appearance(world, "march_complete")
        return

    tx, ty = YELLOW_MARCH_PATH[ya.path_index]
    dx, dy = tx - marker.x, ty - marker.y
    d = math.hypot(dx, dy)
    if d <= _MARCH_STEP_PX:
        marker.x, marker.y = tx, ty
        ya.path_index += 1
    else:
        marker.x += dx * (_MARCH_STEP_PX / d)
        marker.y += dy * (_MARCH_STEP_PX / d)

    # Influence nearby NPCs.
    wander_until = world.tick_count + _WANDER_FORCE_TICKS
    for a in world.agents.values():
        if getattr(a, "kind", None) != AgentKind.NPC:
            continue
        if _distance(marker.x, marker.y, a.x, a.y) <= _MARCH_INFLUENCE_RADIUS:
            if isinstance(a, NPC):
                a.force_wander(wander_until)


# Imposter action menu — also used as the LLM decision menu.
_IMPOSTER_ACTIONS = ("LURK_NEAR_CHILD", "STIR_MEETING", "LIE_LOW", "LURE_OUTSIDE", "DROP_BOX")


def _find_disguise(world: World) -> Optional[NPC]:
    ya = world.yellow_active
    if not ya.disguised_as:
        return None
    a = world.agents.get(ya.disguised_as)
    if isinstance(a, NPC) and a.status == Status.ACTIVE:
        return a
    return None


def _live_tendrils(world: World) -> List[NPC]:
    """Return the list of currently-living tendril NPCs.

    Side-effect: prunes ``ya.tendrils`` of any ids that no longer point to an
    active NPC (the underlying agent may have been reaped between ticks).
    """
    ya = world.yellow_active
    out: List[NPC] = []
    pruned: List[str] = []
    for tid in list(ya.tendrils):
        a = world.agents.get(tid)
        if isinstance(a, NPC) and a.status == Status.ACTIVE:
            out.append(a)
        else:
            pruned.append(tid)
    if pruned:
        ya.tendrils = [t for t in ya.tendrils if t not in pruned]
        # Keep ``disguised_as`` consistent — promote a survivor if the leader fell.
        if ya.disguised_as in pruned:
            ya.disguised_as = ya.tendrils[0] if ya.tendrils else None
    return out


def _children(world: World) -> List[Any]:
    """Return any agents tagged Role.CHILD. Agent B owns the role attr."""
    out = []
    for a in world.agents.values():
        if getattr(a, "kind", None) == AgentKind.CHARACTER:
            role = getattr(a, "role", None)
            # Compare by value to dodge import order with characters module.
            if role is not None and getattr(role, "value", role) == "CHILD":
                out.append(a)
    return out


def _apply_imposter_action(world: World, npc: NPC, action: str) -> None:
    rng = world.rng
    if action == "LURK_NEAR_CHILD":
        kids = _children(world)
        if kids:
            kid = rng.choice(kids)
            npc.target_x = kid.x + rng.uniform(-20, 20)
            npc.target_y = kid.y + rng.uniform(-20, 20)
    elif action == "STIR_MEETING":
        # Drift toward the church (meeting venue) and flip state to ARGUING.
        for b in world.buildings.values():
            if b.role_tag == "church":
                npc.target_x = b.x + rng.uniform(-20, 20)
                npc.target_y = b.y + rng.uniform(-20, 20)
                break
        npc.state = State.ARGUING
    elif action == "LIE_LOW":
        # Park near the diner; act normal.
        for b in world.buildings.values():
            if b.role_tag == "diner":
                npc.target_x = b.x + rng.uniform(-25, 25)
                npc.target_y = b.y + rng.uniform(-25, 25)
                break
        npc.state = State.SOCIALIZING
    elif action == "LURE_OUTSIDE":
        # NIGHT-only: try to unlock a talisman door so a hypnotized kid can leave.
        if world.time.phase == Phase.NIGHT:
            talismans = [b for b in world.buildings.values() if b.has_talisman and b.locked]
            if talismans:
                b = rng.choice(talismans)
                b.locked = False
                npc.target_x = b.x + rng.uniform(-15, 15)
                npc.target_y = b.y + rng.uniform(25, 45)
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="yellow_imposter_acted",
                        subject=npc.id,
                        detail=f"unlocked {b.id}",
                        severity="warn",
                    )
                )
    elif action == "DROP_BOX":
        # v4: force-spawn the Music Box just outside the npc's current pos.
        # No-op if a box already exists. Drop it slightly away so the imposter
        # isn't the obvious candidate to grab it.
        drop_xy = (
            npc.x + rng.uniform(-30.0, 30.0),
            npc.y + rng.uniform(-30.0, 30.0),
        )
        box = _music_box.force_drop(world, drop_xy)
        if box is not None:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="yellow_imposter_acted",
                    subject=npc.id,
                    detail=f"left a music box at ({round(drop_xy[0],1)}, {round(drop_xy[1],1)})",
                    severity="warn",
                )
            )


def _consult_llm(world: World, npc: NPC) -> Optional[str]:
    """If an LLM decider is wired, ask it which action to take."""
    decider = getattr(world, "llm_decider", None)
    if decider is None:
        return None
    rate = world.config.llm_yellow_rate
    try:
        # The decider interface (defined by Agent A's llm package) returns
        # either a chosen option string or None when rate-limited / disabled.
        return decider.maybe_decide(
            actor=f"yellow_man:{npc.id}",
            rate=rate,
            options=list(_IMPOSTER_ACTIONS),
            context={
                "tick": world.tick_count,
                "phase": world.time.phase.value,
                "disguised_as": npc.id,
                "n_children_visible": len(_children(world)),
            },
        )
    except Exception:
        return None


def _tick_imposter(world: World) -> None:
    """Hydra-aware imposter tick.

    Every live tendril gets the subtle fear bias each tick. To keep behaviour
    legible (and not have every tendril simultaneously LURE_OUTSIDE on one tick),
    we pick a single random tendril each tick to apply an imposter action to.
    """
    tendrils = _live_tendrils(world)
    if not tendrils:
        # Every tendril is dead/missing — abort silently and reschedule.
        _end_appearance(world, "disguise_lost")
        return

    # Subtle fear bias on every tendril — they all read slightly "off".
    for t in tendrils:
        t.fear = min(1.0, t.fear + 0.0005)

    # Pick one tendril to act through this tick.
    actor = world.rng.choice(tendrils)

    # Pick an action: LLM if available, else weighted random.
    action = _consult_llm(world, actor)
    if action is None:
        rng = world.rng
        # Phase-aware weighting.
        if world.time.phase == Phase.NIGHT:
            weights = {"LURE_OUTSIDE": 0.45, "LURK_NEAR_CHILD": 0.3, "LIE_LOW": 0.2, "STIR_MEETING": 0.05}
        elif world.time.phase == Phase.DUSK:
            weights = {"STIR_MEETING": 0.4, "LURK_NEAR_CHILD": 0.3, "LIE_LOW": 0.2, "LURE_OUTSIDE": 0.1}
        else:
            weights = {"LIE_LOW": 0.5, "LURK_NEAR_CHILD": 0.25, "STIR_MEETING": 0.2, "LURE_OUTSIDE": 0.05}
        # 1/8 ticks we actually pick — otherwise let normal NPC tick run.
        if rng.random() < 0.12:
            action = rng.choices(
                list(weights.keys()), weights=list(weights.values()), k=1
            )[0]
        else:
            action = None

    if action is not None:
        _apply_imposter_action(world, actor, action)


# ---------------------------------------------------------------------------
# Meeting outcomes consumption
# ---------------------------------------------------------------------------


def _consume_meeting_outcomes(world: World) -> None:
    """Process any new ``imposter_suspicion`` outcomes since the last tick."""
    outcomes: List[MeetingOutcome] = world.meeting_outcomes
    start = _SCHED.seen_outcome_count
    # New ones are appended at the end.
    for i in range(start, len(outcomes)):
        mo = outcomes[i]
        if mo.topic != "imposter_suspicion":
            continue
        _handle_suspicion(world, mo)
    _SCHED.seen_outcome_count = len(outcomes)


def _handle_suspicion(world: World, mo: MeetingOutcome) -> None:
    """Hydra-aware vote handling.

    v2 rules:
        * Not guilty           -> just log it (unchanged).
        * Guilty + a tendril   -> banish that tendril; shorten deadline
                                  proportionally; if no tendrils remain, the
                                  whole imposter is banished (sanity bump).
        * Guilty + not tendril -> innocent dies; fear spike; Yellow stays.
    """
    ya = world.yellow_active
    accused = mo.payload.get("accused_npc_id")
    guilty = bool(mo.payload.get("guilty"))

    if not guilty:
        # Just a log line — they couldn't agree, life goes on.
        world.emit(
            Event(
                tick=world.tick_count,
                type="imposter_vote",
                subject=accused or "unknown",
                detail="not guilty",
                severity="info",
            )
        )
        return

    # Guilty + the accused is one of our tendrils -> tendril banished.
    if (
        accused is not None
        and ya.mode == YellowMode.IMPOSTER
        and accused in ya.tendrils
    ):
        # Remove the tendril.
        ya.tendrils = [t for t in ya.tendrils if t != accused]
        # Kill the now-exposed tendril NPC.
        npc = world.agents.get(accused)
        if npc is not None:
            try:
                npc.status = Status.DEAD
            except Exception:
                pass

        world.emit(
            Event(
                tick=world.tick_count,
                type="yellow_tendril_banished",
                subject=accused,
                detail=f"tendrils remaining: {len(ya.tendrils)}",
                severity="warn",
            )
        )

        # Shorten the deadline proportionally to initial hydra size.
        initial = int(getattr(ya, "_initial_hydra", max(1, len(ya.tendrils) + 1)))
        if initial > 0:
            shrink = world.config.yellow_deadline_ticks // initial
            ya.deadline_tick = max(world.tick_count + 1, ya.deadline_tick - shrink)

        # If the leader fell, promote a survivor.
        if accused == ya.disguised_as:
            ya.disguised_as = ya.tendrils[0] if ya.tendrils else None

        # If no tendrils remain, the whole imposter is banished.
        if not ya.tendrils:
            for a in world.agents.values():
                if getattr(a, "kind", None) == AgentKind.CHARACTER:
                    cur = getattr(a, "sanity", None)
                    if cur is not None:
                        try:
                            a.sanity = min(1.0, float(cur) + 0.05)
                        except Exception:
                            pass
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="imposter_banished",
                    subject=accused,
                    detail="The last tendril fell — the village named him true",
                    severity="info",
                )
            )
            _end_appearance(world, "banished")
        return

    # Guilty but they got someone outside the hydra -> kill the innocent + fear spike.
    if accused is not None and accused in world.agents:
        innocent = world.agents[accused]
        try:
            innocent.status = Status.DEAD
        except Exception:
            pass
        for a in world.agents.values():
            if getattr(a, "kind", None) == AgentKind.CHARACTER:
                cur = getattr(a, "fear", None)
                if cur is not None:
                    try:
                        a.fear = min(1.0, float(cur) + 0.15)
                    except Exception:
                        pass
    world.emit(
        Event(
            tick=world.tick_count,
            type="imposter_vote",
            subject=accused or "unknown",
            detail="wrong accusation — the real one walks on",
            severity="warn",
        )
    )
    # Yellow Man stays; deadline keeps ticking.


# ---------------------------------------------------------------------------
# Wipe handling
# ---------------------------------------------------------------------------


def _trigger_wipe(world: World) -> None:
    world.emit(
        Event(
            tick=world.tick_count,
            type="village_wipe",
            subject="world",
            detail=f"Deadline reached — cycle {world.cycle_number} ends",
            severity="crit",
        )
    )
    world.pending_reset = True
    # Agent A's reset_world() will increment village_wipes for the next cycle,
    # but the counter metric should reflect the wipe NOW so dashboards line up.
    if world.telemetry is not None:
        world.telemetry.counter_inc(Metric.VILLAGE_WIPES_TOTAL, 1.0)
    # Strip the march marker if any, so the reset doesn't carry it forward.
    world.supernaturals[:] = [
        s for s in world.supernaturals
        if getattr(s, "id", None) != "yellow_man_march"
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _maybe_force_box_drop(world: World) -> None:
    """v4: tiny NIGHT-only chance to gift the village a Music Box.

    Active in DORMANT and IMPOSTER modes. The 0.5% per-tick roll gives roughly
    one drop per sim-day at NIGHT. No-op if a box already exists.
    """
    if world.time.phase != Phase.NIGHT:
        return
    if world.rng.random() >= 0.005:
        return
    _music_box.force_drop(world, None)


def tick_yellow(world: World) -> None:
    """Engine hook — call once per tick, AFTER agents have ticked."""
    ya = world.yellow_active

    # Always: dormant-time taint + scheduling.
    if ya.mode == YellowMode.DORMANT:
        _maybe_taint_npcs(world)
        _maybe_force_box_drop(world)
        # Lazily initialise the schedule the very first time we run.
        if _SCHED.next_appearance_tick == 0:
            _schedule_next_appearance(world)
        elif world.tick_count >= _SCHED.next_appearance_tick:
            _start_appearance(world)
    else:
        # Active modes consume any votes BEFORE checking the deadline so
        # a banishment on the deadline tick still saves the village.
        _consume_meeting_outcomes(world)

        # If a vote ended the appearance, ya.mode is now DORMANT and we drop out.
        if ya.mode == YellowMode.VISIBLE_MARCH:
            _tick_visible_march(world)
        elif ya.mode == YellowMode.IMPOSTER:
            _tick_imposter(world)
            # v4: in IMPOSTER mode the Yellow Man can also nudge a box drop.
            _maybe_force_box_drop(world)

        # Deadline check.
        if ya.mode != YellowMode.DORMANT and world.tick_count >= ya.deadline_tick:
            _trigger_wipe(world)
            # Don't call _end_appearance — let A's reset_world wipe state.

    # Gauge update every tick.
    if world.telemetry is not None:
        world.telemetry.gauge_set(
            Metric.YELLOW_ACTIVE,
            0.0 if ya.mode == YellowMode.DORMANT else 1.0,
            {"mode": ya.mode.value},
        )
        # v2 hydra count — 0 when not in IMPOSTER mode.
        world.telemetry.gauge_set(
            Metric.YELLOW_TENDRILS,
            float(len(ya.tendrils)),
        )


def reset_yellow_scheduling(world: World) -> None:
    """Called by ``population.clear_npcs`` / reset hook to wipe local schedule
    state so a fresh cycle starts cleanly. Safe to call standalone."""
    _SCHED.next_appearance_tick = 0
    _SCHED.last_taint_day = -1
    _SCHED.seen_outcome_count = 0
