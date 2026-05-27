"""
Resurrection / homecoming loop.

Agent B owns this module. Driven by ``characters.tick_societies(world)``.
Lifecycle:

* A character marked ``Status.DEAD`` by ``fear.py`` is converted to
  ``Status.ABSENT`` and a resurrection-tick is scheduled.
* On the scheduled tick the character is respawned at a forest intake point
  with ``Status.RETURNING`` (no role bonus while in this status).
* While ``RETURNING`` they wander town; every time another character passes
  within ``RECOGNITION_RADIUS`` we bump ``world.recognition_counts[id]``.
* When the recognition count crosses ``config.recognition_threshold`` they
  are restored to ``Status.ACTIVE`` and ``char_restored`` is emitted.
"""

from __future__ import annotations

import math
from typing import Dict

from contracts import Event, Status, World

from agents.characters import Character, respawn_character


RECOGNITION_RADIUS = 40.0


def _get_schedule(world: World) -> Dict[str, int]:
    """character id -> tick at which they respawn."""
    s = getattr(world, "_resurrection_schedule", None)
    if s is None:
        s = {}
        world._resurrection_schedule = s  # type: ignore[attr-defined]
    return s


def _get_recognised_recently(world: World) -> Dict[str, int]:
    """char_id -> last tick we credited a recognition (anti-spam)."""
    s = getattr(world, "_recognition_recent", None)
    if s is None:
        s = {}
        world._recognition_recent = s  # type: ignore[attr-defined]
    return s


def tick_resurrection(world: World) -> None:
    schedule = _get_schedule(world)

    # 1) Sweep for newly DEAD characters and convert -> ABSENT.
    for cid, agent in list(world.agents.items()):
        if not isinstance(agent, Character):
            continue
        if agent.status == Status.DEAD:
            agent.status = Status.ABSENT
            cfg = world.config
            jitter = world.rng.randint(-cfg.resurrection_jitter, cfg.resurrection_jitter)
            schedule[cid] = world.tick_count + cfg.resurrection_base_ticks + jitter
            world.emit(Event(
                tick=world.tick_count, type="char_absent",
                subject=cid, detail=f"{agent.name} has gone (return in ~{cfg.resurrection_base_ticks} ticks)",
                severity="warn",
            ))

    # 2) Check schedule for respawns.
    due = [cid for cid, when in schedule.items() if world.tick_count >= when]
    for cid in due:
        schedule.pop(cid, None)
        # Drop the absent agent record before respawning.
        prev = world.agents.get(cid)
        if isinstance(prev, Character) and prev.status == Status.ABSENT:
            del world.agents[cid]
        respawn_character(world, cid)
        # respawn_character emits "homecoming" itself.

    # 3) Recognition: characters near a RETURNING peer accrue recognition.
    recents = _get_recognised_recently(world)
    returners = [a for a in world.agents.values()
                 if isinstance(a, Character) and a.status == Status.RETURNING]
    actives = [a for a in world.agents.values()
               if isinstance(a, Character) and a.status == Status.ACTIVE]

    for r in returners:
        # Throttle: at most one recognition every ~20 ticks per returner.
        last = recents.get(r.id, -10_000)
        if world.tick_count - last < 20:
            continue
        for other in actives:
            d = math.hypot(other.x - r.x, other.y - r.y)
            if d <= RECOGNITION_RADIUS:
                world.recognition_counts[r.id] = world.recognition_counts.get(r.id, 0) + 1
                recents[r.id] = world.tick_count
                world.emit(Event(
                    tick=world.tick_count, type="char_recognised",
                    subject=r.id, detail=f"by {other.id} "
                    f"({world.recognition_counts[r.id]}/{world.config.recognition_threshold})",
                ))
                if world.recognition_counts[r.id] >= world.config.recognition_threshold:
                    r.status = Status.ACTIVE
                    world.recognition_counts.pop(r.id, None)
                    world.emit(Event(
                        tick=world.tick_count, type="char_restored",
                        subject=r.id, detail=f"{r.name} is recognised and restored",
                        severity="info",
                    ))
                break  # one bump per tick is plenty
