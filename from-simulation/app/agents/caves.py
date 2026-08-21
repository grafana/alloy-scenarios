"""
v6 — cave exploration mechanic.

When a character enters ``State.EXPLORING_CAVES`` (set by Agent B's movement
system for INVESTIGATOR / SEER on DAY phases), their movement system walks
them toward ``CAVE_ENTRY_XY``. Once they're within 25 px of the entry, this
module starts ticking a per-character ``caves_progress`` counter on the
agent.

At 30 ticks of exploration we roll one outcome from a weighted table:

  * 0.40 — ``cave_fragment_found``    (journal-only; legacy.cave_clues_found++)
  * 0.30 — ``cave_clue_found``        (Item.CAVE_CLUE added to inventory)
  * 0.22 — ``cave_scare``             (fear +30, FLEEING)
  * 0.05 — uneventful                 (just a "found nothing" emit)
  * 0.03 — ``cave_lost``              (status=ABSENT — kicks off the standard
                                       700-tick resurrection cycle)

After the outcome rolls (or as a safety bound after 60 ticks) we reset the
counter and switch the character's state back to ``WANDERING`` so the rest of
the FSM resumes. Inventory writes and event emission go through the same
pattern the rest of the engine uses (set the field, emit a canonical event,
record a journal fragment via ``legacy.record``).

Wiring contract: ``simulation._do_tick`` should call ``tick_caves(world)``
once per tick, after population and before social.
"""

from __future__ import annotations

from typing import Any

import legacy as _legacy
from contracts import (
    CAVE_ENTRY_XY,
    Event,
    Item,
    State,
    Status,
    World,
)
from agents.base import distance


# How close to the cave entry counts as "inside". The cave mouth occupies
# roughly a 50 px halo on the SVG — 60 px gives an explorer credit for
# being "in the caves" the moment they hit the outer ring, which matches
# the visual and lets progress accumulate before the FSM re-samples.
_CAVE_RADIUS_PX = 60.0
# How long a character pokes around before rolling an outcome.
_CAVE_OUTCOME_TICKS = 30
# Hard upper bound — even if the outcome was missed, force the cave run to
# end after this many ticks so we never leave a character spinning forever.
_CAVE_MAX_TICKS = 60

# Outcome keys + weights, in the order ``rng.choices`` is happy with.
_OUTCOMES = (
    "cave_fragment_found",
    "cave_clue_found",
    "cave_scare",
    "cave_uneventful",
    "cave_lost",
)
_OUTCOME_WEIGHTS = (0.40, 0.30, 0.22, 0.05, 0.03)


def _at_cave_entry(agent: Any) -> bool:
    cx, cy = CAVE_ENTRY_XY
    # ``distance`` handles tuple-or-object; pass a plain tuple to avoid leaking
    # a private dataclass.
    return distance(agent, (cx, cy)) <= _CAVE_RADIUS_PX


def _end_run(agent: Any, world: World, detail: str) -> None:
    """End the cave run cleanly — reset progress, emit bookend, restore state."""
    setattr(agent, "caves_progress", 0)
    # Only flip back to WANDERING if the agent is still alive and present.
    # If the outcome was ``cave_scare`` they're already FLEEING; if
    # ``cave_lost`` they're ABSENT. We honour those.
    if (
        getattr(agent, "status", Status.ACTIVE) == Status.ACTIVE
        and getattr(agent, "state", None) == State.EXPLORING_CAVES
    ):
        agent.state = State.WANDERING
    world.emit(
        Event(
            tick=world.tick_count,
            type="cave_explored",
            subject=getattr(agent, "id", "?"),
            detail=detail,
            severity="info",
        )
    )


