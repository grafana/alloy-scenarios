"""
World construction and reset helpers.

The ``World`` dataclass itself lives in ``contracts.py`` — DO NOT redefine it
here. This module is responsible for:

  * ``build_world(config)``    — first-time construction of a fresh world.
  * ``reset_world(world)``     — village-wipe reseed: clear non-engine entities,
                                  re-apply ``BUILDING_LAYOUT``, reset food and
                                  farm health, bump ``village_wipes``.

Both functions touch ONLY engine-owned fields (per contracts.py ownership map).
Agent B and Agent C re-populate ``world.agents`` after a reset; we just clear
the dict so they can repopulate from a clean slate.
"""

from __future__ import annotations

import random

from contracts import (
    BUILDING_LAYOUT,
    Building,
    BusState,
    Config,
    Legacy,
    Phase,
    SimTime,
    World,
    YellowState,
)
from events import make_event_buffer
from legacy import distill_legacy_from


def _apply_building_layout(world: World) -> None:
    """(Re)materialise ``world.buildings`` from the static layout table."""
    world.buildings.clear()
    for (b_id, name, x, y, footprint, has_talisman, role_tag) in BUILDING_LAYOUT:
        world.buildings[b_id] = Building(
            id=b_id,
            name=name,
            x=float(x),
            y=float(y),
            footprint=int(footprint),
            has_talisman=bool(has_talisman),
            role_tag=role_tag,
            locked=False,
        )


def build_world(config: Config) -> World:
    """Construct a brand-new world.

    Seeds the RNG (deterministic when ``config.seed`` is set), installs the
    building layout, wires up the bounded event buffer, and returns the world.
    Telemetry is attached later by ``simulation.start()``.
    """
    rng = random.Random(config.seed) if config.seed is not None else random.Random()
    world = World(
        config=config,
        rng=rng,
        tick_count=0,
        time=SimTime(day=0, hour=6, minute=0, phase=Phase.DAY),
        lighting=1.0,
        food_supply=100.0,
        food_capacity=200.0,
        farm_health=1.0,
        last_phase=Phase.DAY,
    )
    world.events = make_event_buffer()
    _apply_building_layout(world)
    return world


def reset_world(world: World) -> None:
    """Wipe-and-reseed in place. Called by the engine when a wipe is pending.

    Clears creatures, supernaturals, and characters (Agent B/C will repopulate
    on their next tick). Re-applies the building layout, resets food/farm,
    increments the wipe counter, and clears the ``pending_reset`` flag.
    Engine time is reset to D0 06:00 of a fresh cycle.

    v2: ``world.legacy`` and ``world.bus.next_arrival_cycle`` SURVIVE the wipe.
    Before bulldozing, we ``distill_legacy_from(world)`` — that scans the dying
    cycle's events and applies the marks/drift/fragment-burning to the Legacy.
    Pending prophecies for the next cycle survive too.
    """
    # 1) Distill the lessons of this cycle into the Legacy BEFORE the wipe.
    distill_legacy_from(world)

    # 2) Bump the legacy counter once per wipe.
    world.legacy.cycles_witnessed += 1
    world.village_wipes += 1
    world.pending_reset = False

    # Engine-owned entities
    world.creatures.clear()
    world.supernaturals.clear()

    # Cross-slice state — cleared here because a wipe is global.
    world.agents.clear()
    world.meeting_outcomes.clear()
    world.recognition_counts.clear()
    world.yellow_touched_npcs.clear()
    world.yellow_active = YellowState()
    world.expedition_authorised = False
    world.expedition_active = False

    # v2 — transient state cleared, persistent state preserved.
    world.trust = {}  # baseline gets re-seeded by Agent B on character build
    world.active_dreams.clear()
    world.lighthouse_called = None
    world.lighthouse_voice_active = False
    # Bus: preserve next_arrival_cycle counter (so the cadence persists), reset
    # the rest. If we just left a cycle whose number IS the scheduled arrival,
    # the bus tick logic will activate after rebuild.
    preserved_next = world.bus.next_arrival_cycle
    world.bus = BusState(next_arrival_cycle=preserved_next)

    # Engine state
    world.food_supply = 100.0
    world.farm_health = 1.0
    world.farm_disaster_until_tick = 0
    world.tick_count = 0
    world.time = SimTime(day=0, hour=6, minute=0, phase=Phase.DAY)
    world.last_phase = Phase.DAY
    world.lighting = 1.0

    # Buildings reseed from layout (clears occupants, re-locks doors, etc.)
    _apply_building_layout(world)

    # Fresh event buffer so the post-reset UI isn't haunted by the last cycle.
    world.events = make_event_buffer()
