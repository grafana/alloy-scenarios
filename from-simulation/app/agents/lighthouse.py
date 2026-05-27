"""
Lighthouse — Agent A v2 engine hook.

Three responsibilities, all driven from ``tick_lighthouse(world)``:

1. **Calling.** Once per cycle, at the tick corresponding to
   ``int(lighthouse_call_tick_frac * 720)``, pick the highest-sanity ACTIVE
   character and "call" them. We record the id on ``world.lighthouse_called``
   and tag the character with ``called=True``. We do NOT change their state —
   biasing toward LIGHTHOUSE is Agent B's concern.

2. **Entering.** Each tick, check whether the called character has wandered
   within 30 px of the lighthouse building at NIGHT. If so, the lighthouse
   "swallows" them: voice activates, character becomes ABSENT and is queued
   for removal next tick, a journal fragment is recorded.

3. **Voice.** While ``world.lighthouse_voice_active`` is True, broadcast a
   cryptic ``lighthouse_voice`` line about every 40 ticks. Lines are pulled
   from a small template pool.
"""

from __future__ import annotations

from typing import Optional

import legacy as _legacy
from contracts import (
    Event,
    Phase,
    Status,
    World,
)
from agents.base import distance


# One sim-day = 720 ticks at the configured cadence (12h * 60min / 2min step).
_TICKS_PER_DAY = 720
_ENTER_RADIUS_PX = 30.0
_VOICE_CADENCE_TICKS = 40


_VOICE_LINES = [
    "It is colder where I am.",
    "There are doors here you have not seen.",
    "The roads loop. So do we.",
    "You are not the first to answer.",
    "The light is not for finding. It is for keeping.",
    "Listen for the tone beneath the wind.",
    "I see you from the bottom of the stairs.",
    "Hold onto the names you still know.",
]


# Cycle-keyed memo for "did we already make the call this cycle?". Reset by
# checking the call-tick equality but we also guard against duplicate emission
# inside the same tick by using a module-local set indexed by cycle.
_called_cycles: set = set()


def _find_lighthouse(world: World):
    return world.buildings.get("lighthouse")


def _maybe_call(world: World) -> None:
    cfg = world.config
    call_tick = int(cfg.lighthouse_call_tick_frac * _TICKS_PER_DAY)
    cycle = world.cycle_number
    if cycle in _called_cycles:
        return

    # Tick-within-the-sim-day: SimTime advances 2 min per tick at TIME_SCALE=1,
    # so dividing minutes-today by 2 recovers the tick index of the day.
    tick_today = world.time.minutes_today // 2
    if tick_today < call_tick:
        return

    # Find a callable target: highest sanity, ACTIVE character.
    candidates = [
        a for a in world.agents.values()
        if getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
        and getattr(a, "kind", None) is not None
        and getattr(a.kind, "value", "") == "character"
    ]
    if not candidates:
        return
    target = max(candidates, key=lambda a: float(getattr(a, "sanity", 100.0)))
    world.lighthouse_called = target.id
    try:
        setattr(target, "called", True)
    except Exception:
        pass
    _called_cycles.add(cycle)
    world.emit(
        Event(
            tick=world.tick_count,
            type="lighthouse_call",
            subject=target.id,
            detail="the Lighthouse has chosen you",
            severity="warn",
        )
    )


def _maybe_enter(world: World) -> None:
    if world.lighthouse_voice_active:
        return  # already inside
    if world.lighthouse_called is None:
        return
    if world.time.phase != Phase.NIGHT:
        return
    char = world.agents.get(world.lighthouse_called)
    if char is None:
        return
    house = _find_lighthouse(world)
    if house is None:
        return
    if distance(char, house) > _ENTER_RADIUS_PX:
        return

    # Swallow the character.
    world.lighthouse_voice_active = True
    name = getattr(char, "name", char.id)
    try:
        setattr(char, "status", Status.ABSENT)
    except Exception:
        pass
    # Mark for removal — Agent B's society pass and our own removal sweep
    # both watch this flag. We don't pop from world.agents mid-iteration; we
    # remove on the next tick at the top.
    try:
        setattr(char, "_remove_next_tick", True)
    except Exception:
        pass

    world.emit(
        Event(
            tick=world.tick_count,
            type="lighthouse_enter",
            subject=char.id,
            detail=f"{name} walked into the Lighthouse",
            severity="crit",
        )
    )
    _legacy.record(world, "lighthouse_enter", name=name)


def _maybe_voice(world: World) -> None:
    if not world.lighthouse_voice_active:
        return
    if world.tick_count <= 0:
        return
    if world.tick_count % _VOICE_CADENCE_TICKS != 0:
        return
    line = world.rng.choice(_VOICE_LINES)
    speaker = world.lighthouse_called or "lighthouse"
    world.emit(
        Event(
            tick=world.tick_count,
            type="lighthouse_voice",
            subject=speaker,
            detail=line,
            severity="info",
        )
    )


def _sweep_removals(world: World) -> None:
    """Drop any agents marked ``_remove_next_tick`` last tick."""
    to_remove = [
        aid for aid, a in world.agents.items()
        if getattr(a, "_remove_next_tick", False)
    ]
    for aid in to_remove:
        try:
            del world.agents[aid]
        except KeyError:
            pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def tick_lighthouse(world: World) -> None:
    """Drive call/enter/voice for the Lighthouse subsystem.

    Wired into ``simulation._do_tick`` after ``tick_yellow`` so a wipe-in-
    progress can't race a lighthouse call.
    """
    # Cycle wipes invalidate our memo: keep the set bounded.
    if len(_called_cycles) > 64:
        _called_cycles.clear()

    _sweep_removals(world)
    _maybe_call(world)
    _maybe_enter(world)
    _maybe_voice(world)
