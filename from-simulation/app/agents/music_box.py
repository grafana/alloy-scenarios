"""
The Music Box Monster — v4 horror set-piece.

A four-phase tragedy keyed to the Rhyme:

    "They touch, they break, they steal.
     No one here is free.
     Here they come, they come for three,
     unless you stop the melody."

Phase machine (stored on ``world.music_box_phase``):

    DORMANT   No box on the map. Periodically spawn one at NIGHT; pickup
              detection is also live during DORMANT once a box exists.
    TOUCH     A villager is carrying the box. Box drains sanity, slowly
              corrupts the house they enter, and worms start hopping to
              creatures at night. Compulsion makes most carriers unable
              to drop it.
    BREAK     One villager dies in their sleep within 200 px of the box.
    STEAL     Three villagers go catatonic (``Status.STOLEN``) and a swarm
              of cicada markers appears around them.
    TERMINAL  All stolen villagers die. Phase resets to DORMANT, the rhyme
              survives in the journal.

Destruction: a carrier reaching ``RUINS_XY`` within ``music_box_destroy_radius``
ends the lifecycle, restores stolen villagers, and clears the worms.

Worms-passing (S2 trick): a worm-infected character within 30 px of a
creature at NIGHT has a 20% chance to "give" the worm to the creature,
killing it. This is an alternative way to break the curse.

Engine hook: ``tick_music_box(world)`` is called by ``simulation._do_tick``
between ``tick_population`` and ``tick_yellow``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from contracts import (
    Agent,
    AgentKind,
    Event,
    FARAWAY_TREES,
    MarkerClass,
    Phase,
    RUINS_XY,
    State,
    Status,
    World,
    YELLOW_MARCH_PATH,
)
from agents.base import distance, nearest

import legacy


# Phase encoding used by simulation._emit_metrics gauge.
PHASE_NUM = {
    "DORMANT": 0,
    "TOUCH": 1,
    "BREAK": 2,
    "STEAL": 3,
    "TERMINAL": 4,
}


# ---------------------------------------------------------------------------
# Markers — MusicBox + transient Cicada swarm sprites
# ---------------------------------------------------------------------------


class MusicBox(Agent):
    """The lone Music Box marker. Lives in ``world.supernaturals``.

    The engine hook ``tick_music_box`` is what actually moves the box, drains
    sanity, escalates phases, etc. The instance ``tick`` is a no-op so we can
    sit in the supernaturals list without being double-stepped.
    """

    def __init__(self, sid: str, x: float, y: float, spawned_at_tick: int) -> None:
        self.id = sid
        self.kind = AgentKind.SUPERNATURAL
        self.marker_class = MarkerClass.MUSIC_BOX
        self.x = float(x)
        self.y = float(y)
        self.spawned_at_tick = int(spawned_at_tick)
        self.last_house_id: Optional[str] = None
        # Internal: tick at which the most recent BREAK death has fired, so we
        # don't kill more than one villager per BREAK phase entry.
        self._break_fired_at_tick: int = -1

    def tick(self, world: World) -> None:  # pragma: no cover — driven externally
        return None

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["kind_detail"] = "music_box"
        base["last_house"] = self.last_house_id
        return base


class Cicada(Agent):
    """Transient swarm sprite — purely cosmetic decay marker."""

    def __init__(self, sid: str, x: float, y: float, expires_at_tick: int) -> None:
        self.id = sid
        self.kind = AgentKind.SUPERNATURAL
        self.marker_class = MarkerClass.CICADA
        self.x = float(x)
        self.y = float(y)
        self.expires_at_tick = int(expires_at_tick)
        self.alive = True

    def tick(self, world: World) -> None:
        # Drift a few pixels, expire when due.
        self.x += world.rng.uniform(-1.2, 1.2)
        self.y += world.rng.uniform(-1.2, 1.2)
        if world.tick_count >= self.expires_at_tick:
            self.alive = False

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base["kind_detail"] = "cicada"
        return base


def spawn_cicadas(
    world: World, around_xy: Tuple[float, float], count: int, ttl: int
) -> None:
    """Append ``count`` cicada markers near ``around_xy`` for ``ttl`` ticks."""
    cx, cy = around_xy
    expires = world.tick_count + max(1, ttl)
    for _ in range(max(0, int(count))):
        sid = f"cicada_{world.tick_count}_{world.rng.randint(0, 10_000_000)}"
        x = cx + world.rng.uniform(-40.0, 40.0)
        y = cy + world.rng.uniform(-40.0, 40.0)
        world.supernaturals.append(Cicada(sid, x, y, expires))


# ---------------------------------------------------------------------------
# Module-local scheduling state — survives across phase changes, NOT wipes.
# (A v2-style reset on village_wipe could clear this; for now it self-heals
# because DORMANT spawn checks against world.tick_count are stateless.)
# ---------------------------------------------------------------------------


_LAST_SPAWN_TICK: int = -10_000_000


def _ticks_per_day(world: World) -> int:
    scale = max(0.001, float(world.config.time_scale))
    return max(60, int(1440.0 / scale))


def _find_box(world: World) -> Optional[MusicBox]:
    if world.music_box_id is None:
        return None
    for s in world.supernaturals:
        if getattr(s, "id", None) == world.music_box_id and isinstance(s, MusicBox):
            return s
    return None


# ---------------------------------------------------------------------------
# DORMANT — spawning + pickup detection
# ---------------------------------------------------------------------------


def _pick_spawn_xy(world: World) -> Tuple[float, float]:
    """50% near a tree, 30% near a dwelling door, 20% on a road waypoint."""
    rng = world.rng
    roll = rng.random()
    if roll < 0.5 and FARAWAY_TREES:
        tx, ty = rng.choice(FARAWAY_TREES)
        return tx + rng.uniform(-25.0, 25.0), ty + rng.uniform(-25.0, 25.0)
    if roll < 0.8 and world.buildings:
        dwellings = [
            b for b in world.buildings.values()
            if b.role_tag in ("house", "matthews", "colony", "diner", "bar")
        ]
        if not dwellings:
            dwellings = list(world.buildings.values())
        b = rng.choice(dwellings)
        # Drop just outside the door.
        return b.x + rng.uniform(-15.0, 15.0), b.y + rng.uniform(20.0, 40.0)
    # Fallback / 20% — a road waypoint.
    if YELLOW_MARCH_PATH:
        wx, wy = rng.choice(YELLOW_MARCH_PATH)
        return wx + rng.uniform(-10.0, 10.0), wy + rng.uniform(-10.0, 10.0)
    return 400.0 + rng.uniform(-40.0, 40.0), 480.0 + rng.uniform(-40.0, 40.0)


def _spawn_box(world: World, xy: Optional[Tuple[float, float]] = None) -> MusicBox:
    global _LAST_SPAWN_TICK
    if xy is None:
        x, y = _pick_spawn_xy(world)
    else:
        x, y = xy
    sid = f"music_box_{world.tick_count}_{world.rng.randint(0, 10_000_000)}"
    box = MusicBox(sid, x, y, world.tick_count)
    world.supernaturals.append(box)
    world.music_box_id = sid
    _LAST_SPAWN_TICK = world.tick_count
    world.emit(
        Event(
            tick=world.tick_count,
            type="music_box_appeared",
            subject=sid,
            detail=f"x={round(x,1)} y={round(y,1)}",
            severity="warn",
        )
    )
    return box


def _maybe_spawn(world: World) -> None:
    """DORMANT-phase: drop a box at NIGHT if the cadence has elapsed."""
    if _find_box(world) is not None:
        return
    if world.time.phase != Phase.NIGHT:
        return
    interval = max(1, world.config.music_box_interval_days) * _ticks_per_day(world)
    if world.tick_count < _LAST_SPAWN_TICK + interval:
        return
    _spawn_box(world)


def force_drop(
    world: World, location: Optional[Tuple[float, float]] = None
) -> Optional[MusicBox]:
    """Force-spawn a Music Box NOW regardless of cadence.

    Used by Yellow Man (or future LLM/admin hooks) to trigger the lifecycle
    out-of-band. No-op if a box already exists. Returns the new box, or None.
    """
    if _find_box(world) is not None:
        return None
    return _spawn_box(world, location)


def _curiosity_score(agent: Any) -> float:
    """High score = more likely to pick up the box.

    Uses ``personality`` dict if present (Character), else attribute fallbacks.
    Defaults: social=0.4, sanity=100, paranoid=0.5. Sanity is clamped 0..100.
    """
    pers = getattr(agent, "personality", None)
    if isinstance(pers, dict):
        social = float(pers.get("social", 0.4))
        paranoid = float(pers.get("paranoid", 0.5))
    else:
        social = float(getattr(agent, "social", 0.4))
        paranoid = float(getattr(agent, "paranoid", 0.5))
    sanity = float(getattr(agent, "sanity", 100.0))
    sanity = max(0.0, min(100.0, sanity)) / 100.0
    return social * 0.7 + (1.0 - sanity) * 0.3 - paranoid * 0.4


def _pickup_detection(world: World, box: MusicBox) -> bool:
    """Check every agent within curiosity radius. Returns True if picked up."""
    if world.music_box_carrier is not None:
        return False
    cfg = world.config
    rng = world.rng
    candidates: List[Any] = []
    for a in world.agents.values():
        if getattr(a, "kind", None) not in (AgentKind.CHARACTER, AgentKind.NPC, AgentKind.OUTSIDER):
            continue
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if distance(a, box) <= cfg.music_box_curiosity_radius:
            candidates.append(a)
    if not candidates:
        return False
    # Iterate in random order so position-in-dict bias doesn't dominate.
    rng.shuffle(candidates)
    for a in candidates:
        score = _curiosity_score(a)
        if score > rng.random():
            _begin_carry(world, box, a)
            return True
    return False


def _begin_carry(world: World, box: MusicBox, agent: Any) -> None:
    """Transition: agent picks up the box; phase DORMANT -> TOUCH."""
    cfg = world.config
    try:
        agent.state = State.CARRYING_BOX
    except Exception:
        pass
    world.music_box_carrier = getattr(agent, "id", None)
    world.worms_infected.add(getattr(agent, "id", ""))
    world.music_box_phase = "TOUCH"
    world.music_box_phase_until_tick = world.tick_count + cfg.music_box_phase_ticks
    line = "They touch."
    if line not in world.rhyme_heard:
        world.rhyme_heard.append(line)
    world.emit(
        Event(
            tick=world.tick_count,
            type="music_box_picked_up",
            subject=getattr(agent, "id", "?"),
            detail=f"box={box.id}",
            severity="warn",
        )
    )
    world.emit(
        Event(
            tick=world.tick_count,
            type="rhyme_line",
            subject="world",
            detail=line,
            severity="info",
        )
    )


# ---------------------------------------------------------------------------
# TOUCH — carrier mechanics
# ---------------------------------------------------------------------------


def _compulsion_resists(agent: Any) -> bool:
    """Return True if the agent's resolve is strong enough to *drop* the box."""
    pers = getattr(agent, "personality", None)
    if isinstance(pers, dict):
        brave = float(pers.get("brave", 0.4))
        devout = float(pers.get("devout", 0.3))
        paranoid = float(pers.get("paranoid", 0.5))
    else:
        brave = float(getattr(agent, "brave", 0.4))
        devout = float(getattr(agent, "devout", 0.3))
        paranoid = float(getattr(agent, "paranoid", 0.5))
    sanity = float(getattr(agent, "sanity", 100.0))
    sanity = max(0.0, min(100.0, sanity)) / 100.0
    # Threshold: harder to break out the more frayed they are.
    return (brave + devout) > 1.2 + paranoid + (1.0 - sanity) * 0.5


