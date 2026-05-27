"""
Dreams + prophecies — Agent A v2 engine hook.

When a sanity-impaired character sleeps, this module rolls dreams. A dream
runs for a fixed number of ticks, periodically emitting cryptic ``dream_line``
events and queueing matching ``Prophecy`` entries on ``world.legacy``.

A separate pass, ``fire_due_prophecies(world)``, scans the legacy each tick
and fires any prophecy whose ``fires_at_cycle`` has come due and whose
trigger condition is currently satisfied in the world. Triggers are derived
from the prophecy line via simple substring matching — over-firing is fine,
the show is allusive and we want resonance over precision.

Entry points wired by ``simulation._do_tick``:
    tick_dreams(world)         — between agent ticks and society tick.
    fire_due_prophecies(world) — at the tail of the tick, before metrics.
"""

from __future__ import annotations

from typing import List, Optional

from contracts import (
    Dream,
    Event,
    Prophecy,
    State,
    Status,
    World,
)


# ---------------------------------------------------------------------------
# Dream content
# ---------------------------------------------------------------------------

# Pool of cryptic prophetic one-liners. The Boy/Anghkooey/self visitor decides
# which subset feels appropriate; for now the entire pool is shared but the
# visitor is recorded on the Dream so the UI can flavour the rendering.
_DREAM_LINES: List[str] = [
    "The Sheriff will sleep through the door.",
    "There is a way the Lighthouse opens twice.",
    "The yellow one wore a familiar face.",
    "A bus will come, and someone on it knows your name.",
    "The first creature this cycle will not be the last.",
    "Khatri prays at dawn, and dawn does not answer.",
    "The forest learns the shape of the houses.",
    "The boy in white walks where you cannot follow.",
    "Count the doors. One of them is new.",
    "The road bends back. So do the years.",
    "What burned in the journal still burns.",
    "Sara hears the chant before any of you.",
    "A child will lead the wrong way home.",
    "The talisman remembers what we have forgotten.",
    "The dead come back wearing the wrong skin.",
    "There is a tree that opens at the wrong hour.",
]


# Ticks between successive dream lines within an active dream.
_LINE_CADENCE_TICKS = 6


# ---------------------------------------------------------------------------
# Trigger derivation — sloppy substring matching, on purpose.
# ---------------------------------------------------------------------------


def _derive_trigger(line: str) -> str:
    """Pick a canonical pseudo-event key for this prophecy line.

    Loose substring match — biased toward over-firing so dreams feel like
    they "come true" often. Order matters: first match wins.
    """
    low = line.lower()
    if "creature" in low or "forest learns" in low:
        return "first_creature_spawn"
    if "lighthouse" in low:
        return "lighthouse_enter"
    if "yellow" in low or "imposter" in low:
        return "yellow_appearance"
    if "bus" in low or "comes" in low:
        return "bus_arrival"
    if "khatri" in low or "prays" in low or "dawn" in low:
        return "khatri_prays_dawn"
    if "boy" in low or "white" in low:
        return "boy_in_white"
    if "tree" in low or "portal" in low or "chant" in low:
        return "faraway_portal"
    if "journal" in low or "burned" in low or "remembers" in low:
        return "journal_page_burns"
    if "dead" in low or "back" in low or "home" in low:
        return "homecoming"
    if "door" in low:
        return "creature_breach"
    return "any"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _character_for_id(world: World, char_id: str):
    return world.agents.get(char_id)


def _already_dreaming(world: World, char_id: str) -> bool:
    return any(d.character_id == char_id for d in world.active_dreams)


_BALLERINA_LINES: List[str] = [
    "The ballerina turned and her mouth was full of worms.",
    "She danced, and the music wound back to its beginning.",
    "Twirl me, said the ballerina.",
    "The cicadas were already inside the dream.",
    "She told me the rhyme was older than the town.",
]


