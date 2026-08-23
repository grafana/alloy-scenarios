"""
v7 — foraging mechanic.

When ``world.barn_destroyed_until_tick > world.tick_count``, the colony's
food store is gone and characters in ``State.FORAGING`` walk to one of the
``FORAGE_ZONES`` (windmill, lakeside river, western pond), gather for
``FORAGE_TICKS_TO_GATHER`` ticks, then return food directly to
``world.food_supply``.

Lifecycle:
  1. Agent B picks FORAGING via the transition table (boosted when the barn
     is down or food is low). Agent's ``target_x/target_y`` is set to a
     forage zone in ``_target_for_role_and_state``.
  2. ``tick_forage`` watches every FORAGING agent each tick:
     - If they're > 20 px from the chosen zone, do nothing (they're walking).
     - If within 20 px, increment ``forage_progress`` and emit a one-time
       ``forage_started`` event.
     - When progress hits ``FORAGE_TICKS_TO_GATHER`` add ``FORAGE_FOOD_PAYOFF``
       food to the larder, emit ``forage_returned``, clear progress, snap
       back to WANDERING so they walk home and re-enter the FSM normally.

Wiring: ``simulation._do_tick`` calls ``tick_forage(world)`` after the
character FSM has run (so state changes settle) and before food.tick (so any
returned food is counted in this tick's drain calc).
"""

from __future__ import annotations

from typing import Any

from contracts import (
    Event,
    FORAGE_FOOD_PAYOFF,
    FORAGE_TICKS_TO_GATHER,
    FORAGE_ZONES,
    State,
    Status,
    World,
)


_AT_ZONE_RADIUS_PX = 22.0


def _at_forage_zone(agent: Any) -> bool:
    chosen = getattr(agent, "_forage_zone", None)
    if chosen is None:
        return False
    dx = float(agent.x) - chosen[0]
    dy = float(agent.y) - chosen[1]
    return (dx * dx + dy * dy) ** 0.5 <= _AT_ZONE_RADIUS_PX


def tick_forage(world: World) -> None:
    """Advance every FORAGING character's gather progress + emit on completion."""
    for agent in list(world.agents.values()):
        if getattr(agent, "state", None) != State.FORAGING:
            # Drop any stale progress if they left the state for any reason.
            if getattr(agent, "forage_progress", 0):
                setattr(agent, "forage_progress", 0)
            continue
        if getattr(agent, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if not _at_forage_zone(agent):
            continue

        progress = int(getattr(agent, "forage_progress", 0)) + 1
        setattr(agent, "forage_progress", progress)

        # First tick of progress — emit a started event so the journal /
        # event log records the trip.
        if progress == 1:
            world.emit(Event(
                tick=world.tick_count,
                type="forage_started",
                subject=getattr(agent, "id", "?"),
                detail=(
                    f"{getattr(agent, 'name', agent.id)} began foraging at "
                    f"({getattr(agent, '_forage_zone', (0,0))[0]:.0f},"
                    f"{getattr(agent, '_forage_zone', (0,0))[1]:.0f})"
                ),
                severity="info",
            ))

        if progress >= FORAGE_TICKS_TO_GATHER:
            world.food_supply = min(
                world.food_capacity,
                world.food_supply + FORAGE_FOOD_PAYOFF,
            )
            world.emit(Event(
                tick=world.tick_count,
                type="forage_returned",
                subject=getattr(agent, "id", "?"),
                detail=(
                    f"{getattr(agent, 'name', agent.id)} brought back "
                    f"{FORAGE_FOOD_PAYOFF:.0f} food"
                ),
                severity="info",
            ))
            setattr(agent, "forage_progress", 0)
            setattr(agent, "_forage_zone", None)
            # Drop back to WANDERING so the regular FSM resumes; they'll walk
            # home or pick a new state next tick.
            agent.state = State.WANDERING