def _drop_box(world: World, box: MusicBox, agent: Optional[Any], reason: str) -> None:
    if agent is not None:
        try:
            if agent.state == State.CARRYING_BOX:
                agent.state = State.WANDERING
        except Exception:
            pass
    world.music_box_carrier = None
    world.emit(
        Event(
            tick=world.tick_count,
            type="music_box_dropped",
            subject=getattr(agent, "id", "?") if agent is not None else "?",
            detail=reason,
            severity="info",
        )
    )


def _nearest_building(world: World, x: float, y: float, radius: float):
    best = None
    best_d = radius
    for b in world.buildings.values():
        d = math.hypot(b.x - x, b.y - y)
        if d <= best_d:
            best_d = d
            best = b
    return best


def _apply_in_house(world: World, box: MusicBox, carrier: Any) -> None:
    """Carrier inside a building: corrupt talisman, drain occupants, scare bystanders."""
    b = _nearest_building(world, box.x, box.y, 30.0)
    if b is None:
        box.last_house_id = None
        return
    box.last_house_id = b.id
    cfg = world.config
    # Talisman failure roll — only meaningful for protected houses.
    if b.has_talisman and world.rng.random() < cfg.music_box_talisman_fail_prob:
        new_until = world.tick_count + max(50, cfg.house_cooling_off_ticks // 16)
        if new_until > b.cooling_off_until_tick:
            b.cooling_off_until_tick = new_until
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="music_box_in_house",
                    subject=b.id,
                    detail=f"talisman flickers, box={box.id}",
                    severity="warn",
                )
            )
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="house_cooling_off",
                    subject=b.id,
                    detail=f"until_tick={new_until}",
                    severity="warn",
                )
            )
    # Sanity drain on occupants.
    for occ_id in list(b.occupants):
        occ = world.agents.get(occ_id)
        if occ is None:
            continue
        s = getattr(occ, "sanity", None)
        if s is None:
            continue
        try:
            occ.sanity = max(0.0, float(s) - 0.5)
        except Exception:
            pass
    # +fear on bystanders within 60 px.
    for a in world.agents.values():
        if a is carrier:
            continue
        if distance(a, box) > 60.0:
            continue
        f = getattr(a, "fear", None)
        if f is None:
            continue
        try:
            a.fear = min(100.0, float(f) + 2.0)
        except Exception:
            pass


