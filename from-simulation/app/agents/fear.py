"""
Fear propagation + paranormal break outcomes.

Per tick:

  1. Every agent within ~120 px of a creature has their ``fear`` raised, scaled
     by ``1 - brave`` (so brave agents resist). Distance falloff is linear.
  2. Once ``fear > 90``, the agent rolls a per-tick chance to "break". On a
     break we set their state to IRRATIONAL, emit ``paranormal_break``, and
     drop a transient glitch marker (Faraway-Tree-style sprite) at their feet.
  3. An agent who has been IRRATIONAL for ``N`` ticks samples an outcome from
     a small table:
        * unlock_door    — unlock the door of the nearest building
        * run_outside    — wander away from the nearest shelter
        * attack_neighbour — set a nearby agent to INCAPACITATED
        * silent_collapse — set themselves to INCAPACITATED
     The agent stays IRRATIONAL for a few more ticks of "stunned" before
     fear drains.

We never *delete* agents here — we set their ``status`` and let the owner slice
(Agent B for characters, Agent C for NPCs) sweep them up on the next tick.
"""

from __future__ import annotations

from typing import List, Optional

from contracts import Agent, Event, Phase, State, Status, World
from agents.base import distance, nearest
from agents import supernatural as _supernatural


# Tunables
_PROX_RADIUS = 120.0
_FEAR_PER_TICK_AT_ZERO = 6.0    # raw fear gain at point-blank from a creature
_BREAK_THRESHOLD = 90.0
_BREAK_PROB_PER_TICK = 0.05
_IRRATIONAL_OUTCOME_TICKS = 12
_IRRATIONAL_TOTAL_TICKS = 30
_FEAR_DRAIN_AFTER_BREAK = 60.0


def _fear_gain(agent_brave: float, dist_to_creature: float) -> float:
    """Linear falloff inside ``_PROX_RADIUS`` scaled by ``(1 - brave)``."""
    if dist_to_creature >= _PROX_RADIUS:
        return 0.0
    falloff = 1.0 - (dist_to_creature / _PROX_RADIUS)
    bravery = max(0.0, min(1.0, float(agent_brave)))
    return _FEAR_PER_TICK_AT_ZERO * falloff * (1.0 - bravery)


def _eligible_agents(world: World) -> List[Agent]:
    """Active, non-dead agents who can feel fear."""
    out: List[Agent] = []
    for a in world.agents.values():
        status = getattr(a, "status", Status.ACTIVE)
        if status in (Status.DEAD, Status.INCAPACITATED, Status.ABSENT):
            continue
        out.append(a)
    return out


def _maybe_break(world: World, agent: Agent) -> None:
    """Roll a paranormal break. On hit, switch agent to IRRATIONAL + emit."""
    if getattr(agent, "state", None) == State.IRRATIONAL:
        return
    fear = float(getattr(agent, "fear", 0.0))
    if fear <= _BREAK_THRESHOLD:
        return
    if world.rng.random() >= _BREAK_PROB_PER_TICK:
        return
    setattr(agent, "state", State.IRRATIONAL)
    setattr(agent, "irrational_since_tick", world.tick_count)
    world.emit(
        Event(
            tick=world.tick_count,
            type="paranormal_break",
            subject=agent.id,
            detail=f"snapped (fear={fear:.1f})",
            severity="crit",
        )
    )
    _supernatural.spawn_glitch_marker(world, agent)


def _resolve_outcome(world: World, agent: Agent) -> None:
    """Sample an outcome once the agent has been IRRATIONAL long enough.

    v9 — when the agent has beliefs about local danger (``house_weak:X``
    nearby) or a specific suspect (``yellow_suspect:Y``), the outcome
    distribution skews accordingly: distrust the shelter and bolt outside,
    or lash out at the perceived villain.
    """
    outcomes = ("unlock_door", "run_outside", "attack_neighbour", "silent_collapse")
    # Light weighting: silent_collapse rarer, others roughly even.
    w = [3.0, 3.0, 3.0, 1.5]
    mind = getattr(agent, "mind", None)
    if mind is not None:
        # Find the nearest building id for "house_weak" lookups.
        nearest_b = nearest(list(world.buildings.values()), agent.x, agent.y)
        if nearest_b is not None:
            hw = mind.beliefs.get(f"house_weak:{nearest_b.id}")
            if hw is not None and hw.confidence > 0.4:
                w[1] += 2.5 * hw.confidence   # +run_outside (don't trust this shelter)
                w[0] += 1.0 * hw.confidence   # +unlock_door (something to escape from)
        # Any active suspicion tips toward attack_neighbour.
        for key, belief in mind.beliefs.items():
            if key.startswith("yellow_suspect:") and belief.confidence > 0.5:
                w[2] += 2.0 * belief.confidence
                break
    outcome = world.rng.choices(outcomes, weights=w, k=1)[0]

    if outcome == "unlock_door":
        target = nearest(list(world.buildings.values()), agent.x, agent.y)
        if target is not None:
            target.locked = False
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="irrational_act",
                    subject=agent.id,
                    detail=f"unlocked {target.name}",
                    severity="warn",
                )
            )
    elif outcome == "run_outside":
        # Pick a building, then "shove" the agent away from it.
        shelter = nearest(list(world.buildings.values()), agent.x, agent.y)
        if shelter is not None:
            dx = agent.x - shelter.x
            dy = agent.y - shelter.y
            d = max(1.0, (dx * dx + dy * dy) ** 0.5)
            agent.x = float(agent.x + (dx / d) * 60.0)
            agent.y = float(agent.y + (dy / d) * 60.0)
        world.emit(
            Event(
                tick=world.tick_count,
                type="irrational_act",
                subject=agent.id,
                detail="bolted outside",
                severity="warn",
            )
        )
    elif outcome == "attack_neighbour":
        neighbours = [
            n for n in _eligible_agents(world)
            if n.id != agent.id and distance(n, agent) <= 60.0
        ]
        if neighbours:
            # v9 — if any neighbour is the subject of an active yellow_suspect
            # belief, the agent lashes at THEM specifically (the "I knew it
            # was you" moment). Otherwise uniform random.
            suspect_id: Optional[str] = None
            mind = getattr(agent, "mind", None)
            if mind is not None:
                for key, belief in mind.beliefs.items():
                    if key.startswith("yellow_suspect:") and belief.confidence > 0.5:
                        suspect_id = key.split(":", 1)[1]
                        break
            if suspect_id is not None:
                preferred = [n for n in neighbours if n.id == suspect_id]
                if preferred:
                    victim = preferred[0]
                else:
                    victim = world.rng.choice(neighbours)
            else:
                victim = world.rng.choice(neighbours)
            setattr(victim, "status", Status.INCAPACITATED)
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="incapacitated",
                    subject=victim.id,
                    detail=f"attacked by {agent.id}",
                    severity="crit",
                )
            )
        else:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="irrational_act",
                    subject=agent.id,
                    detail="lashed out at empty air",
                    severity="info",
                )
            )
    else:  # silent_collapse
        setattr(agent, "status", Status.INCAPACITATED)
        world.emit(
            Event(
                tick=world.tick_count,
                type="incapacitated",
                subject=agent.id,
                detail="silent collapse",
                severity="warn",
            )
        )

    setattr(agent, "outcome_resolved", True)


