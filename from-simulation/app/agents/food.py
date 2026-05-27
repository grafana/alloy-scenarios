"""
Food + farm tick loop.

Owned by Agent A (engine). Per tick:

  * Drain ``world.food_supply`` proportional to the number of "active" agents
    (ACTIVE / RETURNING status — DEAD / INCAPACITATED don't consume).
  * During DAY, when no farm disaster is active, regenerate food at a rate
    scaled by ``world.farm_health``.
  * Roll farm disasters (very rare per tick — ~1% per sim-day worth of ticks).
    A disaster knocks ``farm_health`` down to 0.2..0.5 for ~1500 ticks
    (~12.5 sim-minutes at 2 Hz) and emits ``farm_disaster``.
  * When ``food_supply`` drops below the "low" threshold and we haven't
    recently signalled, emit ``food_low`` and flip a transient
    ``world.food_shortage`` signal flag for Agent B's society loop to read.

Authorising an expedition is NOT done here — Agent B owns that. We just raise
the flag.
"""

from __future__ import annotations

from contracts import Event, Phase, Status, World


# Tunables (could be lifted into Config later if we want them at runtime).
_PER_AGENT_DRAIN = 0.02
_REGEN_FACTOR = 0.15
_LOW_THRESHOLD_FRAC = 0.25         # signal when food < 25% of capacity
_LOW_REARM_FRAC = 0.45             # rearm only after food climbs above 45%
_DISASTER_PROB_PER_TICK = 0.000417  # ~1% per sim-day worth of ticks (24 * 60 ticks at 2 Hz)
_DISASTER_DURATION_TICKS = 1500


def _active_agents(world: World) -> int:
    """Count agents that still consume food."""
    return sum(
        1
        for a in world.agents.values()
        if getattr(a, "status", Status.ACTIVE) in (Status.ACTIVE, Status.RETURNING)
    )


def tick(world: World) -> None:
    """One tick of the food / farm subsystem.

    Side effects on World (all engine-owned fields):
      * ``food_supply``
      * ``farm_health``
      * ``farm_disaster_until_tick``
      * ``food_shortage`` (transient flag — created lazily as an attribute;
        Agent B reads ``getattr(world, "food_shortage", False)``)
    """
    # Drain
    drain = _active_agents(world) * _PER_AGENT_DRAIN
    world.food_supply = max(0.0, world.food_supply - drain)

    in_disaster = world.tick_count < world.farm_disaster_until_tick

    # Regen during DAY when farm is healthy.
    if world.time.phase == Phase.DAY and not in_disaster:
        regen = max(0.0, world.farm_health) * _REGEN_FACTOR
        world.food_supply = min(world.food_capacity, world.food_supply + regen)

    # Disaster roll
    if not in_disaster and world.rng.random() < _DISASTER_PROB_PER_TICK:
        world.farm_health = world.rng.uniform(0.2, 0.5)
        world.farm_disaster_until_tick = world.tick_count + _DISASTER_DURATION_TICKS
        world.emit(
            Event(
                tick=world.tick_count,
                type="farm_disaster",
                subject="world",
                detail=f"farm crippled (health={world.farm_health:.2f})",
                severity="warn",
            )
        )

    # Recovery once disaster expires.
    if not in_disaster and world.farm_health < 1.0 and world.tick_count >= world.farm_disaster_until_tick:
        # Gradual recovery toward full health.
        world.farm_health = min(1.0, world.farm_health + 0.001)

    # Low-food signalling. We use a "rearm" hysteresis so we don't spam events.
    low_thresh = world.food_capacity * _LOW_THRESHOLD_FRAC
    rearm_thresh = world.food_capacity * _LOW_REARM_FRAC
    armed = getattr(world, "_food_low_signal_armed", True)
    if armed and world.food_supply < low_thresh:
        setattr(world, "food_shortage", True)
        setattr(world, "_food_low_signal_armed", False)
        world.emit(
            Event(
                tick=world.tick_count,
                type="food_low",
                subject="world",
                detail=f"food_supply={world.food_supply:.1f}/{world.food_capacity:.0f}",
                severity="warn",
            )
        )
    elif not armed and world.food_supply >= rearm_thresh:
        setattr(world, "food_shortage", False)
        setattr(world, "_food_low_signal_armed", True)
