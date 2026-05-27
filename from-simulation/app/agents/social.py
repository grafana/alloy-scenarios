"""
Social rituals: meetings, conversations, arguments.

Agent B owns this module. It is invoked by ``characters.tick_societies(world)``
once per simulation tick. Three things happen here:

1. **Pending meetings** — gather attendees, run a 20-tick deliberation, sample
   a ``MeetingOutcome`` weighted by attendees' personality, and emit it.
2. **Opportunistic conversations** — during DAY, when two compatible characters
   are within 30 px, pair them into ``State.CONVERSING`` for a few ticks.
3. **Imposter suspicion** — when any character's awareness of a yellow-touched
   NPC crosses ``AWARENESS_TRIGGER``, propose a meeting; voting tallies the
   attendees' guilt scores and reflects the verdict in the outcome payload.

Meeting outcomes are written into ``world.meeting_outcomes`` — Agent C reads
the ``imposter_suspicion`` ones, Agent A reads the ``food_supply`` ones (to
flip ``world.expedition_authorised``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from contracts import (
    Event,
    MeetingOutcome,
    Phase,
    Role,
    State,
    Status,
    World,
)

from agents.characters import Character


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MEETING_DURATION_TICKS = 20
ARGUE_DURATION_TICKS = 6
CONVERSATION_DURATION_TICKS = 10
CONVERSATION_RADIUS = 30.0
AWARENESS_TRIGGER = 5.0


# ---------------------------------------------------------------------------
# Pending meeting bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class _PendingMeeting:
    topic: str
    venue_id: str
    caller_id: str
    started_tick: int
    deadline_tick: int
    attendees: List[str] = field(default_factory=list)
    payload: Dict[str, object] = field(default_factory=dict)
    resolved: bool = False


def _get_pendings(world: World) -> List[_PendingMeeting]:
    """Lazily attach the pending-meeting list to the world."""
    p = getattr(world, "_pending_meetings", None)
    if p is None:
        p = []
        world._pending_meetings = p  # type: ignore[attr-defined]
    return p


def _get_pairings(world: World) -> Dict[str, Tuple[str, int]]:
    """Lazily attach active conversation pairings: id -> (partner, until_tick)."""
    p = getattr(world, "_conversation_pairs", None)
    if p is None:
        p = {}
        world._conversation_pairs = p  # type: ignore[attr-defined]
    return p


def _get_awareness_cooldowns(world: World) -> Dict[str, int]:
    p = getattr(world, "_awareness_cooldowns", None)
    if p is None:
        p = {}
        world._awareness_cooldowns = p  # type: ignore[attr-defined]
    return p


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


# Role-pair compatibility hints — symmetric, default 1.0.
_ROLE_COMPAT: Dict[frozenset, float] = {
    frozenset({Role.SHERIFF, Role.DEPUTY}): 1.8,
    frozenset({Role.SHERIFF, Role.LEADER_COLONY}): 1.4,
    frozenset({Role.PRIEST, Role.SEER}): 1.6,
    frozenset({Role.PRIEST, Role.CARETAKER}): 1.5,
    frozenset({Role.CARETAKER, Role.CHILD}): 1.7,
    frozenset({Role.ENGINEER, Role.SHERIFF}): 1.3,
    frozenset({Role.LEADER_COLONY, Role.BRIDGE}): 1.4,
    frozenset({Role.BRIDGE, Role.SHERIFF}): 1.3,
    frozenset({Role.INVESTIGATOR, Role.SEER}): 1.4,
    frozenset({Role.INVESTIGATOR, Role.LEADER_COLONY}): 0.7,
}


def compatibility(a: Character, b: Character) -> float:
    """Score how likely two characters are to strike up a conversation."""
    if a is b:
        return 0.0
    base = _ROLE_COMPAT.get(frozenset({a.role, b.role}), 1.0)
    social = 0.5 * (a.personality.get("social", 0.5) + b.personality.get("social", 0.5))
    # Paranoia depresses social inclination.
    paranoia = 0.5 * (a.personality.get("paranoid", 0.5) + b.personality.get("paranoid", 0.5))
    return base * (0.4 + 1.2 * social) * (1.1 - 0.5 * paranoia)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def propose_meeting(
    world: World,
    caller_id: str,
    topic: str,
    venue_id: str,
    payload: Optional[Dict[str, object]] = None,
) -> Optional[_PendingMeeting]:
    """Schedule a meeting. Returns the pending record or None if invalid."""
    if caller_id not in world.agents:
        return None
    if venue_id not in world.buildings:
        venue_id = "church"
    pendings = _get_pendings(world)
    # Don't double-propose the same topic.
    for p in pendings:
        if p.topic == topic and not p.resolved:
            return p
    pm = _PendingMeeting(
        topic=topic,
        venue_id=venue_id,
        caller_id=caller_id,
        started_tick=world.tick_count,
        deadline_tick=world.tick_count + MEETING_DURATION_TICKS,
        payload=dict(payload or {}),
    )
    pendings.append(pm)
    world.emit(Event(
        tick=world.tick_count, type="meeting_proposed",
        subject=caller_id, detail=f"{topic} @ {venue_id}",
    ))
    return pm


# ---------------------------------------------------------------------------
# Main tick
# ---------------------------------------------------------------------------


def tick_social(world: World) -> None:
    _check_awareness_triggers(world)
    _drive_pending_meetings(world)
    _drive_conversations(world)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _characters(world: World) -> List[Character]:
    return [a for a in world.agents.values()
            if isinstance(a, Character) and a.status == Status.ACTIVE]


def _check_awareness_triggers(world: World) -> None:
    cooldowns = _get_awareness_cooldowns(world)
    for ch in _characters(world):
        if not ch.awareness:
            continue
        # Find the most suspicious NPC currently flagged for this character.
        suspect, score = max(ch.awareness.items(), key=lambda kv: kv[1])
        if score < AWARENESS_TRIGGER:
            continue
        # Cooldown so we don't spam meetings.
        last = cooldowns.get(suspect, -10_000)
        if world.tick_count - last < 300:
            continue
        cooldowns[suspect] = world.tick_count
        propose_meeting(
            world,
            caller_id=ch.id,
            topic="imposter_suspicion",
            venue_id="church",
            payload={"accused_npc_id": suspect},
        )


def _attend_roll(world: World, ch: Character, topic: str) -> bool:
    if ch.status != Status.ACTIVE:
        return False
    if ch.state in (State.SLEEPING, State.EXPEDITION, State.HYPNOTIZED, State.IRRATIONAL):
        return False
    social = ch.personality.get("social", 0.5)
    leader = ch.personality.get("leader", 0.3)
    base = 0.35 + 0.5 * social + 0.25 * leader
    # Imposter suspicion pulls in the paranoid hard.
    if topic == "imposter_suspicion":
        base += 0.4 * ch.personality.get("paranoid", 0.5)
    if topic == "food_supply":
        base += 0.3 * ch.personality.get("leader", 0.3)
    return world.rng.random() < min(0.95, base)


def _pin_to_meeting(world: World, ch: Character, until_tick: int, venue_id: str) -> None:
    ch.state = State.MEETING
    ch.state_since_tick = world.tick_count
    ch.meeting_until_tick = until_tick
    b = world.buildings.get(venue_id)
    if b is not None:
        ch.target = (b.x, b.y)


def _drive_pending_meetings(world: World) -> None:
    pendings = _get_pendings(world)
    for pm in list(pendings):
        if pm.resolved:
            continue
        # Gather attendees the first tick after proposal.
        if not pm.attendees and world.tick_count == pm.started_tick + 1:
            for ch in _characters(world):
                if _attend_roll(world, ch, pm.topic):
                    pm.attendees.append(ch.id)
                    _pin_to_meeting(world, ch, pm.deadline_tick, pm.venue_id)
            # Ensure caller is present.
            caller = world.agents.get(pm.caller_id)
            if isinstance(caller, Character) and caller.id not in pm.attendees:
                pm.attendees.append(caller.id)
                _pin_to_meeting(world, caller, pm.deadline_tick, pm.venue_id)
            if pm.attendees:
                world.emit(Event(
                    tick=world.tick_count, type="meeting_started",
                    subject=pm.caller_id,
                    detail=f"{pm.topic} ({len(pm.attendees)} attending)",
                ))

        # Resolve on deadline.
        if world.tick_count >= pm.deadline_tick:
            _resolve_meeting(world, pm)
            pm.resolved = True

    # Drop resolved meetings to keep the list small.
    world._pending_meetings = [p for p in pendings if not p.resolved]  # type: ignore[attr-defined]


def _resolve_meeting(world: World, pm: _PendingMeeting) -> None:
    attendees = [world.agents[a] for a in pm.attendees if a in world.agents]
    attendees = [a for a in attendees if isinstance(a, Character)]

    if not attendees:
        outcome = MeetingOutcome(
            tick=world.tick_count, topic=pm.topic, venue_id=pm.venue_id,
            attendees=[], decision="inconclusive", payload=dict(pm.payload),
        )
        world.meeting_outcomes.append(outcome)
        world.emit(Event(
            tick=world.tick_count, type="meeting_outcome",
            subject=pm.caller_id, detail=f"{pm.topic}: inconclusive (no quorum)",
        ))
        return

    payload = dict(pm.payload)
    decision = "inconclusive"

    if pm.topic == "imposter_suspicion":
        accused = payload.get("accused_npc_id")
        # Tally guilt scores: each attendee contributes their awareness of the accused.
        guilt_yes = 0.0
        guilt_no = 0.0
        for a in attendees:
            score = float(a.awareness.get(accused, 0.0))
            paranoid = a.personality.get("paranoid", 0.5)
            # Paranoid attendees tip toward guilty even with thin evidence.
            vote_yes = score + (paranoid - 0.5) * 2.0
            if vote_yes > 0:
                guilt_yes += vote_yes
            else:
                guilt_no += -vote_yes + 0.5
        guilty = guilt_yes > guilt_no
        decision = "agree" if guilty else "disagree"
        payload["guilty"] = bool(guilty)
        if accused is not None:
            payload["accused_npc_id"] = accused
        world.emit(Event(
            tick=world.tick_count, type="imposter_vote",
            subject=pm.caller_id,
            detail=f"accused={accused} guilty={guilty}",
            severity="warn" if guilty else "info",
        ))
    elif pm.topic == "food_supply":
        # Leaders + brave folk push for expedition.
        push = sum(0.5 * a.personality.get("leader", 0.3)
                   + 0.5 * a.personality.get("brave", 0.4)
                   for a in attendees)
        threshold = max(1.0, 0.5 * len(attendees))
        agree = push >= threshold
        decision = "agree" if agree else "disagree"
        if agree:
            world.expedition_authorised = True
    elif pm.topic == "creature_breach_review":
        decision = world.rng.choices(
            ["agree", "disagree", "inconclusive"], weights=[0.5, 0.3, 0.2], k=1,
        )[0]
    else:
        # Generic resolution — weighted by attendees' leader / social vibe.
        agree_w = sum(0.5 + 0.5 * a.personality.get("leader", 0.3) for a in attendees)
        disagree_w = sum(0.3 + 0.6 * a.personality.get("paranoid", 0.5) for a in attendees)
        if agree_w > disagree_w * 1.2:
            decision = "agree"
        elif disagree_w > agree_w * 1.2:
            decision = "disagree"
        else:
            decision = "inconclusive"

    outcome = MeetingOutcome(
        tick=world.tick_count, topic=pm.topic, venue_id=pm.venue_id,
        attendees=[a.id for a in attendees], decision=decision, payload=payload,
    )
    world.meeting_outcomes.append(outcome)
    world.emit(Event(
        tick=world.tick_count, type="meeting_outcome",
        subject=pm.caller_id, detail=f"{pm.topic}: {decision}",
        severity="warn" if pm.topic == "imposter_suspicion" else "info",
    ))

    # Release attendees from State.MEETING; on disagreement, flip a few to ARGUING.
    if decision == "disagree" and len(attendees) >= 2:
        n_arg = min(2, len(attendees))
        arguers = world.rng.sample(attendees, n_arg)
    else:
        arguers = []
    arg_set = {a.id for a in arguers}
    for a in attendees:
        a.meeting_until_tick = 0
        if a.id in arg_set:
            a.state = State.ARGUING
            a.state_since_tick = world.tick_count
            a.arguing_until_tick = world.tick_count + ARGUE_DURATION_TICKS
            a.fear = min(100.0, a.fear + 8.0)
            a.sanity = max(0.0, a.sanity - 3.0)
            world.emit(Event(
                tick=world.tick_count, type="argument",
                subject=a.id, detail=f"after {pm.topic}",
            ))
        else:
            a.state = State.WANDERING
            a.state_since_tick = world.tick_count
            a.target = None

    # Clear awareness for the accused once a verdict has landed.
    if pm.topic == "imposter_suspicion":
        accused = payload.get("accused_npc_id")
        if accused is not None:
            for a in attendees:
                a.awareness.pop(accused, None)


# ---------------------------------------------------------------------------
# Opportunistic conversations
# ---------------------------------------------------------------------------


def _drive_conversations(world: World) -> None:
    pairs = _get_pairings(world)

    # First, expire pairings whose deadline passed.
    expired: List[str] = []
    for cid, (partner, until) in pairs.items():
        if world.tick_count >= until:
            expired.append(cid)
    for cid in expired:
        partner, _ = pairs.pop(cid)
        pairs.pop(partner, None)
        a = world.agents.get(cid)
        b = world.agents.get(partner)
        if isinstance(a, Character) and a.state == State.CONVERSING:
            a.state = State.WANDERING
            a.conversation_partner = None
        if isinstance(b, Character) and b.state == State.CONVERSING:
            b.state = State.WANDERING
            b.conversation_partner = None

    # Only spawn new conversations during DAY phase.
    if world.time.phase != Phase.DAY:
        return

    chars = [
        c for c in _characters(world)
        if c.id not in pairs
        and c.state not in (State.MEETING, State.ARGUING, State.CONVERSING,
                            State.SLEEPING, State.EXPEDITION, State.HYPNOTIZED,
                            State.IRRATIONAL, State.FLEEING)
    ]
    # Limit work: O(n^2) over 10 characters is fine.
    for i in range(len(chars)):
        a = chars[i]
        if a.id in pairs:
            continue
        for j in range(i + 1, len(chars)):
            b = chars[j]
            if b.id in pairs:
                continue
            d = math.hypot(a.x - b.x, a.y - b.y)
            if d > CONVERSATION_RADIUS:
                continue
            score = compatibility(a, b)
            if world.rng.random() < 0.05 * score:
                until = world.tick_count + CONVERSATION_DURATION_TICKS
                pairs[a.id] = (b.id, until)
                pairs[b.id] = (a.id, until)
                a.state = State.CONVERSING
                b.state = State.CONVERSING
                a.conversation_partner = b.id
                b.conversation_partner = a.id
                a.state_since_tick = world.tick_count
                b.state_since_tick = world.tick_count
                # Seers/caretakers chatting with supernaturals soften the sanity hit.
                if a.role in (Role.SEER, Role.CARETAKER) or b.role in (Role.SEER, Role.CARETAKER):
                    if world.supernaturals:
                        a.sanity = min(100.0, a.sanity + 1.0)
                        b.sanity = min(100.0, b.sanity + 1.0)
                world.emit(Event(
                    tick=world.tick_count, type="conversation",
                    subject=a.id, detail=f"with {b.id}",
                ))
                break
