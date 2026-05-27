"""
Cross-cycle memory — the only thing the universe remembers across wipes.

Two responsibilities:

1. ``distill_legacy_from(world)`` — called by ``reset_world`` *before* it
   bulldozes the world. Scans the dying cycle's events and applies their
   lessons to ``world.legacy``: hash marks for every breach, drift deltas
   for every named character who died, survival rolls for journal fragments,
   trauma counters for repeated deaths.

2. ``record(world, template_key, **slots)`` — the journal narrator. Agent B
   calls this on canonical events (creature_breach, char_death, homecoming,
   imposter_banished, village_wipe, outsider_died). Each call appends a one-
   line ``JournalFragment`` keyed off short lyrical templates.

The legacy object lives on World and survives reset. After many cycles it
becomes the only continuous thread linking otherwise-isolated universes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from contracts import (
    Event,
    JournalFragment,
    Legacy,
    World,
)


# ---------------------------------------------------------------------------
# Journal templates — one-line lyrical summaries, slot interpolation.
# ---------------------------------------------------------------------------


# Each template family has multiple variants; the rng picks one. Templates use
# ``{slot}`` substitution. Slot names match the kwargs passed to ``record``.
_TEMPLATES: Dict[str, List[str]] = {
    "creature_breach": [
        "The {building} door did not hold this night.",
        "A creature found a way in through the {building}.",
        "Talisman or no, the {building} was breached.",
    ],
    "char_death": [
        "{name} did not live to see another dawn.",
        "We lost {name} in the dark.",
        "{name} was taken from us. Again, perhaps. None of us is sure.",
    ],
    "homecoming": [
        "{name} came back along the forest road.",
        "{name} returned. Older somehow. Quieter.",
        "{name} walked out of the trees. We did not ask where they had been.",
    ],
    "imposter_banished": [
        "We sent the yellow thing away from the {building}.",
        "The imposter was named, and named, and named again. It left.",
        "We voted. Whatever it was, it is gone.",
    ],
    "village_wipe": [
        "And then there was nothing.",
        "The town went quiet in a way it should not be possible to go quiet.",
        "We failed. The cycle closed. Pages from this one will not all be saved.",
    ],
    "outsider_died": [
        "The {name} from the bus did not get back on it.",
        "{name} came here looking for {goal}, and found something else.",
    ],
    "expedition_returned": [
        "Boyd brought food back from the trees, and most of the party.",
        "We ate that night. We tried not to count the empty chairs.",
    ],
    "lighthouse_enter": [
        "{name} walked into the Lighthouse and did not walk out.",
        "{name} answered the Lighthouse. We heard them on the wind after.",
    ],
}


def _pick_template(world: World, key: str) -> Optional[str]:
    pool = _TEMPLATES.get(key)
    if not pool:
        return None
    return world.rng.choice(pool)


# ---------------------------------------------------------------------------
# Public: record a journal fragment
# ---------------------------------------------------------------------------


def record(world: World, key: str, **slots: Any) -> None:
    """Append one journal fragment about a canonical event.

    Quietly skips if the key is unknown — keeps callers from blowing up on a
    typo. The fragment is pristine on creation; ``distill_legacy_from`` rolls
    survival/burning at each wipe.
    """
    template = _pick_template(world, key)
    if template is None:
        return
    try:
        text = template.format(**slots)
    except (KeyError, IndexError):
        text = template  # missing slot — just keep the raw template
    world.legacy.journal_fragments.append(
        JournalFragment(
            cycle_recorded=world.legacy.cycles_witnessed + 1,  # the cycle currently being lived
            text=text,
            burned=0.0,
        )
    )
    world.emit(
        Event(
            tick=world.tick_count,
            type="journal_entry",
            subject="khatri",
            detail=text,
            severity="info",
        )
    )


# ---------------------------------------------------------------------------
# Distillation — what the dying cycle teaches the Legacy.
# ---------------------------------------------------------------------------


def distill_legacy_from(world: World) -> None:
    """Apply the dying cycle's lessons to ``world.legacy``.

    Called from ``reset_world`` BEFORE any bulldozing happens. Reads the current
    event buffer + character state. Writes to:

      * ``legacy.building_breach_marks``     (every creature_breach this cycle)
      * ``legacy.personality_drift``         (every char who died — small drift)
      * ``legacy.deaths_by_creature``        (per-character death counter)
      * ``legacy.journal_fragments[*].burned`` (each fragment rolls a survival)

    Pending prophecies do NOT get burned — they're the bridge between cycles.
    """
    cfg = world.config
    rng = world.rng

    # --- Hash marks: scan THIS cycle's events for creature_breach.
    for evt in list(world.events):
        if evt.type == "creature_breach":
            # The subject is the building id (per agents/creatures.py convention).
            bid = evt.subject
            world.legacy.building_breach_marks[bid] = (
                world.legacy.building_breach_marks.get(bid, 0) + 1
            )
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="hash_mark_added",
                    subject=bid,
                    detail=f"hash mark count now {world.legacy.building_breach_marks[bid]}",
                    severity="info",
                )
            )

    # --- Personality drift: every named character who died THIS cycle.
    # We read directly off the agents dict — DEAD characters are still there.
    for agent in list(world.agents.values()):
        kind = getattr(agent, "kind", None)
        # Match only named characters by kind.value to avoid an enum import dance.
        if kind is None or getattr(kind, "value", "") != "character":
            continue
        status_val = getattr(getattr(agent, "status", None), "value", None)
        if status_val != "DEAD":
            continue
        name = getattr(agent, "name", agent.id)
        drift = world.legacy.personality_drift.setdefault(name, {})
        # Trauma rules: a creature death raises paranoid + drops brave;
        # an irrational-act death raises devout (the show's logic).
        cause = getattr(agent, "death_cause", "creature")
        if cause == "creature":
            drift["paranoid"] = drift.get("paranoid", 0.0) + cfg.personality_drift_rate
            drift["brave"] = drift.get("brave", 0.0) - cfg.personality_drift_rate * 0.5
            world.legacy.deaths_by_creature[name] = world.legacy.deaths_by_creature.get(name, 0) + 1
        else:
            drift["devout"] = drift.get("devout", 0.0) + cfg.personality_drift_rate
            drift["paranoid"] = drift.get("paranoid", 0.0) + cfg.personality_drift_rate * 0.3
        # Cap drift magnitudes — personalities don't pendulum past +/- 0.4.
        for trait, v in list(drift.items()):
            drift[trait] = max(-0.4, min(0.4, v))
        world.emit(
            Event(
                tick=world.tick_count,
                type="personality_drift",
                subject=name,
                detail=f"drift now {drift}",
                severity="info",
            )
        )

    # --- Journal fragment survival: each pristine fragment rolls.
    survived: List[JournalFragment] = []
    for frag in world.legacy.journal_fragments:
        # Fragments already burned past 0.85 are too far gone — drop them.
        if frag.burned > 0.85:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="journal_page_burns",
                    subject="khatri",
                    detail=f"page from cycle {frag.cycle_recorded} crumbled to ash",
                    severity="info",
                )
            )
            continue
        if rng.random() <= cfg.journal_fragment_survival_prob:
            # Survived but partially burned.
            frag.burned = min(1.0, frag.burned + rng.uniform(0.05, 0.2))
            survived.append(frag)
        else:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="journal_page_burns",
                    subject="khatri",
                    detail=f"page from cycle {frag.cycle_recorded} lost to the wipe",
                    severity="info",
                )
            )
    # Cap to last 40 fragments overall so the legacy doesn't grow unboundedly.
    world.legacy.journal_fragments = survived[-40:]
