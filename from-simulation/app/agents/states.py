"""
Time-of-day weighted state transition table.

Every character + NPC FSM samples next-state candidates from this table,
weighted by ``base_weight * tod_multipliers[current_phase]``. A multiplier of
``0.0`` effectively bans the transition during that phase (e.g. SLEEPING is
gated to NIGHT, FARMING to DAY).

Wire-up:
    candidates = TRANSITION_TABLE[current_state]
    weights = [base * tod.get(phase, 1.0) for (_, base, tod) in candidates]
    next_state = rng.choices([next for (next, _, _) in candidates], weights)[0]

This is engine-shaped scaffolding; Agents B/C may *augment* by composing extra
context (role gates, building proximity, fear thresholds) on top — they don't
edit this table.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from contracts import Phase, State


# A transition is (next_state, base_weight, per-phase multipliers).
Transition = Tuple[State, float, Dict[Phase, float]]


# --- Phase multiplier shortcuts -------------------------------------------------

_DAY_ONLY: Dict[Phase, float] = {Phase.DAY: 1.0, Phase.DUSK: 0.2, Phase.NIGHT: 0.0, Phase.DAWN: 0.4}
_NIGHT_ONLY: Dict[Phase, float] = {Phase.DAY: 0.0, Phase.DUSK: 0.4, Phase.NIGHT: 1.0, Phase.DAWN: 0.2}
_DUSK_NIGHT: Dict[Phase, float] = {Phase.DAY: 0.1, Phase.DUSK: 1.0, Phase.NIGHT: 1.0, Phase.DAWN: 0.2}
_ANYTIME: Dict[Phase, float] = {Phase.DAY: 1.0, Phase.DUSK: 1.0, Phase.NIGHT: 1.0, Phase.DAWN: 1.0}
_BIASED_DAY: Dict[Phase, float] = {Phase.DAY: 1.0, Phase.DUSK: 0.6, Phase.NIGHT: 0.2, Phase.DAWN: 0.6}
_BIASED_NIGHT: Dict[Phase, float] = {Phase.DAY: 0.3, Phase.DUSK: 0.7, Phase.NIGHT: 1.0, Phase.DAWN: 0.5}


# --- The transition table -------------------------------------------------------
#
# Notes on coverage:
#   * Every "solo" character state has a self-stay edge (return to WANDERING /
#     current state) so the FSM never deadlocks if all weighted edges happen to
#     score 0 for the current phase.
#   * Multi-agent states (MEETING/ARGUING/CONVERSING/MEDIATING) decay back to
#     WANDERING — the social driver in Agent B promotes them externally.
#   * Creature/supernatural sub-FSMs are NOT in this table — they're managed
#     inside agents/creatures.py and agents/supernatural.py respectively.
#   * IRRATIONAL is a terminal "stuck" state from this table's POV — exit is
#     driven by agents/fear.py outcome sampling, not by weighted transitions.

TRANSITION_TABLE: Dict[State, List[Transition]] = {
    State.SLEEPING: [
        (State.SLEEPING, 6.0, _NIGHT_ONLY),
        (State.WANDERING, 2.0, _BIASED_DAY),
        (State.EATING, 1.5, _BIASED_DAY),
        (State.FARMING, 1.0, _DAY_ONLY),
    ],
    State.EATING: [
        (State.WANDERING, 2.0, _ANYTIME),
        (State.GOSSIPING, 1.5, _BIASED_DAY),
        (State.SHELTERING, 1.0, _DUSK_NIGHT),
        (State.FARMING, 1.0, _DAY_ONLY),
    ],
    State.SCAVENGING: [
        (State.SCAVENGING, 2.0, _BIASED_DAY),
        (State.WANDERING, 1.5, _ANYTIME),
        (State.EATING, 1.0, _ANYTIME),
        (State.SHELTERING, 1.0, _DUSK_NIGHT),
    ],
    State.FARMING: [
        (State.FARMING, 4.0, _DAY_ONLY),
        (State.EATING, 1.5, _ANYTIME),
        (State.WANDERING, 1.0, _ANYTIME),
        (State.SHELTERING, 1.5, _DUSK_NIGHT),
        # v7 — pivot to FORAGING when the barn is down. The weight here is
        # baseline; characters.py applies an additional 3× boost via the
        # food_shortage / barn_destroyed_until_tick checks.
        (State.FORAGING, 1.2, _DAY_ONLY),
    ],
    State.GOSSIPING: [
        (State.GOSSIPING, 2.0, _DAY_ONLY),
        (State.CONVERSING, 1.5, _DAY_ONLY),
        (State.WANDERING, 2.0, _ANYTIME),
        (State.MEETING, 0.5, _BIASED_DAY),
    ],
    State.PATROLLING: [
        (State.PATROLLING, 3.0, _BIASED_NIGHT),
        (State.WANDERING, 1.0, _ANYTIME),
        (State.INVESTIGATING, 1.5, _DUSK_NIGHT),
        (State.SHELTERING, 0.5, _NIGHT_ONLY),
    ],
    State.SHELTERING: [
        (State.SHELTERING, 5.0, _NIGHT_ONLY),
        (State.SLEEPING, 2.0, _NIGHT_ONLY),
        (State.PRAYING, 1.0, _DUSK_NIGHT),
        (State.WANDERING, 2.0, _BIASED_DAY),
    ],
    State.PRAYING: [
        (State.PRAYING, 1.5, _DUSK_NIGHT),
        (State.WANDERING, 2.0, _ANYTIME),
        (State.SHELTERING, 1.0, _DUSK_NIGHT),
        (State.MOURNING, 0.5, _ANYTIME),
    ],
    State.MEDICAL_CARE: [
        (State.MEDICAL_CARE, 3.0, _ANYTIME),
        (State.WANDERING, 1.0, _ANYTIME),
        (State.CARETAKING, 1.0, _ANYTIME),
    ],
    State.MOURNING: [
        (State.MOURNING, 2.0, _ANYTIME),
        (State.PRAYING, 1.5, _ANYTIME),
        (State.WANDERING, 1.5, _BIASED_DAY),
        (State.GOSSIPING, 0.5, _DAY_ONLY),
    ],
    State.REPAIRING: [
        (State.REPAIRING, 2.5, _DAY_ONLY),
        (State.WANDERING, 1.0, _ANYTIME),
        (State.EATING, 0.5, _ANYTIME),
    ],
    State.WANDERING: [
        # The "hub" state — most transitions originate here.
        (State.WANDERING, 1.0, _ANYTIME),
        (State.EATING, 1.0, _BIASED_DAY),
        (State.GOSSIPING, 1.0, _DAY_ONLY),
        (State.FARMING, 1.0, _DAY_ONLY),
        (State.SCAVENGING, 0.8, _BIASED_DAY),
        (State.PATROLLING, 0.8, _BIASED_NIGHT),
        (State.SHELTERING, 1.2, _DUSK_NIGHT),
        (State.SLEEPING, 1.5, _NIGHT_ONLY),
        (State.PRAYING, 0.4, _ANYTIME),
        (State.INVESTIGATING, 0.3, _ANYTIME),
        (State.REPAIRING, 0.4, _DAY_ONLY),
        (State.PLAYING, 0.4, _DAY_ONLY),
        (State.CONVERSING, 0.5, _BIASED_DAY),
        # v6 — wanderers occasionally drift into the caves on their own.
        # Lower base than the INVESTIGATING edge; same DAY-only gating.
        (State.EXPLORING_CAVES, 0.4, _DAY_ONLY),
    ],
    State.FLEEING: [
        # Fleeing decays back into shelter / wander when fear subsides.
        (State.SHELTERING, 3.0, _ANYTIME),
        (State.WANDERING, 1.0, _BIASED_DAY),
        (State.FLEEING, 1.5, _DUSK_NIGHT),
    ],
    State.HYPNOTIZED: [
        # Hypnotised agents stay put until creatures.py releases them.
        (State.HYPNOTIZED, 10.0, _ANYTIME),
        (State.WANDERING, 0.2, _BIASED_DAY),
    ],
    State.INVESTIGATING: [
        (State.INVESTIGATING, 0.7, _ANYTIME),
        (State.WANDERING, 1.0, _ANYTIME),
        (State.PATROLLING, 0.8, _BIASED_NIGHT),
        (State.MEETING, 0.4, _BIASED_DAY),
        # v6 — cave exploration. DAY-only; INVESTIGATOR/SEER get a role bonus
        # on top of this in characters.py via ROLE_PRIORITY. Bumped to 3.0 so
        # the role bonus (2×) gives ~6.0 vs INVESTIGATING's ~1.4 — Jade and
        # Sara actually leave the village for the caves rather than just
        # picking nearby buildings.
        (State.EXPLORING_CAVES, 3.0, _DAY_ONLY),
    ],
    State.PLAYING: [
        (State.PLAYING, 2.0, _DAY_ONLY),
        (State.WANDERING, 1.5, _BIASED_DAY),
        (State.SHELTERING, 1.0, _DUSK_NIGHT),
    ],
    State.EXPEDITION: [
        # Owned externally by the expedition slice; included for completeness.
        (State.EXPEDITION, 5.0, _ANYTIME),
        (State.WANDERING, 0.2, _BIASED_DAY),
    ],
    State.CARETAKING: [
        (State.CARETAKING, 2.0, _ANYTIME),
        (State.MEDICAL_CARE, 1.0, _ANYTIME),
        (State.WANDERING, 1.0, _ANYTIME),
    ],
    State.IRRATIONAL: [
        # Driven externally by fear.py; offer a thin escape edge.
        (State.IRRATIONAL, 4.0, _ANYTIME),
        (State.WANDERING, 0.3, _BIASED_DAY),
    ],
    State.CARRYING_BOX: [
        # v4 — Music Box carriers rarely transition; drop is driven by
        # music_box.py's compulsion check. Self-stay dominates.
        (State.CARRYING_BOX, 10.0, _ANYTIME),
        (State.WANDERING, 0.2, _BIASED_DAY),
    ],
    State.MEETING: [
        (State.MEETING, 3.0, _BIASED_DAY),
        (State.WANDERING, 1.0, _ANYTIME),
        (State.ARGUING, 0.5, _BIASED_DAY),
    ],
    State.ARGUING: [
        (State.WANDERING, 2.0, _ANYTIME),
        (State.MEDIATING, 0.8, _BIASED_DAY),
        (State.MEETING, 0.5, _BIASED_DAY),
    ],
    State.CONVERSING: [
        (State.WANDERING, 1.5, _ANYTIME),
        (State.GOSSIPING, 1.0, _DAY_ONLY),
        (State.CONVERSING, 0.8, _ANYTIME),
    ],
    State.MEDIATING: [
        (State.WANDERING, 2.0, _ANYTIME),
        (State.MEETING, 0.8, _BIASED_DAY),
        (State.CONVERSING, 0.6, _BIASED_DAY),
    ],
    # NPC mini-FSM (just two states — see agents/npcs.py for richer logic).
    State.WORKING: [
        (State.WORKING, 3.0, _DAY_ONLY),
        (State.SOCIALIZING, 1.0, _DAY_ONLY),
        (State.WANDERING, 0.5, _ANYTIME),
        (State.SHELTERING, 1.0, _DUSK_NIGHT),
        (State.SLEEPING, 1.5, _NIGHT_ONLY),
    ],
    State.SOCIALIZING: [
        (State.SOCIALIZING, 2.0, _DAY_ONLY),
        (State.WORKING, 1.5, _DAY_ONLY),
        (State.GOSSIPING, 1.0, _DAY_ONLY),
        (State.SHELTERING, 1.0, _DUSK_NIGHT),
    ],
    # v2 — dreaming decays back to sleeping; the engine's dreams.tick owns
    # the actual lifecycle but we register a transition so the generic FSM
    # never deadlocks if a character is sampled mid-dream.
    State.DREAMING: [
        (State.SLEEPING, 4.0, _ANYTIME),
        (State.DREAMING, 1.0, _ANYTIME),
    ],
    # v6 — cave exploration. caves.py drives the actual lifecycle (progress
    # counter + outcome roll); these edges only matter if a character is
    # sampled mid-exploration before caves.py has run its outcome.
    State.EXPLORING_CAVES: [
        # Heavily sticky — caves.py owns the exit. Otherwise the FSM can
        # bounce the character out before they walk ~150 px to the entrance.
        (State.EXPLORING_CAVES, 20.0, _DAY_ONLY),
        (State.WANDERING, 0.2, _BIASED_DAY),
        (State.FLEEING, 0.5, _ANYTIME),
    ],
    # v7 — FORAGING. characters.py owns the lifecycle (walking to a forage
    # zone, gathering for FORAGE_TICKS_TO_GATHER, returning food). Sticky like
    # EXPLORING_CAVES so the FSM doesn't pull the forager off mid-trip.
    State.FORAGING: [
        (State.FORAGING, 20.0, _DAY_ONLY),
        (State.WANDERING, 0.3, _BIASED_DAY),
        (State.FLEEING, 0.5, _ANYTIME),
    ],
    # v6 — CALLED is sticky. The hard-override in characters.py pins us to it
    # while ``world.lighthouse_called`` names this character, but we still
    # register edges so the FSM doesn't deadlock if the call is cleared.
    State.CALLED: [
        (State.CALLED, 10.0, _ANYTIME),
        (State.WANDERING, 0.2, _BIASED_DAY),
    ],
}