def _roll_outcome(agent: Any, world: World) -> None:
    """Pick one weighted outcome and apply its side effects + events."""
    rng = world.rng
    name = getattr(agent, "name", getattr(agent, "id", "?"))
    pick = rng.choices(_OUTCOMES, weights=_OUTCOME_WEIGHTS, k=1)[0]

    if pick == "cave_fragment_found":
        world.legacy.cave_clues_found += 1
        world.emit(
            Event(
                tick=world.tick_count,
                type="cave_fragment_found",
                subject=getattr(agent, "id", "?"),
                detail=f"{name} found a fragment in the caves",
                severity="info",
            )
        )
        try:
            _legacy.record(world, "cave_fragment_found", name=name)
        except Exception:
            pass
        _end_run(agent, world, f"{name} returned with a fragment")
        return

    if pick == "cave_clue_found":
        # Add a CAVE_CLUE to the character's inventory (string key, as the
        # engine stores Item.value -> count).
        inv = getattr(agent, "inventory", None)
        if isinstance(inv, dict):
            key = Item.CAVE_CLUE.value
            inv[key] = int(inv.get(key, 0)) + 1
        world.emit(
            Event(
                tick=world.tick_count,
                type="cave_clue_found",
                subject=getattr(agent, "id", "?"),
                detail=f"{name} picked up a strange object in the caves",
                severity="info",
            )
        )
        try:
            _legacy.record(world, "cave_clue_found", name=name)
        except Exception:
            pass
        _end_run(agent, world, f"{name} pocketed something from the caves")
        return

    if pick == "cave_scare":
        try:
            agent.fear = min(100.0, float(getattr(agent, "fear", 0.0)) + 30.0)
        except Exception:
            pass
        # FLEEING is our "panic home" state. The character's own FSM resumes
        # next tick and will eventually decay back to WANDERING.
        if getattr(agent, "status", Status.ACTIVE) == Status.ACTIVE:
            agent.state = State.FLEEING
        world.emit(
            Event(
                tick=world.tick_count,
                type="cave_scare",
                subject=getattr(agent, "id", "?"),
                detail=f"{name} fled the caves",
                severity="warn",
            )
        )
        # No legacy line — fear is its own story; nothing to remember beyond
        # the event log.
        # Reset progress + bookend, but don't override the FLEEING state.
        setattr(agent, "caves_progress", 0)
        world.emit(
            Event(
                tick=world.tick_count,
                type="cave_explored",
                subject=getattr(agent, "id", "?"),
                detail=f"{name} ran out of the caves",
                severity="info",
            )
        )
        return

    if pick == "cave_uneventful":
        world.emit(
            Event(
                tick=world.tick_count,
                type="cave_explored",
                subject=getattr(agent, "id", "?"),
                detail="found nothing worth carrying home",
                severity="info",
            )
        )
        _end_run(agent, world, f"{name} surfaced empty-handed")
        return

    if pick == "cave_lost":
        # Rare bad outcome: status flips to ABSENT, which the standard
        # population/resurrection loop in population.py will eventually
        # bring back ~700 ticks later.
        try:
            agent.status = Status.ABSENT
        except Exception:
            pass
        world.emit(
            Event(
                tick=world.tick_count,
                type="cave_lost",
                subject=getattr(agent, "id", "?"),
                detail=f"{name} did not come out of the caves",
                severity="crit",
            )
        )
        try:
            _legacy.record(world, "cave_lost", name=name)
        except Exception:
            pass
        # No state restore — ABSENT characters don't tick.
        setattr(agent, "caves_progress", 0)
        return


def tick_caves(world: World) -> None:
    """Engine hook — drives every EXPLORING_CAVES character forward one tick.

    Idempotent + cheap when nobody is exploring. Honours ``Status.ACTIVE`` —
    DEAD/ABSENT/etc. agents are skipped.
    """
    for agent in list(world.agents.values()):
        if getattr(agent, "state", None) != State.EXPLORING_CAVES:
            # Reset any stale counter on agents who left the state for any
            # reason (B's movement system can override us on a phase flip).
            if getattr(agent, "caves_progress", 0):
                setattr(agent, "caves_progress", 0)
            continue
        if getattr(agent, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if not _at_cave_entry(agent):
            # Still walking in — let movement bring them. Don't tick yet.
            continue

        progress = int(getattr(agent, "caves_progress", 0)) + 1
        setattr(agent, "caves_progress", progress)

        if progress == _CAVE_OUTCOME_TICKS:
            _roll_outcome(agent, world)
            continue

        # Safety bound: if for some reason we sailed past the outcome tick
        # (e.g. some other module bumped caves_progress), force-end the run.
        if progress >= _CAVE_MAX_TICKS:
            _end_run(agent, world, "the caves gave up nothing more")