def _tick_irrational(world: World, agent: Agent) -> None:
    """State machine inside IRRATIONAL — outcome + recovery."""
    since = int(getattr(agent, "irrational_since_tick", world.tick_count))
    elapsed = world.tick_count - since
    if elapsed == _IRRATIONAL_OUTCOME_TICKS and not getattr(agent, "outcome_resolved", False):
        _resolve_outcome(world, agent)
    if elapsed >= _IRRATIONAL_TOTAL_TICKS:
        # Recover (unless the outcome was a self-collapse).
        if getattr(agent, "status", Status.ACTIVE) == Status.ACTIVE:
            setattr(agent, "state", State.WANDERING)
            setattr(agent, "fear", max(0.0, float(getattr(agent, "fear", 0.0)) - _FEAR_DRAIN_AFTER_BREAK))
            setattr(agent, "outcome_resolved", False)
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="recovered",
                    subject=agent.id,
                    detail="returned to senses",
                    severity="info",
                )
            )


# ----------------------------------------------------------------- public


def propagate(world: World) -> None:
    """One tick of fear propagation + irrational follow-up."""
    creatures = world.creatures
    eligible = _eligible_agents(world)

    # Find the nearest creature for each agent in a single pass; reused for
    # both fear gain and the decay path so a hidden agent decays even with
    # creatures nearby.
    nearest_dist: dict = {}
    if creatures:
        for agent in eligible:
            min_d = None
            for c in creatures:
                d = distance(agent, c)
                if min_d is None or d < min_d:
                    min_d = d
            nearest_dist[id(agent)] = min_d

    if creatures:
        for agent in eligible:
            brave = float(getattr(agent, "brave", 0.5))
            min_d = nearest_dist.get(id(agent))
            if min_d is None:
                continue
            gain = _fear_gain(brave, min_d)
            if gain > 0.0:
                current = float(getattr(agent, "fear", 0.0))
                setattr(agent, "fear", min(100.0, current + gain))

    # Fear decay: every tick, fear drifts back toward 0. Sheltering / sleeping
    # in a protected building drains it fast; otherwise a small idle drain.
    # Without this, a single creature night strands the whole village in
    # FLEEING forever — observed in the live snapshot before this fix.
    phase = world.time.phase
    for agent in eligible:
        cur = float(getattr(agent, "fear", 0.0))
        if cur <= 0.0:
            continue
        state = getattr(agent, "state", None)
        in_safe_shelter = False
        dwelling_id = getattr(agent, "dwelling_id", None) or getattr(agent, "home_id", None)
        if dwelling_id and dwelling_id in world.buildings:
            b = world.buildings[dwelling_id]
            if b.is_protected(world.tick_count):
                in_safe_shelter = True
        # Skip decay if a creature is within meaningful range (60 px) — that's
        # active terror, fear should not regenerate downward.
        min_d = nearest_dist.get(id(agent))
        if min_d is not None and min_d < 60.0:
            continue
        if state == State.SLEEPING and in_safe_shelter:
            drain = 1.20
        elif state == State.SHELTERING and in_safe_shelter:
            drain = 0.80
        elif phase == Phase.DAY:
            drain = 0.30
        else:
            drain = 0.10
        new = max(0.0, cur - drain)
        setattr(agent, "fear", new)

    # Always run break + irrational follow-up (gives agents who broke a creature
    # back a chance to recover even after the creature has retreated).
    for agent in eligible:
        if getattr(agent, "state", None) == State.IRRATIONAL:
            _tick_irrational(world, agent)
        else:
            _maybe_break(world, agent)