def _tick_touch(world: World, box: MusicBox) -> None:
    cfg = world.config
    carrier = world.agents.get(world.music_box_carrier) if world.music_box_carrier else None

    # Carrier missing / dead -> drop and stay in TOUCH so someone else can pick up.
    if carrier is None or getattr(carrier, "status", Status.ACTIVE) != Status.ACTIVE:
        if world.music_box_carrier is not None:
            _drop_box(world, box, carrier, "carrier_lost")
        # Allow re-pickup this same tick.
        _pickup_detection(world, box)
        return

    # Mirror box to carrier.
    box.x = float(carrier.x)
    box.y = float(carrier.y)

    # Compulsion drop?
    if _compulsion_resists(carrier):
        _drop_box(world, box, carrier, "broke_compulsion")
        return

    # Worm drain.
    s = getattr(carrier, "sanity", None)
    if s is not None:
        try:
            carrier.sanity = max(0.0, float(s) - cfg.music_box_sanity_drain)
        except Exception:
            pass

    # House mechanics.
    _apply_in_house(world, box, carrier)

    # Phase escalation.
    if world.tick_count >= world.music_box_phase_until_tick:
        _advance_phase(world, box, to_phase="BREAK")


# ---------------------------------------------------------------------------
# Phase transitions: BREAK / STEAL / TERMINAL
# ---------------------------------------------------------------------------


