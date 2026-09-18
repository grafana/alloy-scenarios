"""
v8 — Cult faction.

Story: when an NPC loses too many friends or family to creatures, paranormal
breaks, or starvation, they crack the other way — they conclude that the
village has invited the dark and start working *with* it. Cultists are still
NPCs (same kind, same dot), but their ``cult_state`` flag flips to
``CONVERTED`` and they:

  * Refuse to shelter at night — they roam the village instead.
  * Pulse fear into nearby townfolk, accelerating breaks.
  * Recruit other low-sanity NPCs in the same surname / friend graph.
  * If their numbers cross a critical mass, they "perform the sacrifice"
    at NIGHT, which forces a village wipe — the same loop reset as Yellow
    Man wins.

Counter: if survivors kill or break enough cultists, the cult is suppressed
and the village endures.

Ownership: this module is purely additive. It writes ``cult_state`` /
``cult_pressure`` on NPCs and reads/writes nothing else outside of emitting
events. It runs after agents tick so the conversion view is up-to-date.
"""

from __future__ import annotations

from typing import Dict, List

from contracts import AgentKind, Event, Phase, State, Status, World


# ---------------------------------------------------------------- tunables

# How much "cult_pressure" each kind of loss adds when it happens to a
# friend or family member of the NPC. Once cult_pressure crosses the
# CONVERT threshold the NPC turns. SUSPECTED is just a UI / dossier flag.
_PRESSURE_FAMILY_DEATH = 1.0
_PRESSURE_FAMILY_BREAK = 0.5
_PRESSURE_FRIEND_DEATH = 0.6
_PRESSURE_FRIEND_BREAK = 0.3
# Sanity-floor bias — an already-shaken NPC converts at lower thresholds.
_LOW_SANITY_MULT = 1.6
_LOW_SANITY_THRESHOLD = 35.0

_SUSPECTED_THRESHOLD = 1.0
_CONVERT_THRESHOLD = 2.0

# Cultist behaviour tunables.
_CULTIST_FEAR_RADIUS = 90.0
_CULTIST_FEAR_PER_TICK = 0.25      # added to nearby non-cultists each tick
_CULTIST_SPREAD_PROB = 0.0008      # tick-chance to recruit a vulnerable kin

# Sacrifice / endgame.
_SACRIFICE_THRESHOLD = 8           # number of CONVERTED to trigger the call
_SACRIFICE_DEADLINE_TICKS = 800    # ticks the village has to suppress them
_SACRIFICE_MIN_TICKS_BEFORE_WIPE = 600


# ---------------------------------------------------------------- helpers


def _friend_ids(world: World, npc_id: str) -> List[str]:
    """NPCs / chars whose trust score with ``npc_id`` is ≥ 0.65."""
    trust_map = getattr(world, "trust", {}) or {}
    out: List[str] = []
    seen = set()
    for (a, b), s in trust_map.items():
        if a == npc_id and b not in seen:
            try:
                if float(s) >= 0.65:
                    out.append(b)
                    seen.add(b)
            except Exception:
                pass
        elif b == npc_id and a not in seen:
            try:
                if float(s) >= 0.65:
                    out.append(a)
                    seen.add(a)
            except Exception:
                pass
    return out


def _family_ids(world: World, npc) -> List[str]:
    """Living NPCs sharing the surname (excluding the npc itself)."""
    surname = getattr(npc, "surname", None)
    if not surname:
        return []
    out = []
    for a in world.agents.values():
        if getattr(a, "kind", None) != AgentKind.NPC:
            continue
        if a.id == npc.id:
            continue
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if getattr(a, "surname", None) == surname:
            out.append(a.id)
    return out


def _is_cultist(agent) -> bool:
    return getattr(agent, "cult_state", "NONE") == "CONVERTED"


# ---------------------------------------------------------------- public


