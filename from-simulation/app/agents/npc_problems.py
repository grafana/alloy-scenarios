"""
NPC problems — sanity breaks inside talisman houses.

This file owns the night-time risk that lives *inside* a protected building.
The Creatures slice already handles outside threats (probing the door). Here
the threat comes from the people themselves: an NPC with low sanity and high
fear, sheltering inside a talisman building, has a small chance per tick to
break — they hurt the house's protection (cool-off) and the people inside.

Sequence on a successful break:

1. The building's talisman is treated as failed (``cooling_off_until_tick``
   advanced by ``config.house_cooling_off_ticks``). NPCs won't pick the house
   as a new home until cool-off clears (Agent A's ``cooling_off.py`` handles
   the timer and ``house_cleared`` event).
2. A ``npc_sanity_break`` event fires with the offending NPC as subject.
3. A ``creature_breach`` event also fires so v2's legacy distillation picks up
   the building as a hash mark.
4. Each occupant (NPC OR character) rolls ``config.npc_breach_death_prob``;
   on hit they die. ``npc_death`` / ``char_death`` events follow.
5. Surviving NPC occupants are displaced — given a new ``home_id`` that
   excludes the breached house — and shoved ~30 px toward town centre.
   ``npc_displaced`` and ``npc_settled`` events trail each relocation.

Engine wiring: call ``tick_npc_problems(world)`` once per tick from
``simulation._do_tick``. Safe to call every tick — it's a cheap no-op outside
NIGHT.
"""

from __future__ import annotations

import math
from typing import List, Tuple

from contracts import (
    AgentKind,
    Building,
    Event,
    Phase,
    Status,
    World,
)
import legacy
from agents.npcs import NPC, pick_home_id


# Town-centre reference for the "shove displaced occupants away" calculation.
_TOWN_CENTRE: Tuple[float, float] = (465.0, 475.0)
_DISPLACE_PX = 30.0


def _shove_toward_centre(agent, distance_px: float = _DISPLACE_PX) -> None:
    """Move ``agent`` ~distance_px toward the town centre from its current spot."""
    cx, cy = _TOWN_CENTRE
    dx = cx - agent.x
    dy = cy - agent.y
    d = math.hypot(dx, dy)
    if d <= 1e-3:
        # Already at centre — push in an arbitrary direction.
        agent.x += distance_px
        return
    agent.x = agent.x + (dx / d) * distance_px
    agent.y = agent.y + (dy / d) * distance_px


def _emit_house_cooling_off(world: World, building: Building, reason: str) -> None:
    world.emit(
        Event(
            tick=world.tick_count,
            type="house_cooling_off",
            subject=building.id,
            detail=f"{building.name} cooling off ({reason})",
            severity="warn",
        )
    )


def _trigger_break(world: World, npc: NPC, building: Building) -> None:
    """One NPC's sanity broke inside ``building`` — apply the consequences."""
    cfg = world.config

    # 1) Mark the house as cooling off (talisman fails).
    building.cooling_off_until_tick = world.tick_count + cfg.house_cooling_off_ticks
    _emit_house_cooling_off(world, building, "sanity break")

    # 2) Emit the sanity-break event itself.
    world.emit(
        Event(
            tick=world.tick_count,
            type="npc_sanity_break",
            subject=npc.id,
            detail=building.id,
            severity="crit",
        )
    )
    legacy.record(world, "npc_sanity_break", npc=npc.name, building=building.name)

    # 3) Emit a creature_breach so v2's hash-mark distillation picks it up.
    world.emit(
        Event(
            tick=world.tick_count,
            type="creature_breach",
            subject=building.id,
            detail=f"talisman failed inside {building.name}",
            severity="crit",
        )
    )

    # 4) Roll death for every occupant (the breaker included).
    occupant_ids: List[str] = list(building.occupants)
    survivors: List[str] = []
    for occ_id in occupant_ids:
        agent = world.agents.get(occ_id)
        if agent is None:
            continue
        if getattr(agent, "status", Status.ACTIVE) == Status.DEAD:
            continue
        if world.rng.random() < cfg.npc_breach_death_prob:
            agent.status = Status.DEAD
            kind = getattr(agent, "kind", None)
            name = getattr(agent, "name", agent.id)
            if kind == AgentKind.NPC:
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="npc_death",
                        subject=agent.id,
                        detail=f"{name} died when {building.name} broke",
                        severity="crit",
                    )
                )
            elif kind == AgentKind.CHARACTER:
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="char_death",
                        subject=agent.id,
                        detail=f"{name} died when {building.name} broke",
                        severity="crit",
                    )
                )
                legacy.record(world, "char_death", name=name)
            # Drop from occupants so they don't get displaced as survivors.
            building.occupants.discard(agent.id)
        else:
            survivors.append(occ_id)

    # 5) Displace survivors. NPCs get a new home; characters just get shoved.
    for sid in survivors:
        agent = world.agents.get(sid)
        if agent is None:
            continue
        # Leave the broken house's occupant set.
        building.occupants.discard(sid)
        # Move them ~30 px toward town centre.
        _shove_toward_centre(agent)

        if getattr(agent, "kind", None) == AgentKind.NPC:
            new_home = pick_home_id(world, exclude=[building.id])
            agent.home_id = new_home
            # ``_indoors`` lives on NPC; reset it so the new home isn't
            # already considered "inside" before they arrive.
            try:
                agent._indoors = False  # type: ignore[attr-defined]
            except Exception:
                pass
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="npc_displaced",
                    subject=agent.id,
                    detail=f"left {building.id}",
                    severity="warn",
                )
            )
            if new_home is not None:
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="npc_settled",
                        subject=new_home,
                        detail=f"{agent.name} re-homed to {new_home}",
                        severity="info",
                    )
                )


def tick_npc_problems(world: World) -> None:
    """Engine hook. Roll sanity breaks for NPCs sheltering at NIGHT.

    Cheap no-op outside NIGHT. Only one break per building per tick (we stop
    iterating that building's occupants once it goes into cool-off).
    """
    if world.time.phase != Phase.NIGHT:
        return

    cfg = world.config
    tick = world.tick_count

    # Walk a snapshot of buildings — _trigger_break mutates occupants and the
    # cool-off field, but we only roll on currently-protected ones.
    for building in list(world.buildings.values()):
        if not building.is_protected(tick):
            continue
        if not building.occupants:
            continue
        # Snapshot occupants so we don't iterate over a mutating set.
        for occ_id in list(building.occupants):
            agent = world.agents.get(occ_id)
            if agent is None:
                continue
            if getattr(agent, "kind", None) != AgentKind.NPC:
                continue
            if getattr(agent, "status", Status.ACTIVE) != Status.ACTIVE:
                continue
            sanity = float(getattr(agent, "sanity", 100.0))
            fear = float(getattr(agent, "fear", 0.0))
            if sanity >= cfg.npc_sanity_break_sanity:
                continue
            if fear <= cfg.npc_sanity_break_fear:
                continue
            if world.rng.random() < cfg.npc_sanity_break_prob:
                _trigger_break(world, agent, building)
                # House is now in cool-off — stop processing it this tick.
                break