def _advance_phase(world: World, box: MusicBox, to_phase: str) -> None:
    cfg = world.config
    world.music_box_phase = to_phase
    world.music_box_phase_until_tick = world.tick_count + cfg.music_box_phase_ticks
    if to_phase == "BREAK":
        line = "They break."
    elif to_phase == "STEAL":
        line = "Here they come, they come for three,"
    elif to_phase == "TERMINAL":
        line = "unless you stop the melody."
    else:
        line = ""
    if line and line not in world.rhyme_heard:
        world.rhyme_heard.append(line)
        world.emit(
            Event(
                tick=world.tick_count,
                type="rhyme_line",
                subject="world",
                detail=line,
                severity="warn" if to_phase in ("BREAK", "STEAL") else "crit",
            )
        )
    # STEAL has on-entry side effects.
    if to_phase == "STEAL":
        _do_steal_entry(world, box)


def _nearby_villagers(world: World, box: MusicBox, radius: float) -> List[Any]:
    out = []
    for a in world.agents.values():
        if getattr(a, "kind", None) not in (AgentKind.CHARACTER, AgentKind.NPC, AgentKind.OUTSIDER):
            continue
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if a.id == world.music_box_carrier:
            continue
        if distance(a, box) <= radius:
            out.append(a)
    return out