def _pick_visitor(world: World) -> str:
    # When the Music Box is awake, the ballerina haunts dreams alongside the
    # boy/anghkooey/self options. She gets a flat 50% slice of the pool when
    # active; otherwise she's 0%.
    ballerina_active = getattr(world, "music_box_phase", "DORMANT") != "DORMANT"
    weights = [
        ("boy_in_white", 0.45),
        ("anghkooey", 0.35),
        ("self", 0.20),
    ]
    if ballerina_active:
        # Renormalise the original three to share the remaining 50%, ballerina = 50%.
        weights = [
            ("boy_in_white", 0.225),
            ("anghkooey", 0.175),
            ("self", 0.100),
            ("ballerina", 0.500),
        ]
    options = [v for v, _ in weights]
    probs = [w for _, w in weights]
    return world.rng.choices(options, weights=probs, k=1)[0]


def _generate_lines(world: World, count: int, visitor: str = "self") -> List[str]:
    # Choose ``count`` distinct lines from the pool. Ballerina has her own pool.
    if visitor == "ballerina":
        pool = list(_BALLERINA_LINES)
    else:
        pool = list(_DREAM_LINES)
    world.rng.shuffle(pool)
    return pool[: max(1, count)]


# ---------------------------------------------------------------------------
# Public: dream lifecycle tick
# ---------------------------------------------------------------------------


def tick_dreams(world: World) -> None:
    """Drive dream begin/line/end events and queue prophecies.

    Called once per sim tick from ``simulation._do_tick`` — after the agent
    ticks (so sleeping characters have already been processed by their own
    FSM this tick) and before ``tick_societies`` (so B observes the
    DREAMING transitions when it runs).
    """
    cfg = world.config
    rng = world.rng

    # 1) Roll new dreams for sleeping low-sanity characters not already dreaming.
    for agent in list(world.agents.values()):
        state = getattr(agent, "state", None)
        if state != State.SLEEPING:
            continue
        status = getattr(agent, "status", Status.ACTIVE)
        if status != Status.ACTIVE:
            continue
        sanity = float(getattr(agent, "sanity", 100.0))
        if sanity >= cfg.dream_trigger_sanity_threshold:
            continue
        if _already_dreaming(world, agent.id):
            continue
        if rng.random() >= cfg.dream_trigger_prob:
            continue

        visitor = _pick_visitor(world)
        n_lines = rng.randint(2, 4)
        lines = _generate_lines(world, n_lines, visitor)
        dream = Dream(
            character_id=agent.id,
            started_at_tick=world.tick_count,
            duration=int(cfg.dream_duration_ticks),
            lines=lines,
            visitor=visitor,
        )
        world.active_dreams.append(dream)
        # Flip the character into DREAMING — Agent B watches for this.
        try:
            setattr(agent, "state", State.DREAMING)
        except Exception:
            pass
        world.emit(
            Event(
                tick=world.tick_count,
                type="dream_begin",
                subject=agent.id,
                detail=f"{visitor} visits ({n_lines} lines)",
                severity="info",
            )
        )
        if visitor == "ballerina":
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="ballerina_vision",
                    subject=agent.id,
                    detail=f"the ballerina enters {agent.id}'s dream",
                    severity="warn",
                )
            )

    # 2) Progress each active dream: emit the next line on cadence, end on
    #    duration. Iterate over a snapshot since we may mutate the list.
    cur_cycle = world.legacy.cycles_witnessed + 1
    for dream in list(world.active_dreams):
        elapsed = world.tick_count - dream.started_at_tick

        # End-of-dream takedown.
        if elapsed >= dream.duration:
            char = _character_for_id(world, dream.character_id)
            if char is not None:
                # Only restore if they're still mid-dream — defensive against
                # B/C having already moved them on (e.g. died in their sleep).
                if getattr(char, "state", None) == State.DREAMING:
                    try:
                        setattr(char, "state", State.SLEEPING)
                    except Exception:
                        pass
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="dream_end",
                    subject=dream.character_id,
                    detail=f"{dream.visitor} dream ends",
                    severity="info",
                )
            )
            try:
                world.active_dreams.remove(dream)
            except ValueError:
                pass
            continue

        # Mid-dream: emit next queued line every ~6 ticks. We use the count of
        # lines already spoken (tracked by how many we've popped) — but lines
        # aren't popped, we just index by elapsed // cadence.
        line_idx = elapsed // _LINE_CADENCE_TICKS
        # Only fire on the exact tick the new index opens up, and only if the
        # dream still has a line at that index.
        if elapsed > 0 and elapsed % _LINE_CADENCE_TICKS == 0 and line_idx <= len(dream.lines):
            idx = line_idx - 1 if line_idx > 0 else 0
            if 0 <= idx < len(dream.lines):
                line = dream.lines[idx]
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="dream_line",
                        subject=dream.character_id,
                        detail=line,
                        severity="info",
                    )
                )
                # Queue a prophecy on the legacy. It fires next cycle.
                prophecy = Prophecy(
                    set_at_cycle=cur_cycle,
                    fires_at_cycle=cur_cycle + 1,
                    trigger=_derive_trigger(line),
                    payload=line,
                )
                world.legacy.pending_prophecies.append(prophecy)
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="prophecy_set",
                        subject=dream.character_id,
                        detail=f"[{prophecy.trigger}] {line}",
                        severity="info",
                    )
                )


