"""
Population management for unnamed NPCs.

Spawns new arrivals from the forest edge and reaps the dead. Runs once per
sim-tick from the engine loop via ``tick_population(world)``.

Spawn rule:
    * If active NPC count drops below ``config.npc_floor`` -> spawn one.
    * Otherwise a flat ~1/600 random chance per tick -> spawn one.

A spawn picks a random ``NPC_INTAKE_POINTS`` entry, generates a fresh name,
emits ``npc_arrival``, and adds the NPC to ``world.agents``.

Death rule:
    * Anything in ``world.agents`` that is an NPC and whose ``status`` is
      ``Status.DEAD`` gets removed from the dict, with an ``npc_death`` event.

The NPC gauge ``from_sim_npcs_active`` is set every tick.
"""

from __future__ import annotations

from typing import List

from contracts import (
    AgentKind,
    CAR_PATH_IN,
    CAR_PARK_XY,
    Event,
    Metric,
    NPC_INTAKE_POINTS,
    Status,
    World,
)
from agents.npcs import NPC, assign_family, generate_npc_name, pick_home_id
from agents import cars as _cars


# v6 — chance an NPC arrival comes by car instead of on foot. Only applies
# when no Car is currently active in the world (one at a time).
_CAR_ARRIVAL_PROBABILITY = 0.35


# Numeric counter so NPC ids are stable + unique across a single cycle.
# A reset clears world.agents; we also clear this on reset via clear_npcs().
_NPC_COUNTER = {"n": 0}


def _next_npc_id(world: World) -> str:
    _NPC_COUNTER["n"] += 1
    # Encode the cycle number so ids never collide across resets either.
    return f"npc_{world.cycle_number}_{_NPC_COUNTER['n']}"


def _count_active_npcs(world: World) -> int:
    return sum(
        1
        for a in world.agents.values()
        if getattr(a, "kind", None) == AgentKind.NPC
        and getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
    )


def spawn_npc(world: World) -> NPC:
    """Spawn one NPC. v6 — ~35% chance it arrives by car instead of on foot.

    On a car-arrival roll the NPC is created at the car's starting waypoint
    (the road edge), placed in ``Status.ABSENT`` so they don't tick or render
    as walkable until the car parks, and ``cars.spawn_car`` is invoked to put
    the actual vehicle on the map. When the car emits ``car_arrival``,
    ``tick_population`` reads ``world.car_pending_npc_id`` and alights the
    passenger (flipping to ACTIVE at ``CAR_PARK_XY``).

    On a foot-arrival roll (the default) the NPC appears at a random intake
    point as before.
    """
    rng = world.rng

    use_car = (
        world.active_car_id is None
        and rng.random() < _CAR_ARRIVAL_PROBABILITY
    )

    if use_car:
        # Place the NPC at the car's first waypoint and mirror their position
        # to the car's. They're ABSENT until the car parks, so the existing
        # tick loop skips them. ``home_id`` is still bound now so the
        # snapshot has a stable home from tick 0 if the frontend cares.
        if CAR_PATH_IN:
            x, y = CAR_PATH_IN[0]
        else:
            x, y = CAR_PARK_XY
        npc = NPC(
            npc_id=_next_npc_id(world),
            name=generate_npc_name(world),
            x=float(x),
            y=float(y),
        )
        npc.arrived_at_tick = world.tick_count
        npc.home_id = pick_home_id(world)
        npc.surname = assign_family(world, npc.id)
        # Hide them until the car parks. ``tick_population`` flips this back
        # to ACTIVE when ``world.car_pending_npc_id`` matches.
        npc.status = Status.ABSENT
        world.agents[npc.id] = npc
        # Spawn the car. ``spawn_car`` sets ``world.active_car_id``; the car
        # remembers the npc id and triggers car_arrival on parking.
        _cars.spawn_car(world, npc.id)
        return npc

    # Foot-arrival — original behaviour.
    x, y = rng.choice(NPC_INTAKE_POINTS)
    # Small jitter so they don't all stack on the exact same pixel.
    x += rng.uniform(-12, 12)
    y += rng.uniform(-12, 12)
    npc = NPC(
        npc_id=_next_npc_id(world),
        name=generate_npc_name(world),
        x=x,
        y=y,
    )
    npc.arrived_at_tick = world.tick_count
    # v4: bind a home building on spawn so the snapshot shows it from tick 0.
    # ``pick_home_id`` may return None (every house in cool-off); the NPC's
    # own tick will retry until something opens up.
    npc.home_id = pick_home_id(world)
    npc.surname = assign_family(world, npc.id)
    world.agents[npc.id] = npc

    full_name = f"{npc.name} {npc.surname}" if npc.surname else npc.name
    world.emit(
        Event(
            tick=world.tick_count,
            type="npc_arrival",
            subject=npc.id,
            detail=f"{full_name} arrived from the trees",
            severity="info",
        )
    )
    return npc


def _alight_car_passenger(world: World) -> None:
    """If a car has parked this tick, finalise the NPC's arrival.

    The Car sets ``world.car_pending_npc_id`` from ``_transition_parked``.
    We pop the id off the world, flip the NPC to ACTIVE, snap them to the
    car park location, and emit the canonical ``npc_arrival`` event so
    downstream systems (legacy journal, telemetry, intent strings) all
    behave exactly as if the NPC walked in on foot.
    """
    pid = world.car_pending_npc_id
    if pid is None:
        return
    world.car_pending_npc_id = None
    npc = world.agents.get(pid)
    if npc is None:
        return
    # Snap them off the car and onto the road spur.
    try:
        npc.x, npc.y = float(CAR_PARK_XY[0]), float(CAR_PARK_XY[1]) + 8.0
        npc.target_x, npc.target_y = npc.x, npc.y
    except Exception:
        pass
    try:
        npc.status = Status.ACTIVE
    except Exception:
        pass
    name = getattr(npc, "name", pid)
    world.emit(
        Event(
            tick=world.tick_count,
            type="npc_arrival",
            subject=npc.id,
            detail=f"{name} stepped out of a battered car",
            severity="info",
        )
    )