def on_loss(world: World, victim_id: str, loss_kind: str) -> None:
    """Bump cult_pressure on every NPC who is family / friend of the victim.

    ``loss_kind`` is either ``"death"`` (creature kill, npc_death, char_death)
    or ``"break"`` (paranormal_break / sanity_break). Called from event
    consumers — kept idempotent per (victim, kind) by tagging the victim with
    ``_cult_loss_seen`` so the same death doesn't double-bump.
    """
    victim = world.agents.get(victim_id) if hasattr(world, "agents") else None
    seen_key = f"_cult_loss_seen_{loss_kind}"
    if victim is not None:
        if getattr(victim, seen_key, False):
            return
        setattr(victim, seen_key, True)

    # Friends of the victim across the whole agents pool.
    friends = set(_friend_ids(world, victim_id))
    # Family of the victim (NPCs with the same surname).
    family: List[str] = []
    if victim is not None:
        surname = getattr(victim, "surname", None)
        if surname:
            for a in world.agents.values():
                if getattr(a, "surname", None) == surname and a.id != victim_id:
                    family.append(a.id)

    for kin_id in set(family) | friends:
        kin = world.agents.get(kin_id)
        if kin is None:
            continue
        if getattr(kin, "kind", None) != AgentKind.NPC:
            continue
        if getattr(kin, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if _is_cultist(kin):
            continue

        if kin_id in family:
            delta = (
                _PRESSURE_FAMILY_DEATH if loss_kind == "death"
                else _PRESSURE_FAMILY_BREAK
            )
        else:
            delta = (
                _PRESSURE_FRIEND_DEATH if loss_kind == "death"
                else _PRESSURE_FRIEND_BREAK
            )

        if float(getattr(kin, "sanity", 100.0)) < _LOW_SANITY_THRESHOLD:
            delta *= _LOW_SANITY_MULT

        kin.cult_pressure = float(getattr(kin, "cult_pressure", 0.0)) + delta

        prev_state = getattr(kin, "cult_state", "NONE")
        if kin.cult_pressure >= _CONVERT_THRESHOLD and prev_state != "CONVERTED":
            kin.cult_state = "CONVERTED"
            kin.cult_converted_at_tick = world.tick_count
            display = (
                f"{kin.name} {kin.surname}".strip() if getattr(kin, "surname", None)
                else getattr(kin, "name", kin.id)
            )
            world.emit(Event(
                tick=world.tick_count,
                type="cult_joined",
                subject=kin.id,
                detail=f"{display} joined the cult — grief turned outward",
                severity="crit",
            ))
        elif kin.cult_pressure >= _SUSPECTED_THRESHOLD and prev_state == "NONE":
            kin.cult_state = "SUSPECTED"


def _broadcast_fear(world: World, cultist) -> None:
    """A cultist pulses fear into nearby townfolk + chars."""
    cx, cy = cultist.x, cultist.y
    r2 = _CULTIST_FEAR_RADIUS * _CULTIST_FEAR_RADIUS
    for a in world.agents.values():
        if a.id == cultist.id:
            continue
        if _is_cultist(a):
            continue
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        dx = a.x - cx
        dy = a.y - cy
        if dx * dx + dy * dy <= r2:
            cur = float(getattr(a, "fear", 0.0))
            setattr(a, "fear", min(100.0, cur + _CULTIST_FEAR_PER_TICK))


def _maybe_recruit(world: World, cultist) -> None:
    """A cultist tries to convert one shaky kin per tick at a low chance."""
    if world.rng.random() >= _CULTIST_SPREAD_PROB:
        return
    candidates = []
    surname = getattr(cultist, "surname", None)
    for a in world.agents.values():
        if a.id == cultist.id:
            continue
        if getattr(a, "kind", None) != AgentKind.NPC:
            continue
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if _is_cultist(a):
            continue
        # Family or low-sanity friend.
        same_family = surname and getattr(a, "surname", None) == surname
        sanity = float(getattr(a, "sanity", 100.0))
        if same_family or sanity < _LOW_SANITY_THRESHOLD:
            candidates.append(a)
    if not candidates:
        return
    target = world.rng.choice(candidates)
    target.cult_pressure = float(getattr(target, "cult_pressure", 0.0)) \
        + _PRESSURE_FAMILY_DEATH
    prev = getattr(target, "cult_state", "NONE")
    if target.cult_pressure >= _CONVERT_THRESHOLD and prev != "CONVERTED":
        target.cult_state = "CONVERTED"
        target.cult_converted_at_tick = world.tick_count
        display = (
            f"{target.name} {target.surname}".strip()
            if getattr(target, "surname", None)
            else getattr(target, "name", target.id)
        )
        world.emit(Event(
            tick=world.tick_count,
            type="cult_recruited",
            subject=target.id,
            detail=f"{display} was whispered into the cult",
            severity="crit",
        ))


def _check_sacrifice(world: World) -> None:
    """If cult reaches critical mass, set a sacrifice deadline.

    The sacrifice is announced via ``cult_sacrifice_called`` and stored on
    ``world._cult_sacrifice_deadline``. If the deadline ticks past while
    the cult still has critical mass at NIGHT, a ``village_wipe`` is fired
    and Agent A's reset path bulldozes the cycle.
    """
    cult_count = sum(1 for a in world.agents.values() if _is_cultist(a))
    deadline = int(getattr(world, "_cult_sacrifice_deadline", 0))

    if cult_count >= _SACRIFICE_THRESHOLD and deadline == 0:
        world._cult_sacrifice_deadline = world.tick_count + _SACRIFICE_DEADLINE_TICKS
        world.emit(Event(
            tick=world.tick_count,
            type="cult_sacrifice_called",
            subject="world",
            detail=(
                f"the cult has {cult_count} hands — they speak of feeding the dark"
            ),
            severity="crit",
        ))
        return

    if deadline and cult_count < _SACRIFICE_THRESHOLD:
        # The town beat them back below critical mass — call it off.
        world._cult_sacrifice_deadline = 0
        world.emit(Event(
            tick=world.tick_count,
            type="cult_suppressed",
            subject="world",
            detail="the cult fell apart — the sacrifice cannot happen",
            severity="info",
        ))
        return

    # Deadline reached + still critical mass + it's NIGHT → end the cycle.
    if (
        deadline
        and world.tick_count >= deadline
        and world.time.phase == Phase.NIGHT
        and cult_count >= _SACRIFICE_THRESHOLD
        and world.tick_count >= _SACRIFICE_MIN_TICKS_BEFORE_WIPE
    ):
        world._cult_sacrifice_deadline = 0
        world.emit(Event(
            tick=world.tick_count,
            type="cult_sacrifice",
            subject="world",
            detail="the cult dragged the village to the dark — the cycle resets",
            severity="crit",
        ))
        world.pending_reset = True


def tick(world: World) -> None:
    """Engine hook — call once per tick AFTER agents have ticked.

    Walks the cultist roster, broadcasts fear, occasionally recruits,
    forces wandering at night, and checks the sacrifice condition.
    """
    if not hasattr(world, "agents"):
        return

    # Phase 1 — every cultist does their thing.
    cultists = [a for a in world.agents.values() if _is_cultist(a)]
    if cultists:
        for c in cultists:
            # Force their state to WANDERING at night so they roam instead
            # of sheltering at home (which is what loyalty would do).
            if world.time.phase in (Phase.DUSK, Phase.NIGHT):
                cur = getattr(c, "state", None)
                if cur in (State.SHELTERING, State.SLEEPING):
                    setattr(c, "state", State.WANDERING)
            _broadcast_fear(world, c)
            _maybe_recruit(world, c)

    # Phase 2 — sacrifice / endgame check.
    _check_sacrifice(world)


def consume_events_for_pressure(world: World, events) -> None:
    """Scan a batch of events for deaths + breaks and feed them to ``on_loss``.

    Hooked from simulation.py per tick on the world's event buffer.
    """
    if not events:
        return
    for ev in events:
        if not ev:
            continue
        et = getattr(ev, "type", None) or (ev.get("type") if isinstance(ev, dict) else None)
        subj = getattr(ev, "subject", None) or (ev.get("subject") if isinstance(ev, dict) else None)
        if not subj or not et:
            continue
        if et in ("npc_death", "char_death", "incapacitated"):
            on_loss(world, subj, "death")
        elif et in ("paranormal_break", "npc_sanity_break"):
            on_loss(world, subj, "break")
