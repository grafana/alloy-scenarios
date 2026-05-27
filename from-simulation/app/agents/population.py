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
    Event,
    Metric,
    NPC_INTAKE_POINTS,
    Status,
    World,
)
from agents.npcs import NPC, generate_npc_name, pick_home_id


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
    """Spawn one NPC at a random intake point. Used by ``tick_population``."""
    rng = world.rng
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
    world.agents[npc.id] = npc

    world.emit(
        Event(
            tick=world.tick_count,
            type="npc_arrival",
            subject=npc.id,
            detail=f"{npc.name} arrived from the trees",
            severity="info",
        )
    )
    return npc


def _reap_dead(world: World) -> int:
    """Remove dead NPCs from ``world.agents``. Returns count reaped."""
    dead_ids: List[str] = []
    for a in world.agents.values():
        if getattr(a, "kind", None) != AgentKind.NPC:
            continue
        if getattr(a, "status", Status.ACTIVE) == Status.DEAD:
            dead_ids.append(a.id)

    for nid in dead_ids:
        agent = world.agents.pop(nid, None)
        name = getattr(agent, "name", nid) if agent is not None else nid
        # v4: clear them from their home's occupant set.
        home_id = getattr(agent, "home_id", None) if agent is not None else None
        if home_id is not None:
            building = world.buildings.get(home_id)
            if building is not None:
                building.occupants.discard(nid)
        # If this NPC was puppeted, drop the touch — they're gone.
        world.yellow_touched_npcs.discard(nid)
        world.emit(
            Event(
                tick=world.tick_count,
                type="npc_death",
                subject=nid,
                detail=f"{name} did not survive the night",
                severity="warn",
            )
        )
    return len(dead_ids)


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