def _tick_break(world: World, box: MusicBox) -> None:
    """One nearby villager dies in their sleep. Fires once per BREAK entry."""
    # Mirror box to carrier if still held.
    carrier = world.agents.get(world.music_box_carrier) if world.music_box_carrier else None
    if carrier is not None:
        box.x = float(carrier.x)
        box.y = float(carrier.y)

    if box._break_fired_at_tick == -1 or box._break_fired_at_tick < (
        world.music_box_phase_until_tick - world.config.music_box_phase_ticks
    ):
        # Pick a victim. Prefer NPCs, then fall back to characters.
        nearby = _nearby_villagers(world, box, 200.0)
        npcs = [a for a in nearby if getattr(a, "kind", None) == AgentKind.NPC]
        pool = npcs if npcs else [a for a in nearby if getattr(a, "kind", None) == AgentKind.CHARACTER]
        if pool:
            victim = world.rng.choice(pool)
            try:
                victim.status = Status.DEAD
            except Exception:
                pass
            try:
                setattr(victim, "death_cause", "music_box_break")
            except Exception:
                pass
            box._break_fired_at_tick = world.tick_count
            name = getattr(victim, "name", None) or getattr(victim, "id", "?")
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="break_death",
                    subject=getattr(victim, "id", "?"),
                    detail=f"{name} did not wake",
                    severity="crit",
                )
            )
            try:
                legacy.record(world, "break_death", name=name)
            except Exception:
                pass
        else:
            # No victims in range — flag the fire so we don't retry every tick.
            box._break_fired_at_tick = world.tick_count

    if world.tick_count >= world.music_box_phase_until_tick:
        _advance_phase(world, box, to_phase="STEAL")


def _do_steal_entry(world: World, box: MusicBox) -> None:
    """Pick three villagers, mark STOLEN, spawn cicada swarm around each."""
    rng = world.rng
    nearby = _nearby_villagers(world, box, 220.0)
    if not nearby:
        return
    rng.shuffle(nearby)
    victims = nearby[:3]
    for v in victims:
        try:
            v.status = Status.STOLEN
        except Exception:
            pass
        vid = getattr(v, "id", "?")
        world.emit(
            Event(
                tick=world.tick_count,
                type="steal_event",
                subject=vid,
                detail=f"taken by the music box",
                severity="crit",
            )
        )
        n_cicadas = rng.randint(5, 8)
        spawn_cicadas(world, (float(v.x), float(v.y)), n_cicadas, ttl=world.config.music_box_phase_ticks * 2)


def _tick_steal(world: World, box: MusicBox) -> None:
    # Keep box visually with the carrier if still held.
    carrier = world.agents.get(world.music_box_carrier) if world.music_box_carrier else None
    if carrier is not None:
        box.x = float(carrier.x)
        box.y = float(carrier.y)
    if world.tick_count >= world.music_box_phase_until_tick:
        _advance_phase(world, box, to_phase="TERMINAL")


def _tick_terminal(world: World, box: MusicBox) -> None:
    """All STOLEN villagers die; phase resets to DORMANT."""
    stolen_ids = []
    for a in list(world.agents.values()):
        if getattr(a, "status", None) == Status.STOLEN:
            try:
                a.status = Status.DEAD
            except Exception:
                pass
            try:
                setattr(a, "death_cause", "music_box_terminal")
            except Exception:
                pass
            stolen_ids.append(getattr(a, "id", "?"))
    world.emit(
        Event(
            tick=world.tick_count,
            type="break_death",
            subject="world",
            detail=f"terminal: {len(stolen_ids)} dead",
            severity="crit",
        )
    )
    # Summary event (using an existing canonical type — village_terror isn't
    # registered yet, fall back to journal_entry so we don't get an "unknown"
    # telemetry tag).
    world.emit(
        Event(
            tick=world.tick_count,
            type="journal_entry",
            subject="world",
            detail="The melody ended. Three did not return.",
            severity="crit",
        )
    )
    _reset_to_dormant(world, box, preserve_rhyme=True)


# ---------------------------------------------------------------------------
# Destruction at the ruins
# ---------------------------------------------------------------------------