_TOMBSTONE_TICKS = 30


def _reap_dead(world: World) -> int:
    """Remove dead NPCs from ``world.agents``. Returns count reaped.

    v5: sub-mains get a 30-tick tombstone window. We mark them with
    ``_tombstone_until_tick`` on the first sighting (firing ``sub_main_died``
    + memory hook + clearing the home's occupants); subsequent reap passes
    skip them until the tick clock catches up, at which point they're fully
    removed. ``world.sub_mains`` is NEVER cleared — the lookup must survive
    so the snapshot's ``is_sub_main: True`` tag still applies for any
    retroactive debug/inspection.
    """
    dead_ids: List[str] = []
    for a in world.agents.values():
        if getattr(a, "kind", None) != AgentKind.NPC:
            continue
        if getattr(a, "status", Status.ACTIVE) == Status.DEAD:
            dead_ids.append(a.id)

    reaped = 0
    for nid in dead_ids:
        agent = world.agents.get(nid)
        if agent is None:
            continue
        is_sub_main = nid in world.sub_mains
        tombstone = int(getattr(agent, "_tombstone_until_tick", 0) or 0)

        # First-pass handling for any death.
        if is_sub_main and tombstone == 0:
            # Start the 30-tick tombstone. Fire sub_main_died + clear home,
            # but DO NOT remove from world.agents — the frontend will render
            # the fading marker until the window elapses.
            name = getattr(agent, "name", nid)
            cause = getattr(agent, "death_cause", "unknown")
            try:
                agent._tombstone_until_tick = world.tick_count + _TOMBSTONE_TICKS
            except Exception:
                pass
            home_id = getattr(agent, "home_id", None)
            if home_id is not None:
                building = world.buildings.get(home_id)
                if building is not None:
                    building.occupants.discard(nid)
            world.yellow_touched_npcs.discard(nid)
            # Memory hook — best-effort. Memory swallows its own errors but we
            # still guard so a missing attribute doesn't blow up the reap.
            if world.memory is not None:
                try:
                    world.memory.mark_sub_main_dead(world, nid, cause)
                except Exception:
                    pass
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="sub_main_died",
                    subject=nid,
                    detail=f"{name} died ({cause})",
                    severity="crit",
                )
            )
            try:
                from agents.promotion import _record_sub_main_death
                _record_sub_main_death(1)
            except Exception:
                pass
            # Still emit npc_death so existing consumers (legacy hash marks,
            # creature attribution, etc.) keep working.
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="npc_death",
                    subject=nid,
                    detail=f"{name} did not survive the night",
                    severity="warn",
                )
            )
            # NB: NOT removed from world.agents — wait for the tombstone tick.
            continue

        if is_sub_main and world.tick_count < tombstone:
            # Still inside the tombstone window — leave the corpse on the map.
            continue

        # Regular (non-sub-main) death OR sub-main whose tombstone has elapsed.
        agent = world.agents.pop(nid, None)
        name = getattr(agent, "name", nid) if agent is not None else nid
        home_id = getattr(agent, "home_id", None) if agent is not None else None
        if home_id is not None:
            building = world.buildings.get(home_id)
            if building is not None:
                building.occupants.discard(nid)
        # If this NPC was puppeted, drop the touch — they're gone.
        world.yellow_touched_npcs.discard(nid)
        if not is_sub_main:
            # Sub-mains already emitted npc_death + sub_main_died on the first
            # pass; don't double-emit when the tombstone clears.
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="npc_death",
                    subject=nid,
                    detail=f"{name} did not survive the night",
                    severity="warn",
                )
            )
        reaped += 1
    return reaped


def clear_npcs(world: World) -> None:
    """Drop every NPC from ``world.agents``. Called by reset hook."""
    npc_ids = [a.id for a in world.agents.values() if getattr(a, "kind", None) == AgentKind.NPC]
    for nid in npc_ids:
        world.agents.pop(nid, None)
    _NPC_COUNTER["n"] = 0


def tick_population(world: World) -> None:
    """Engine hook — call once per tick, after agent ticks have run."""
    # 1) Reap any newly-dead NPCs first so the floor count is honest.
    _reap_dead(world)

    # 1b) v6 — if a car parked this tick, finalise the NPC's arrival
    # (flip to ACTIVE + snap to road spur + emit npc_arrival).
    _alight_car_passenger(world)

    # 2) Maybe spawn.
    active = _count_active_npcs(world)
    floor = world.config.npc_floor
    rng = world.rng
    should_spawn = active < floor or rng.random() < (1.0 / 600.0)
    # Soft ceiling so we don't pile up NPCs forever in long-running cycles.
    ceiling = max(floor + 12, floor * 2)
    if should_spawn and active < ceiling:
        spawn_npc(world)

    # 3) Update the active gauge.
    if world.telemetry is not None:
        # Recount in case we just spawned.
        world.telemetry.gauge_set(
            Metric.NPCS_ACTIVE,
            float(_count_active_npcs(world)),
        )
        # v4: count NPCs that have been assigned a home building.
        homes_full = sum(
            1
            for a in world.agents.values()
            if getattr(a, "kind", None) == AgentKind.NPC
            and getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
            and getattr(a, "home_id", None) is not None
        )
        world.telemetry.gauge_set(Metric.NPC_HOMES_FULL, float(homes_full))
