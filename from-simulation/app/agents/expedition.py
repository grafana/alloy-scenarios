"""
Food expeditions into the forest.

Agent B owns this module. Driven by ``characters.tick_societies(world)``.

Lifecycle:

* When ``world.expedition_authorised`` is set (only the social loop sets it,
  from a successful ``food_supply`` meeting outcome), pick a leader from the
  brave/leader-personality pool (Boyd, Donna, or Jim by default) and recruit
  2-4 brave characters present in town.
* Walk the party to a random interior forest point, well away from the spawn
  ring.
* Mill ~80 ticks. If the mill extends past DUSK, fear ramps up sharply and
  there's a chance one party member dies (their ``status`` is set to ``DEAD``
  — ``resurrection.py`` picks them up next tick).
* Return to town, deposit food, restore states, emit ``expedition_returned``.

Events emitted: ``expedition_called`` (when authorised), ``expedition_departed``,
``expedition_returned``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from contracts import (
    Event,
    Phase,
    Role,
    RUINS_XY,
    State,
    Status,
    World,
)

from agents.characters import Character


EXPEDITION_MILL_TICKS = 80
FOREST_TARGET_RING = (0.85, 0.95)  # fraction of map dimensions for interior point
FOOD_REWARD = 60.0
DEPART_SPEED = 3.5

# v4: music-box destruction run.
MUSIC_BOX_RENDEZVOUS_RADIUS = 30.0   # leader-to-carrier adjacency threshold
MUSIC_BOX_DESTROY_RADIUS = 40.0      # close enough to RUINS for A's tick to fire


@dataclass
class _Expedition:
    leader_id: str
    member_ids: List[str] = field(default_factory=list)
    departed_tick: int = 0
    target: Tuple[float, float] = (0.0, 0.0)
    home: Tuple[float, float] = (500.0, 350.0)
    phase: str = "departing"  # departing | milling | returning | done | rendezvous | ruins
    mill_start_tick: int = 0
    # v4 — set when this is a music-box destruction expedition.
    is_music_box: bool = False


def _get_expedition(world: World) -> Optional[_Expedition]:
    return getattr(world, "_active_expedition", None)


def _set_expedition(world: World, exp: Optional[_Expedition]) -> None:
    world._active_expedition = exp  # type: ignore[attr-defined]


def _eligible(c: Character) -> bool:
    if c.status != Status.ACTIVE:
        return False
    if c.state in (State.SLEEPING, State.HYPNOTIZED, State.IRRATIONAL,
                   State.MEETING, State.ARGUING):
        return False
    return True


def _pick_leader(world: World) -> Optional[Character]:
    candidates: List[Tuple[Character, float]] = []
    for a in world.agents.values():
        if not isinstance(a, Character):
            continue
        if a.role not in (Role.SHERIFF, Role.LEADER_COLONY, Role.ENGINEER):
            continue
        if not _eligible(a):
            continue
        weight = (
            0.5 * a.personality.get("leader", 0.3)
            + 0.5 * a.personality.get("brave", 0.4)
        )
        candidates.append((a, max(0.1, weight)))
    if not candidates:
        return None
    pool, weights = zip(*candidates)
    return world.rng.choices(pool, weights=weights, k=1)[0]


def _pick_party(world: World, leader: Character) -> List[Character]:
    pool = [
        a for a in world.agents.values()
        if isinstance(a, Character) and a.id != leader.id and _eligible(a)
    ]
    # Prefer brave folk.
    pool.sort(key=lambda c: c.personality.get("brave", 0.4), reverse=True)
    n = world.rng.randint(2, min(4, max(2, len(pool))))
    return pool[:n]


def _forest_target(world: World) -> Tuple[float, float]:
    # Map viewBox is 1000 x 700. Interior forest sits between the building cluster
    # and the spawn ring. Pick somewhere on a corner-ish ring.
    angle = world.rng.uniform(0, 2 * math.pi)
    rx = world.rng.uniform(FOREST_TARGET_RING[0], FOREST_TARGET_RING[1])
    cx, cy = 500.0, 350.0
    tx = cx + rx * 380.0 * math.cos(angle)
    ty = cy + rx * 270.0 * math.sin(angle)
    # Clamp inside the map margin (avoid the very edge spawn points).
    tx = max(60.0, min(940.0, tx))
    ty = max(60.0, min(640.0, ty))
    return (tx, ty)


def _walk_party(world: World, exp: _Expedition, dest: Tuple[float, float],
                speed: float) -> bool:
    """Move all members one step toward dest. Returns True when all arrived."""
    all_arrived = True
    for mid in [exp.leader_id, *exp.member_ids]:
        ch = world.agents.get(mid)
        if not isinstance(ch, Character) or ch.status not in (Status.ACTIVE,):
            continue
        dx = dest[0] - ch.x
        dy = dest[1] - ch.y
        d = math.hypot(dx, dy)
        if d <= speed:
            ch.x, ch.y = dest
        else:
            ch.x += speed * dx / d
            ch.y += speed * dy / d
            all_arrived = False
    return all_arrived


def _pin_party(world: World, exp: _Expedition) -> None:
    for mid in [exp.leader_id, *exp.member_ids]:
        ch = world.agents.get(mid)
        if isinstance(ch, Character) and ch.status == Status.ACTIVE:
            ch.state = State.EXPEDITION
            ch.state_since_tick = world.tick_count
            ch.expedition_role = "leader" if mid == exp.leader_id else "member"


def _release_party(world: World, exp: _Expedition) -> None:
    for mid in [exp.leader_id, *exp.member_ids]:
        ch = world.agents.get(mid)
        if isinstance(ch, Character) and ch.status == Status.ACTIVE:
            ch.state = State.WANDERING
            ch.state_since_tick = world.tick_count
            ch.expedition_role = None
            ch.target = None


def _pick_music_box_leader(world: World) -> Optional[Character]:
    """Prefer Boyd (SHERIFF); fall back to any worm-infected character.

    The infected carrier is a sensible second choice because they're already
    bonded to the box and will accept the trip without argument.
    """
    boyd = world.agents.get("Boyd")
    if isinstance(boyd, Character) and _eligible(boyd):
        return boyd
    # SHERIFF role fallback (in case Boyd is incapacitated/dead).
    for a in world.agents.values():
        if (isinstance(a, Character) and a.role == Role.SHERIFF
                and _eligible(a) and a.id != "Boyd"):
            return a
    # Worm-infected carrier fallback.
    worms = getattr(world, "worms_infected", set()) or set()
    carrier_id = getattr(world, "music_box_carrier", None)
    if carrier_id and carrier_id in world.agents:
        ch = world.agents[carrier_id]
        if isinstance(ch, Character) and _eligible(ch):
            return ch
    for wid in worms:
        ch = world.agents.get(wid)
        if isinstance(ch, Character) and _eligible(ch):
            return ch
    return None


def tick_expeditions(world: World) -> None:
    exp = _get_expedition(world)

    # ------------------------------------------------ kick off a new expedition
    if exp is None:
        if not world.expedition_authorised:
            return

        is_music_box = bool(getattr(world, "_expedition_is_music_box", False))

        if is_music_box:
            leader = _pick_music_box_leader(world)
            if leader is None:
                # Nobody available — drop both flags, try again later.
                world.expedition_authorised = False
                world._expedition_is_music_box = False  # type: ignore[attr-defined]
                return
            # Music-box runs are smaller: leader + 0-2 companions optional.
            party = _pick_party(world, leader)[:2]
            home = (leader.x, leader.y)
            # Initial target depends on whether a carrier exists.
            carrier_id = getattr(world, "music_box_carrier", None)
            carrier = world.agents.get(carrier_id) if carrier_id else None
            if isinstance(carrier, Character) and carrier.id != leader.id:
                target = (carrier.x, carrier.y)
                phase = "rendezvous"
            else:
                # No carrier or leader IS the carrier — head straight to ruins.
                # If no carrier at all, make the leader the carrier.
                if carrier_id is None or not isinstance(carrier, Character):
                    world.music_box_carrier = leader.id
                    try:
                        leader.state = State.CARRYING_BOX
                    except Exception:
                        pass
                target = RUINS_XY
                phase = "ruins"
            exp = _Expedition(
                leader_id=leader.id,
                member_ids=[c.id for c in party],
                departed_tick=world.tick_count,
                target=target,
                home=home,
                phase=phase,
                is_music_box=True,
            )
            _set_expedition(world, exp)
            _pin_party(world, exp)
            for mid in [leader.id, *exp.member_ids]:
                ch = world.agents.get(mid)
                if isinstance(ch, Character):
                    ch.target = target
            world.expedition_authorised = False
            world.expedition_active = True
            world.emit(Event(
                tick=world.tick_count, type="expedition_called",
                subject=leader.id,
                detail=f"destroy music box — led by {leader.name}",
                severity="warn",
            ))
            world.emit(Event(
                tick=world.tick_count, type="expedition_departed",
                subject=leader.id,
                detail=f"to the ruins at ({RUINS_XY[0]:.0f},{RUINS_XY[1]:.0f})",
                severity="warn",
            ))
            return

        leader = _pick_leader(world)
        if leader is None:
            # Authorised but nobody available — drop the flag, try again later.
            world.expedition_authorised = False
            return
        party = _pick_party(world, leader)
        if len(party) < 2:
            world.expedition_authorised = False
            return
        # Town centre as home base for the return leg.
        home = (leader.x, leader.y)
        target = _forest_target(world)
        exp = _Expedition(
            leader_id=leader.id,
            member_ids=[c.id for c in party],
            departed_tick=world.tick_count,
            target=target,
            home=home,
            phase="departing",
        )
        _set_expedition(world, exp)
        _pin_party(world, exp)
        for mid in [leader.id, *exp.member_ids]:
            ch = world.agents.get(mid)
            if isinstance(ch, Character):
                ch.target = target
        world.expedition_authorised = False
        world.expedition_active = True
        world.emit(Event(
            tick=world.tick_count, type="expedition_called",
            subject=leader.id,
            detail=f"led by {leader.name} ({len(party)} members)",
        ))
        world.emit(Event(
            tick=world.tick_count, type="expedition_departed",
            subject=leader.id,
            detail=f"heading to ({target[0]:.0f},{target[1]:.0f})",
        ))
        return

    # ------------------------------------------------ music-box destruction run
    if exp.is_music_box:
        leader = world.agents.get(exp.leader_id)
        if not isinstance(leader, Character) or leader.status != Status.ACTIVE:
            # Lost the leader mid-run — abort cleanly.
            _release_party(world, exp)
            _set_expedition(world, None)
            world.expedition_active = False
            world._expedition_is_music_box = False  # type: ignore[attr-defined]
            return

        carrier_id = getattr(world, "music_box_carrier", None)
        carrier = world.agents.get(carrier_id) if carrier_id else None

        if exp.phase == "rendezvous":
            # Leader walks to the carrier. If the carrier is gone (dropped /
            # died / vanished), the leader becomes the carrier.
            if not isinstance(carrier, Character) or carrier.status != Status.ACTIVE:
                world.music_box_carrier = leader.id
                try:
                    leader.state = State.CARRYING_BOX
                except Exception:
                    pass
                exp.target = RUINS_XY
                exp.phase = "ruins"
                for mid in [exp.leader_id, *exp.member_ids]:
                    ch = world.agents.get(mid)
                    if isinstance(ch, Character):
                        ch.target = RUINS_XY
                return
            # Step toward the carrier's current position.
            target = (carrier.x, carrier.y)
            exp.target = target
            for mid in [exp.leader_id, *exp.member_ids]:
                ch = world.agents.get(mid)
                if isinstance(ch, Character):
                    ch.target = target
            _walk_party(world, exp, target, DEPART_SPEED)
            d = math.hypot(leader.x - carrier.x, leader.y - carrier.y)
            if d <= MUSIC_BOX_RENDEZVOUS_RADIUS:
                # Leader joins the carrier. From here both head to the ruins.
                exp.phase = "ruins"
                exp.target = RUINS_XY
                # Make sure carrier is part of the marching party.
                if carrier.id != leader.id and carrier.id not in exp.member_ids:
                    exp.member_ids.append(carrier.id)
                    try:
                        carrier.state = State.EXPEDITION  # pin alongside leader
                        carrier.expedition_role = "carrier"
                        carrier.state_since_tick = world.tick_count
                    except Exception:
                        pass
                for mid in [exp.leader_id, *exp.member_ids]:
                    ch = world.agents.get(mid)
                    if isinstance(ch, Character):
                        ch.target = RUINS_XY
            return

        if exp.phase == "ruins":
            # Walk the carrier (and leader) to RUINS_XY. Agent A's
            # tick_music_box handles the actual destruction when within
            # MUSIC_BOX_DESTROY_RADIUS of the ruins.
            ref = carrier if isinstance(carrier, Character) and carrier.status == Status.ACTIVE else leader
            _walk_party(world, exp, RUINS_XY, DEPART_SPEED)
            d = math.hypot(ref.x - RUINS_XY[0], ref.y - RUINS_XY[1])
            if d <= MUSIC_BOX_DESTROY_RADIUS:
                # Arrived. Hold for one tick to let A's destroyer fire.
                # When the carrier is cleared by A, fold the expedition.
                if world.music_box_carrier is None or world.music_box_phase == "DORMANT":
                    exp.phase = "returning"
                    for mid in [exp.leader_id, *exp.member_ids]:
                        ch = world.agents.get(mid)
                        if isinstance(ch, Character) and ch.status == Status.ACTIVE:
                            ch.target = exp.home
            return

        if exp.phase == "returning":
            arrived = _walk_party(world, exp, exp.home, DEPART_SPEED)
            if arrived:
                _release_party(world, exp)
                world.emit(Event(
                    tick=world.tick_count, type="expedition_returned",
                    subject=exp.leader_id,
                    detail="music box destroyed; party home",
                    severity="info",
                ))
                _set_expedition(world, None)
                world.expedition_active = False
                world._expedition_is_music_box = False  # type: ignore[attr-defined]
            return

        # Unknown music-box phase — recover by bailing out.
        _release_party(world, exp)
        _set_expedition(world, None)
        world.expedition_active = False
        world._expedition_is_music_box = False  # type: ignore[attr-defined]
        return

    # ------------------------------------------------ drive existing expedition
    if exp.phase == "departing":
        arrived = _walk_party(world, exp, exp.target, DEPART_SPEED)
        if arrived:
            exp.phase = "milling"
            exp.mill_start_tick = world.tick_count
        return

    if exp.phase == "milling":
        # Add tension during the mill: small fear bump every ~10 ticks.
        if (world.tick_count - exp.mill_start_tick) % 10 == 0:
            for mid in [exp.leader_id, *exp.member_ids]:
                ch = world.agents.get(mid)
                if isinstance(ch, Character) and ch.status == Status.ACTIVE:
                    ch.fear = min(100.0, ch.fear + 1.0)
        # Past DUSK: sharp fear, chance of death.
        if world.time.phase in (Phase.DUSK, Phase.NIGHT):
            for mid in [exp.leader_id, *exp.member_ids]:
                ch = world.agents.get(mid)
                if isinstance(ch, Character) and ch.status == Status.ACTIVE:
                    ch.fear = min(100.0, ch.fear + 3.0)
                    ch.sanity = max(0.0, ch.sanity - 0.5)
            # 1.5% chance per tick after dusk for one member to die.
            if world.time.phase == Phase.NIGHT and world.rng.random() < 0.015:
                # Don't kill the leader as the first casualty.
                pool = [world.agents[mid] for mid in exp.member_ids
                        if isinstance(world.agents.get(mid), Character)
                        and world.agents[mid].status == Status.ACTIVE]
                if pool:
                    victim = world.rng.choice(pool)
                    victim.status = Status.DEAD
                    world.emit(Event(
                        tick=world.tick_count, type="char_death",
                        subject=victim.id,
                        detail=f"lost on expedition with {exp.leader_id}",
                        severity="crit",
                    ))
        # Mill is done.
        if world.tick_count - exp.mill_start_tick >= EXPEDITION_MILL_TICKS:
            exp.phase = "returning"
            for mid in [exp.leader_id, *exp.member_ids]:
                ch = world.agents.get(mid)
                if isinstance(ch, Character) and ch.status == Status.ACTIVE:
                    ch.target = exp.home
        return

    if exp.phase == "returning":
        arrived = _walk_party(world, exp, exp.home, DEPART_SPEED)
        if arrived:
            # Survivors deposit food.
            survivors = [
                world.agents[mid] for mid in [exp.leader_id, *exp.member_ids]
                if isinstance(world.agents.get(mid), Character)
                and world.agents[mid].status == Status.ACTIVE
            ]
            haul = FOOD_REWARD * (len(survivors) / max(1, 1 + len(exp.member_ids)))
            # We do not own world.food_supply, but the brief implies we may raise it
            # when an expedition completes. Cap by capacity.
            try:
                world.food_supply = min(world.food_capacity, world.food_supply + haul)
            except Exception:
                pass
            _release_party(world, exp)
            world.emit(Event(
                tick=world.tick_count, type="expedition_returned",
                subject=exp.leader_id,
                detail=f"survivors={len(survivors)} food+={haul:.0f}",
                severity="info" if len(survivors) == 1 + len(exp.member_ids) else "warn",
            ))
            _set_expedition(world, None)
            world.expedition_active = False
        return
