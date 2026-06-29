"""
Food + farm tick loop.

Owned by Agent A (engine). Per tick:

  * Drain ``world.food_supply`` proportional to the number of "active" agents
    (ACTIVE / RETURNING status — DEAD / INCAPACITATED don't consume).
  * During DAY, regenerate food. Regen scales with both the active population
    and ``world.farm_health`` — so as NPCs accumulate across cycles, food
    production scales up with the mouths to feed.
  * v6+: the **barn** is the food store. While the barn is destroyed
    (``world.barn_destroyed_until_tick``), regen is throttled to 15% of normal
    and the food_shortage flag latches on so society pushes characters into
    FORAGING runs at the windmill / lake until the structure is rebuilt.
  * Roll farm disasters rarely. A disaster knocks farm_health down for a
    couple of sim-days.
  * Signal ``food_shortage`` to Agent B when supply is low (hysteresis).

Authorising an expedition is NOT done here — Agent B owns that. We just raise
the flag.
"""

from __future__ import annotations

from contracts import Event, Phase, Status, World


# ------------------------------------------------------------------ tunables

# Drain per active agent per tick. Lower than v5 (0.02 → 0.006 → 0.005) so a
# stable village with regen-equal-to-drain holds at full larder; only a
# disaster or a barn breach causes real pressure.
_PER_AGENT_DRAIN = 0.005

# v8 — food-shortage anxiety. When the larder runs low everyone loses
# sanity and gains fear, not just the characters who run hunger meters.
# These rates are per-agent, per-tick, multiplied by ``severity`` ∈ [0, 1]
# where severity == (1 - food_supply / SHORTAGE_THRESHOLD). At the
# threshold (severity=0) nothing happens; at zero food (severity=1) the
# full rate fires.
_SHORTAGE_THRESHOLD_FRAC = 0.35   # below 35% larder triggers anxiety
_SHORTAGE_FEAR_PER_TICK = 0.08    # 0.0..0.08 per tick scaled by severity
_SHORTAGE_SANITY_PER_TICK = 0.05  # 0.0..0.05 per tick scaled by severity

# Regen scales with active agents so production keeps pace as NPCs arrive. At
# farm_health=1.0 the regen factor is the multiplier on per-agent contribution.
# Tuned so net day-cycle change is moderately positive (food climbs) and the
# whole cycle (day+night) is roughly neutral, leaving slack for disasters.
_REGEN_PER_AGENT = 0.013          # × active agents × farm_health × phase factor
_REGEN_FLOOR = 0.10                # always at least this much during DAY
# Phase multiplier on regen. DAY is full. DAWN/DUSK get partial credit so the
# transitions don't feel like cliffs.
_REGEN_PHASE_MULT = {
    Phase.DAY: 1.0,
    Phase.DAWN: 0.5,
    Phase.DUSK: 0.3,
    Phase.NIGHT: 0.0,
}

# Barn-destroyed regen multiplier. While the barn is down the village can't
# store harvest — most of what's grown spoils. The forage mechanic in
# characters.py picks up the slack by sending crews to the windmill/lake.
_BARN_BROKEN_REGEN_MULT = 0.15

# Low-food signalling thresholds.
_LOW_THRESHOLD_FRAC = 0.30          # signal when food < 30% of capacity
_LOW_REARM_FRAC = 0.55              # rearm only after food climbs above 55%

# Farm disaster cadence. v5's 0.000417/tick = ~30%/sim-day was producing a
# disaster roughly every other sim-day; the village spent most cycles in
# disaster mode. Drop to ~0.00010/tick = ~7%/sim-day, so a healthy run
# stretches several days between disasters.
_DISASTER_PROB_PER_TICK = 0.00010
_DISASTER_DURATION_TICKS = 1500


def _active_agents(world: World) -> int:
    """Count agents that still consume food."""
    return sum(
        1
        for a in world.agents.values()
        if getattr(a, "status", Status.ACTIVE) in (Status.ACTIVE, Status.RETURNING)
    )


def _barn_broken(world: World) -> bool:
    """True while the barn (food store) is out of action.

    Field is lazily attached in agents/creatures.py the first time a creature
    breaches the barn. Cleared when reset_world wipes the cycle.
    """
    until = int(getattr(world, "barn_destroyed_until_tick", 0))
    return until > 0 and world.tick_count < until


def tick(world: World) -> None:
    """One tick of the food / farm subsystem."""
    active = _active_agents(world)

    # ---- Drain
    drain = active * _PER_AGENT_DRAIN
    world.food_supply = max(0.0, world.food_supply - drain)

    in_disaster = world.tick_count < world.farm_disaster_until_tick
    barn_broken = _barn_broken(world)

    # ---- Regen
    phase_mult = _REGEN_PHASE_MULT.get(world.time.phase, 0.0)
    if phase_mult > 0 and not in_disaster:
        # Population-scaled regen plus a small floor so a village with very
        # few survivors doesn't immediately starve.
        regen = (active * _REGEN_PER_AGENT + _REGEN_FLOOR) * float(world.farm_health)
        regen *= phase_mult
        if barn_broken:
            regen *= _BARN_BROKEN_REGEN_MULT
        world.food_supply = min(world.food_capacity, world.food_supply + regen)

    # ---- Disaster roll (rare)
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

    # ---- Disaster recovery
    if not in_disaster and world.farm_health < 1.0 and world.tick_count >= world.farm_disaster_until_tick:
        world.farm_health = min(1.0, world.farm_health + 0.001)

    # ---- Low-food signalling. The hysteresis prevents repeated
    # food_low spam when the supply hovers around the threshold.
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

    # ---- v8 — food-shortage anxiety pings every active agent. Characters
    # already have their own hunger → sanity coupling; this adds a global
    # layer so NPCs (which don't track hunger) also feel the squeeze.
    shortage_thresh = world.food_capacity * _SHORTAGE_THRESHOLD_FRAC
    if world.food_supply < shortage_thresh and shortage_thresh > 0:
        severity = max(0.0, min(1.0, 1.0 - world.food_supply / shortage_thresh))
        fear_gain = _SHORTAGE_FEAR_PER_TICK * severity
        sanity_loss = _SHORTAGE_SANITY_PER_TICK * severity
        for a in world.agents.values():
            if getattr(a, "status", Status.ACTIVE) not in (Status.ACTIVE, Status.RETURNING):
                continue
            try:
                cur_fear = float(getattr(a, "fear", 0.0))
                setattr(a, "fear", min(100.0, cur_fear + fear_gain))
                cur_sanity = float(getattr(a, "sanity", 100.0))
                setattr(a, "sanity", max(0.0, cur_sanity - sanity_loss))
            except Exception:
                pass
