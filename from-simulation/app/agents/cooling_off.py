"""
House cooling-off sweep — v4 talisman repair tick.

After a creature breach or a music-box-induced talisman flicker, a building's
``cooling_off_until_tick`` is bumped forward. While ``world.tick_count`` is
below that mark, ``Building.is_protected()`` returns False even when
``has_talisman`` is True. This module owns the *cleanup* side: when the timer
expires, emit ``house_cleared`` and stop reporting the building as cooling-off.

The bumping is done by callers (creatures.py, music_box.py); this tick just
clears the expired marks and updates the ``HOUSES_COOLING_OFF`` gauge.
"""

from __future__ import annotations

from contracts import Event, Metric, World


def tick_cooling_off(world: World) -> None:
    """Sweep every building, expire stale cool-offs, emit + report gauge."""
    now = world.tick_count
    active = 0
    for b in world.buildings.values():
        if b.cooling_off_until_tick > 0 and now >= b.cooling_off_until_tick:
            b.cooling_off_until_tick = 0
            world.emit(
                Event(
                    tick=now,
                    type="house_cleared",
                    subject=b.id,
                    detail="cooling-off ended",
                    severity="info",
                )
            )
        if b.cooling_off_until_tick > now:
            active += 1
    if world.telemetry is not None:
        world.telemetry.gauge_set(Metric.HOUSES_COOLING_OFF, float(active))