# ---------------------------------------------------------------------------
# Public: fire prophecies whose moment has come.
# ---------------------------------------------------------------------------


def _creature_spawn_this_tick(world: World) -> bool:
    """Did a creature_spawn event hit the buffer at the current tick?"""
    if world.events is None:
        return False
    for evt in reversed(list(world.events)):
        if evt.tick != world.tick_count:
            return False  # buffer is roughly time-ordered
        if evt.type == "creature_spawn":
            return True
    return False


def _event_type_this_tick(world: World, event_type: str) -> bool:
    if world.events is None:
        return False
    for evt in reversed(list(world.events)):
        if evt.tick != world.tick_count:
            return False
        if evt.type == event_type:
            return True
    return False


def _khatri_praying_at_dawn(world: World) -> bool:
    if world.time.phase.value != "DAWN":
        return False
    for agent in world.agents.values():
        name = (getattr(agent, "name", "") or "").lower()
        if "khatri" not in name:
            continue
        state = getattr(agent, "state", None)
        if state == State.PRAYING:
            return True
    return False


def _trigger_met(world: World, trigger: str) -> bool:
    """Decide whether ``trigger`` is currently satisfied. Loose by design."""
    if trigger == "any":
        return True
    if trigger == "first_creature_spawn":
        return _creature_spawn_this_tick(world)
    if trigger == "khatri_prays_dawn":
        return _khatri_praying_at_dawn(world)
    # All other triggers are direct event types — fire if the event hit this tick.
    return _event_type_this_tick(world, trigger)


def fire_due_prophecies(world: World) -> None:
    """Emit ``prophecy_fired`` for any pending prophecy whose moment has come.

    A prophecy is "due" once ``fires_at_cycle <= current cycle`` AND its
    trigger condition holds in the world this tick. Fired prophecies are
    removed from ``world.legacy.pending_prophecies``.
    """
    cur_cycle = world.legacy.cycles_witnessed + 1
    if not world.legacy.pending_prophecies:
        return

    survivors: List[Prophecy] = []
    for prop in world.legacy.pending_prophecies:
        if prop.fires_at_cycle <= cur_cycle and _trigger_met(world, prop.trigger):
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="prophecy_fired",
                    subject="world",
                    detail=f"[{prop.trigger}] {prop.payload}",
                    severity="warn",
                )
            )
            # Do not retain — it has come true.
            continue
        survivors.append(prop)
    world.legacy.pending_prophecies = survivors