def _check_destruction(world: World, box: MusicBox) -> bool:
    """If the carrier is at the ruins, destroy the box. Returns True if destroyed."""
    if world.music_box_carrier is None:
        return False
    carrier = world.agents.get(world.music_box_carrier)
    if carrier is None:
        return False
    cfg = world.config
    rx, ry = RUINS_XY
    if math.hypot(float(carrier.x) - rx, float(carrier.y) - ry) > cfg.music_box_destroy_radius:
        return False

    carrier_name = getattr(carrier, "name", None) or getattr(carrier, "id", "?")

    # Restore STOLEN -> ACTIVE.
    for a in world.agents.values():
        if getattr(a, "status", None) == Status.STOLEN:
            try:
                a.status = Status.ACTIVE
            except Exception:
                pass

    # Remove worm from carrier.
    cid = getattr(carrier, "id", None)
    if cid in world.worms_infected:
        world.worms_infected.discard(cid)

    # +5 sanity to everyone.
    for a in world.agents.values():
        s = getattr(a, "sanity", None)
        if s is None:
            continue
        try:
            a.sanity = min(100.0, float(s) + 5.0)
        except Exception:
            pass

    _reset_to_dormant(world, box, preserve_rhyme=True)

    world.emit(
        Event(
            tick=world.tick_count,
            type="music_box_destroyed",
            subject=cid or "?",
            detail=f"shattered at the ruins by {carrier_name}",
            severity="info",
        )
    )
    try:
        legacy.record(world, "music_box_destroyed", carrier=carrier_name)
    except Exception:
        pass
    return True


def _reset_to_dormant(world: World, box: MusicBox, preserve_rhyme: bool) -> None:
    """Common cleanup for TERMINAL and destruction paths."""
    # Strip the box + all cicadas from supernaturals.
    box_id = box.id
    world.supernaturals[:] = [
        s for s in world.supernaturals
        if not (
            getattr(s, "id", None) == box_id
            or getattr(s, "marker_class", None) == MarkerClass.CICADA
        )
    ]
    # Reset carrier state if they're still CARRYING_BOX.
    carrier = world.agents.get(world.music_box_carrier) if world.music_box_carrier else None
    if carrier is not None:
        try:
            if carrier.state == State.CARRYING_BOX:
                carrier.state = State.WANDERING
        except Exception:
            pass
    # Clear worm flags — destruction cures everyone. (TERMINAL also clears so a
    # fresh DORMANT doesn't carry the infection forever.)
    world.worms_infected.clear()
    world.music_box_phase = "DORMANT"
    world.music_box_phase_until_tick = 0
    world.music_box_id = None
    world.music_box_carrier = None
    if not preserve_rhyme:
        world.rhyme_heard.clear()


# ---------------------------------------------------------------------------
# Worms passing — alt cure via creature contact
# ---------------------------------------------------------------------------


def _tick_worms_passing(world: World) -> None:
    """At NIGHT: infected character within 30 px of a creature -> 20% kill creature, cure carrier."""
    if world.time.phase != Phase.NIGHT:
        return
    if not world.worms_infected or not world.creatures:
        return
    rng = world.rng
    # Iterate over a snapshot — we may mutate world.creatures.
    for aid in list(world.worms_infected):
        agent = world.agents.get(aid)
        if agent is None:
            continue
        # Find nearest creature within 30 px.
        target = None
        for c in world.creatures:
            if distance(agent, c) <= 30.0:
                target = c
                break
        if target is None:
            continue
        if rng.random() < 0.20:
            try:
                world.creatures.remove(target)
            except ValueError:
                pass
            world.worms_infected.discard(aid)
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="worms_passed",
                    subject=aid,
                    detail=f"creature={getattr(target, 'id', '?')}",
                    severity="info",
                )
            )


# ---------------------------------------------------------------------------
# Public engine hook
# ---------------------------------------------------------------------------


def tick_music_box(world: World) -> None:
    """Engine hook — call once per tick, BEFORE tick_yellow."""
    phase = world.music_box_phase

    if phase == "DORMANT":
        _maybe_spawn(world)
        box = _find_box(world)
        if box is not None:
            _pickup_detection(world, box)
        # Worms-passing only really matters once there's been a carrier, but
        # safe to call unconditionally — it's a no-op when worms_infected empty.
        _tick_worms_passing(world)
        return

    # Active-phase branches need the box; if it has vanished, reset.
    box = _find_box(world)
    if box is None:
        # Defensive: rebuild a dormant world if the box disappeared.
        world.music_box_phase = "DORMANT"
        world.music_box_phase_until_tick = 0
        world.music_box_id = None
        world.music_box_carrier = None
        return

    # Destruction is checked every active tick.
    if _check_destruction(world, box):
        return

    if phase == "TOUCH":
        _tick_touch(world, box)
    elif phase == "BREAK":
        _tick_break(world, box)
    elif phase == "STEAL":
        _tick_steal(world, box)
    elif phase == "TERMINAL":
        _tick_terminal(world, box)

    # Worms passing runs alongside the active phase too.
    _tick_worms_passing(world)
