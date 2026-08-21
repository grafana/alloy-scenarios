"""
Day/night cycle helpers.

The simulation runs 24 sim-hours per cycle. Phases are derived purely from
``SimTime`` so they can be computed at any point without needing extra state.

    DAWN : 05:00 -> 06:00     (lighting ramps 0 -> 1)
    DAY  : 06:00 -> 18:00     (lighting = 1)
    DUSK : 18:00 -> 20:00     (lighting ramps 1 -> 0)
    NIGHT: 20:00 -> 05:00     (lighting = 0)

``update_lighting`` uses a smooth cosine ramp during DAWN/DUSK so the UI gets a
gentle, continuous brightness curve instead of a step function. Lighting feeds
the SVG day/night overlay (Agent D) and the creature spawn gate (Agent A).
"""

from __future__ import annotations

import math

from contracts import Phase, SimTime, World


# Boundaries in sim-minutes from midnight.
_DAWN_START = 5 * 60      # 05:00
_DAY_START = 6 * 60       # 06:00
_DUSK_START = 18 * 60     # 18:00
_NIGHT_START = 20 * 60    # 20:00


def phase_for(sim_time: SimTime) -> Phase:
    """Return the current ``Phase`` strictly as a function of ``sim_time``.

    Boundaries are inclusive of the lower bound and exclusive of the upper.
    """
    m = sim_time.minutes_today
    if _DAWN_START <= m < _DAY_START:
        return Phase.DAWN
    if _DAY_START <= m < _DUSK_START:
        return Phase.DAY
    if _DUSK_START <= m < _NIGHT_START:
        return Phase.DUSK
    return Phase.NIGHT


def _smooth_ramp(progress: float) -> float:
    """Half-cosine ease: 0 -> 1 as progress goes 0 -> 1."""
    p = max(0.0, min(1.0, progress))
    # (1 - cos(pi * p)) / 2 produces a soft S-curve in [0, 1].
    return 0.5 * (1.0 - math.cos(math.pi * p))


def update_lighting(world: World) -> None:
    """Recompute ``world.lighting`` from ``world.time``.

    Lighting is a float in [0, 1]. The cosine ramp gives the dusk/dawn
    transitions a soft S-curve rather than a linear fade.
    """
    m = world.time.minutes_today
    if _DAY_START <= m < _DUSK_START:
        world.lighting = 1.0
    elif _NIGHT_START <= m or m < _DAWN_START:
        world.lighting = 0.0
    elif _DAWN_START <= m < _DAY_START:
        progress = (m - _DAWN_START) / float(_DAY_START - _DAWN_START)
        world.lighting = _smooth_ramp(progress)
    else:  # DUSK
        progress = (m - _DUSK_START) / float(_NIGHT_START - _DUSK_START)
        world.lighting = 1.0 - _smooth_ramp(progress)
