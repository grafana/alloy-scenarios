"""
Forest creatures.

Sub-FSM (lives inside the Creature, not the global transition table):

    WALKING      — moving from the spawn point toward a target building.
    PROBING      — at the doorstep; counting down 8 ticks of "is anyone home?"
    INTRUDING    — door was unlocked AND there was no talisman; inside, hunting.
    HYPNOTIZING  — a child is here; freeze them.
    RETREATING   — dawn arrived; head back to the forest and despawn.

Spawning is gated to the DAY -> DUSK phase boundary so a fresh cohort steps out
of the forest every sim-evening. Number per cohort scales lightly with day so
later cycles feel more pressured.

This file uses only ``world.rng``; agent-state writes go through the agent
itself; world-observable changes are emitted via ``world.emit``.
"""

from __future__ import annotations

import math
from typing import List, Optional

from contracts import (
    Agent,
    AgentKind,
    BARN_DOWN_DEFAULT_TICKS,
    CAVE_ENTRY_XY,
    Event,
    FOREST_SPAWN_POINTS,
    MarkerClass,
    Metric,
    Phase,
    Role,
    State,
    Status,
    World,
)
from agents.base import distance, move_toward, nearest
import legacy as _legacy


# Sub-state strings (kept narrow to this file; not part of the global State enum).
_WALKING = "WALKING"
_PROBING = "PROBING"
_INTRUDING = "INTRUDING"
_HYPNOTIZING = "HYPNOTIZING"
_RETREATING = "RETREATING"

_CREATURE_SPEED = 1.6
_PROBE_DURATION_TICKS = 8
_HYPNOSIS_DURATION_TICKS = 6
_INTRUSION_MAX_TICKS = 40
_DOOR_PROXIMITY = 18.0

# v6 — swarmer-tier creatures: faster, shorter probe, nuisance-level rather
# than apex. They cluster-spawn in 3-packs from the same forest point.
_SWARMER_SPEED = 3.5
_SWARMER_PROBE_DURATION_TICKS = 5
_SWARMER_HYPNOSIS_DURATION_TICKS = 3
_SWARMER_INTRUSION_MAX_TICKS = 25
_SWARMER_DOOR_PROXIMITY = 14.0
_SWARMER_FRACTION = 0.45
_SWARMERS_PER_CLUSTER = 3

# v7 — creature hunting. A creature in WALKING substate looks for visible
# characters (outside any talisman building, not SHELTERING, not SLEEPING)
# within _HUNT_RADIUS px. If found, it pivots to chase that character instead
# of probing a building. Catching them (within 10 px) sets them INCAPACITATED
# and the creature retreats with the kill.
# v9.1 — danger pass: wider hunt, slightly faster chase, larger catch box.
_HUNT_RADIUS = 150.0
_HUNT_CATCH_RADIUS = 14.0
_HUNT_SPEED_BONUS = 0.6   # +0.6 px/tick when actively chasing
# v7 — cave-dwelling spawn. During NIGHT (v9.1: also DUSK), every
# _CAVE_SPAWN_INTERVAL ticks a new creature emerges from the cave entry.
# Probability gates how busy the cave is on any given night.
_CAVE_SPAWN_INTERVAL_TICKS = 60    # ~2 sim-hours (v9.1)
_CAVE_SPAWN_PROB = 0.70            # 70% of intervals during DUSK/NIGHT spawn one
# v7 — barn is the food store. When the barn is breached, the food economy
# collapses for BARN_DOWN_DEFAULT_TICKS ticks unless an engineer repairs it.
_BARN_BUILDING_ID = "barn"

# v8 — buildings creatures will never target. The lighthouse is a refuge /
# narrative artefact; having creatures wander into it broke immersion. Add
# any building here that should be off-limits regardless of talisman state.
_OFF_LIMITS_BUILDING_IDS = frozenset({"lighthouse"})

# v8 — population-aware spawn scaling. Replaces the day-only formula. The
# more agents on the map (chars + NPCs), the bigger the cohort that arrives
# at dusk, so the night pressure tracks the size of the population.
# v9.1 — danger pass: steeper scaling + higher cap so a thriving town
# actually faces a cohort large enough to threaten it.
_SPAWN_PER_N_AGENTS = 8         # one extra creature per 8 living agents
_SPAWN_BASE = 2                 # always at least 2 spawn each dusk
_SPAWN_CAP = 20                 # hard cap so the map doesn't drown
_SPAWN_DAY_BONUS_CAP = 3        # later days add up to +3 on top of population
_HUNT_RADIUS_OVERCROWD = 240.0  # vision range expands when overcrowded


class Creature(Agent):
    """A forest creature. Lives in ``world.creatures``."""

    def __init__(self, creature_id: str, x: float, y: float) -> None:
        self.id = creature_id
        self.kind = AgentKind.CREATURE
        self.marker_class = MarkerClass.CREATURE
        self.x = float(x)
        self.y = float(y)

        self.substate: str = _WALKING
        self.target_building_id: Optional[str] = None
        self.spawn_x: float = float(x)
        self.spawn_y: float = float(y)
        self.tick_in_substate: int = 0
        self.victim_id: Optional[str] = None
        # v9.1 — stalker multi-kill loop. After catching prey we keep
        # hunting up to ``kill_cap`` total before retreating, which lets a
        # single rampaging creature meaningfully thin an exposed cohort
        # instead of one-and-done. Swarmers override kill_cap=1 below.
        self.kills_made: int = 0
        self.kill_cap: int = 3

    # ------------------------------------------------------------- helpers
    def _pick_target(self, world: World) -> Optional[str]:
        """Prefer the nearest building without a talisman; fall back to any.

        v9 — when the Director has a non-empty ``target_bias`` (cross-cycle
        weakness map), we trade pure nearest-neighbour for weighted choice
        so creatures preferentially seek buildings whose talismans have
        bent in previous cycles. Off-limits and destroyed buildings are
        always excluded.
        """
        def eligible(b) -> bool:
            if b.id in _OFF_LIMITS_BUILDING_IDS:
                return False
            if getattr(b, "destroyed", False):
                return False
            return True

        candidates = [b for b in world.buildings.values() if eligible(b)]
        if not candidates:
            return None
        unprotected = [b for b in candidates if not b.has_talisman]
        pool = unprotected if unprotected else candidates

        # Director bias: a soft weight that prefers historically weak spots.
        director = getattr(world, "director", None)
        tb = getattr(director, "target_bias", {}) or {}
        if tb:
            # Combine inverse-distance (closer = heavier) with the bias weight.
            weights = []
            for b in pool:
                d = max(1.0, distance(self, b))
                bias = 1.0 + 3.0 * float(tb.get(b.id, 0.0))
                weights.append((1000.0 / d) * bias)
            try:
                target = world.rng.choices(pool, weights=weights, k=1)[0]
                return target.id
            except (ValueError, IndexError):
                pass

        target = nearest(pool, self.x, self.y)
        return target.id if target is not None else None

    def _set_substate(self, new: str) -> None:
        if new != self.substate:
            self.substate = new
            self.tick_in_substate = 0

    # -------------------------------------------------------- main tick
    def tick(self, world: World) -> None:
        self.tick_in_substate += 1

        # Dawn forces retreat regardless of current substate.
        if world.time.phase == Phase.DAWN and self.substate != _RETREATING:
            self._set_substate(_RETREATING)

        if self.substate == _WALKING:
            self._tick_walking(world)
        elif self.substate == _PROBING:
            self._tick_probing(world)
        elif self.substate == _INTRUDING:
            self._tick_intruding(world)
        elif self.substate == _HYPNOTIZING:
            self._tick_hypnotizing(world)
        elif self.substate == _RETREATING:
            self._tick_retreating(world)

    # ---- substate handlers ----
    def _tick_walking(self, world: World) -> None:
        # v7 — first, look for a visible outside character to hunt. If one is
        # within _HUNT_RADIUS the creature drops its building plan and chases.
        # v9.1 — after a catch, stalkers (kill_cap > 1) can keep hunting up
        # to ``kill_cap`` total before retreating.
        prey = _find_prey(world, self, _HUNT_RADIUS)
        if prey is not None:
            reached = move_toward(
                self, float(prey.x), float(prey.y),
                _CREATURE_SPEED + _HUNT_SPEED_BONUS,
            )
            # Catch! Set the prey INCAPACITATED and possibly keep hunting.
            if reached or distance(self, prey) <= _HUNT_CATCH_RADIUS:
                _catch_prey(world, self, prey)
                self.kills_made += 1
                # v9.1 — emit a rampage event the second time a stalker
                # catches prey in one outing. Loud signal in the event log
                # so the user can spot it.
                if self.kills_made >= 2:
                    world.emit(Event(
                        tick=world.tick_count,
                        type="creature_kill_streak",
                        subject=self.id,
                        detail=f"rampage: {self.kills_made} kills this hunt",
                        severity="warn",
                    ))
                # If we still have kills left in the bank, fall through so
                # the next prey search runs immediately on the next tick
                # (we just reset hunting emission so a fresh chase logs).
                if self.kills_made < self.kill_cap and world.time.phase in (Phase.DUSK, Phase.NIGHT):
                    self.victim_id = None
                    self._hunting_emitted = False
                    # Stay in WALKING — next tick re-acquires.
                else:
                    self._set_substate(_RETREATING)
            else:
                # Emit a hunting event at most once per chase — flag via a
                # lazy attribute so we don't spam.
                if getattr(self, "_hunting_emitted", False) is False:
                    self._hunting_emitted = True
                    world.emit(Event(
                        tick=world.tick_count,
                        type="creature_hunting",
                        subject=self.id,
                        detail=f"chasing {getattr(prey, 'name', prey.id)}",
                        severity="warn",
                    ))
            return

        if self.target_building_id is None:
            self.target_building_id = self._pick_target(world)
            if self.target_building_id is None:
                self._set_substate(_RETREATING)
                return
        target = world.buildings.get(self.target_building_id)
        if target is None:
            self.target_building_id = None
            return
        reached = move_toward(self, target.x, target.y, _CREATURE_SPEED)
        if reached or distance(self, target) <= _DOOR_PROXIMITY:
            self._set_substate(_PROBING)

    def _tick_probing(self, world: World) -> None:
        target = world.buildings.get(self.target_building_id or "")
        if target is None:
            self._set_substate(_WALKING)
            return
        # Probe duration elapsed — decide what happens.
        if self.tick_in_substate >= _PROBE_DURATION_TICKS:
            if not target.has_talisman and not target.locked:
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="creature_breach",
                        subject=self.id,
                        detail=f"breached {target.name}",
                        severity="crit",
                    )
                )
                # v7 — barn breach destroys the food store.
                if target.id == _BARN_BUILDING_ID:
                    _destroy_barn(world, self)
                # v8 — every unprotected breach chips at the structure.
                _accumulate_house_damage(world, target, self.id)
                # v9 — Director cross-cycle memory of which buildings break.
                _bump_failure(world, target.id, 1.0)
                self._set_substate(_INTRUDING)
            else:
                # Stymied. Go retreat to the woods rather than loiter.
                self._set_substate(_RETREATING)

    def _tick_intruding(self, world: World) -> None:
        target = world.buildings.get(self.target_building_id or "")
        if target is None:
            self._set_substate(_RETREATING)
            return
        # Look for a child currently inside — uses the building's occupant set,
        # falling back to "any nearby CHILD agent" if occupancy isn't tracked yet.
        child = self._find_child_in(target, world)
        if child is not None and self.victim_id != child.id:
            self.victim_id = child.id
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="hypnosis_attempt",
                    subject=self.id,
                    detail=f"targeting {child.id}",
                    severity="warn",
                )
            )
            self._set_substate(_HYPNOTIZING)
            return
        # No victim within the timeout — leave.
        if self.tick_in_substate >= _INTRUSION_MAX_TICKS:
            self._set_substate(_RETREATING)

    def _tick_hypnotizing(self, world: World) -> None:
        victim = world.agents.get(self.victim_id) if self.victim_id else None
        if victim is None:
            self._set_substate(_INTRUDING)
            self.victim_id = None
            return
        # Drag the victim's state to HYPNOTIZED for the duration. We do NOT
        # delete the agent — Agent B's character loop sees HYPNOTIZED and
        # decides what to do next.
        setattr(victim, "state", State.HYPNOTIZED)
        if self.tick_in_substate >= _HYPNOSIS_DURATION_TICKS:
            self.victim_id = None
            self._set_substate(_RETREATING)

    def _tick_retreating(self, world: World) -> None:
        reached = move_toward(self, self.spawn_x, self.spawn_y, _CREATURE_SPEED * 1.2)
        if reached:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="creature_retreat",
                    subject=self.id,
                    detail="returned to forest",
                    severity="info",
                )
            )
            # Mark for despawn — engine prunes in maybe_spawn / simulation loop.
            self.substate = "DESPAWN"

    # ------------------------------------------------------------ utility
    @staticmethod
    def _find_child_in(target, world: World):
        # 1) Try occupant set first.
        for occ_id in target.occupants:
            agent = world.agents.get(occ_id)
            if agent is not None and getattr(agent, "role", None) == Role.CHILD:
                return agent
        # 2) Fall back to spatial check (within building footprint radius).
        # Agent B may or may not maintain occupancy yet; this keeps behaviour
        # working in either case.
        radius = 40.0
        for a in world.agents.values():
            if getattr(a, "role", None) != Role.CHILD:
                continue
            if distance(a, target) <= radius:
                return a
        return None

    def to_dict(self):
        base = super().to_dict()
        base.update(
            {
                "substate": self.substate,
                "target": self.target_building_id,
                "victim_id": self.victim_id,
                "intent": _intent_for(self),
                "role": "Forest creature"
                if not isinstance(self, SwarmerCreature)
                else "Swarmer creature",
                "status": _substate_label(self.substate),
            }
        )
        return base


# ---------------------------------------------------------------------------
# v6 — SwarmerCreature: a smaller, faster nuisance-tier creature.
#
# Same FSM as the apex stalker, but with reduced proximity radii, faster
# movement, and shorter probe/hypnotize windows. They spawn in clusters of
# three from a single forest point so visually they read as a pack.
# ---------------------------------------------------------------------------


class SwarmerCreature(Creature):
    """A swarmer — small, fast, packs-of-three creature.

    Inherits the parent FSM. Overrides only the timing/proximity constants and
    the speed used in the WALKING/RETREATING handlers.
    """

    def __init__(self, creature_id: str, x: float, y: float) -> None:
        super().__init__(creature_id, x, y)
        self.marker_class = MarkerClass.CREATURE_SWARM
        # v9.1 — swarmers keep single-prey behaviour; multi-kill is for
        # the apex stalker only.
        self.kill_cap = 1

    # ---- substate handlers: replicate base behaviour but with smaller radii
    # / faster steps. We override the three handlers that depend on the
    # tunable constants. The HYPNOTIZING handler shares the parent path but
    # uses the swarmer hypnosis duration via the timing check below.
    def _tick_walking(self, world: World) -> None:
        # v7 — swarmers hunt too, and they're faster.
        # v9.1 — swarmers keep single-prey behaviour (kill_cap=1) but the
        # kills_made counter is still maintained for parity with stalkers.
        prey = _find_prey(world, self, _HUNT_RADIUS)
        if prey is not None:
            reached = move_toward(
                self, float(prey.x), float(prey.y),
                _SWARMER_SPEED + _HUNT_SPEED_BONUS,
            )
            if reached or distance(self, prey) <= _HUNT_CATCH_RADIUS:
                _catch_prey(world, self, prey)
                self.kills_made += 1
                self._set_substate(_RETREATING)
            else:
                if getattr(self, "_hunting_emitted", False) is False:
                    self._hunting_emitted = True
                    world.emit(Event(
                        tick=world.tick_count,
                        type="creature_hunting",
                        subject=self.id,
                        detail=f"swarmer chasing {getattr(prey, 'name', prey.id)}",
                        severity="warn",
                    ))
            return
        if self.target_building_id is None:
            self.target_building_id = self._pick_target(world)
            if self.target_building_id is None:
                self._set_substate(_RETREATING)
                return
        target = world.buildings.get(self.target_building_id)
        if target is None:
            self.target_building_id = None
            return
        reached = move_toward(self, target.x, target.y, _SWARMER_SPEED)
        if reached or distance(self, target) <= _SWARMER_DOOR_PROXIMITY:
            self._set_substate(_PROBING)

    def _tick_probing(self, world: World) -> None:
        target = world.buildings.get(self.target_building_id or "")
        if target is None:
            self._set_substate(_WALKING)
            return
        if self.tick_in_substate >= _SWARMER_PROBE_DURATION_TICKS:
            if not target.has_talisman and not target.locked:
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="creature_breach",
                        subject=self.id,
                        detail=f"swarm breached {target.name}",
                        severity="crit",
                    )
                )
                if target.id == _BARN_BUILDING_ID:
                    _destroy_barn(world, self)
                # v9 — Director cross-cycle memory.
                _bump_failure(world, target.id, 0.6)  # swarmers count for less
                self._set_substate(_INTRUDING)
            else:
                self._set_substate(_RETREATING)

    def _tick_intruding(self, world: World) -> None:
        target = world.buildings.get(self.target_building_id or "")
        if target is None:
            self._set_substate(_RETREATING)
            return
        child = self._find_child_in(target, world)
        if child is not None and self.victim_id != child.id:
            self.victim_id = child.id
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="hypnosis_attempt",
                    subject=self.id,
                    detail=f"swarmer targeting {child.id}",
                    severity="warn",
                )
            )
            self._set_substate(_HYPNOTIZING)
            return
        if self.tick_in_substate >= _SWARMER_INTRUSION_MAX_TICKS:
            self._set_substate(_RETREATING)

    def _tick_hypnotizing(self, world: World) -> None:
        victim = world.agents.get(self.victim_id) if self.victim_id else None
        if victim is None:
            self._set_substate(_INTRUDING)
            self.victim_id = None
            return
        setattr(victim, "state", State.HYPNOTIZED)
        if self.tick_in_substate >= _SWARMER_HYPNOSIS_DURATION_TICKS:
            self.victim_id = None
            self._set_substate(_RETREATING)

    def _tick_retreating(self, world: World) -> None:
        reached = move_toward(self, self.spawn_x, self.spawn_y, _SWARMER_SPEED * 1.2)
        if reached:
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="creature_retreat",
                    subject=self.id,
                    detail="swarmer returned to forest",
                    severity="info",
                )
            )
            self.substate = "DESPAWN"


# ----------------------------------------------------------- spawning


def _spawn_count_for_day(day: int, rng) -> int:
    """Legacy day-only spawn count, kept for tests.

    Formula: ``2 + min(5, day // 2) + randint(0, 2)``.
    """
    base = 2 + min(5, day // 2)
    return base + rng.randint(0, 2)


def _spawn_count(world: World) -> int:
    """v8 — population-aware dusk spawn count.

    The cohort tracks the live population so a thinned-out town gets a
    breather and a thriving town gets aggressively culled. Hard cap so the
    map doesn't drown.

    v9 — multiplied by ``world.director.spawn_rate_mult`` so the AI Director
    can escalate (low pressure) or hold back (high pressure) the cohort.
    """
    rng = world.rng
    pop = sum(
        1 for a in world.agents.values()
        if getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
    )
    pop_term = pop // _SPAWN_PER_N_AGENTS
    day_term = min(_SPAWN_DAY_BONUS_CAP, world.time.day // 3)
    jitter = rng.randint(0, 2)
    base = _SPAWN_BASE + pop_term + day_term + jitter
    director = getattr(world, "director", None)
    mult = float(getattr(director, "spawn_rate_mult", 1.0))
    return max(_SPAWN_BASE, min(_SPAWN_CAP, int(round(base * mult))))


# v8 — substate → human label for the dossier card.
_SUBSTATE_LABELS = {
    _WALKING: "Stalking",
    _PROBING: "Probing a door",
    _INTRUDING: "Inside",
    _HYPNOTIZING: "Hypnotising",
    _RETREATING: "Retreating",
    "DESPAWN": "Gone",
}


def _substate_label(substate: str) -> str:
    return _SUBSTATE_LABELS.get(substate, substate or "?")


def _intent_for(creature: "Creature") -> str:
    """Build a one-line dossier intent from the creature's current substate.

    Looks up the target building name on demand (best-effort — if the
    world reference isn't available, falls back to the raw id). Always
    returns a complete sentence so the dossier UI never shows a blank.
    """
    target_name = creature.target_building_id or "the village"
    # The Creature doesn't hold a world ref, but the SocketIO inspect
    # handler enriches with target_name via `_resolve_agent`; this string
    # is a sensible default the user can still read on its own.
    sub = creature.substate
    if sub == _WALKING:
        if getattr(creature, "_hunting_emitted", False):
            return "Chasing a survivor in the open."
        return f"Stalking toward {target_name}."
    if sub == _PROBING:
        return f"Testing the doors of {target_name}."
    if sub == _INTRUDING:
        return f"Inside {target_name} — looking for prey."
    if sub == _HYPNOTIZING:
        return f"Hypnotising {creature.victim_id or 'someone'}."
    if sub == _RETREATING:
        return "Falling back to the treeline."
    if sub == "DESPAWN":
        return "Gone — back into the forest."
    return "Watching from the dark."


# ---------------------------------------------------------------------------
# v7 — hunting, cave-dwelling spawn, barn destruction
# ---------------------------------------------------------------------------


def _find_prey(world: World, creature: "Creature", radius: float):
    """Return the nearest huntable agent within ``radius`` px, or None.

    v8 — both characters AND NPCs are huntable. Anyone caught outside
    when the sun goes down is fair game. An agent is "outside" if their
    state is not one of the safe-indoors states (SLEEPING / SHELTERING /
    IRRATIONAL means tucked in a corner / already incapacitated).

    Hunting only ramps during DUSK / NIGHT. During DAY characters can
    roam freely.
    """
    phase = world.time.phase
    if phase == Phase.DAY:
        # Creatures still wander toward buildings during DAY/DAWN but they
        # don't actively chase prey in broad daylight.
        return None

    # Expand vision when the village is overcrowded — the population
    # pressure mechanic the user asked for. We want a thriving town to
    # actively be culled.
    pop = sum(
        1 for a in world.agents.values()
        if getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
    )
    effective_radius = radius
    if pop > 60:
        effective_radius = max(radius, _HUNT_RADIUS_OVERCROWD)

    SAFE_STATES = {State.SLEEPING, State.SHELTERING, State.IRRATIONAL}

    best = None
    best_d = effective_radius
    for a in world.agents.values():
        kind = getattr(a, "kind", None)
        if kind not in (AgentKind.CHARACTER, AgentKind.NPC):
            continue
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        s = getattr(a, "state", None)
        if s in SAFE_STATES:
            continue
        d = distance(creature, a)
        if d < best_d:
            best = a
            best_d = d
    return best


def _catch_prey(world: World, creature: "Creature", prey) -> None:
    """A creature has caught an agent — incapacitate or kill, and log it.

    Characters survive as INCAPACITATED so the recover/resurrection paths
    still work. NPCs aren't core to the story — they die outright, which
    feeds the population pressure loop the user asked for.
    """
    kind = getattr(prey, "kind", None)
    pid = getattr(prey, "id", "?")
    if kind == AgentKind.NPC:
        try:
            prey.status = Status.DEAD
        except Exception:
            pass
        world.emit(Event(
            tick=world.tick_count,
            type="npc_death",
            subject=pid,
            detail=f"caught by {creature.id} in the open after dark",
            severity="crit",
        ))
        return
    # Default: character. Status INCAPACITATED leaves the agent on the
    # board so the existing recovery / death pipelines fire.
    try:
        prey.status = Status.INCAPACITATED
    except Exception:
        pass
    world.emit(Event(
        tick=world.tick_count,
        type="incapacitated",
        subject=pid,
        detail=f"caught by {creature.id} in the open",
        severity="crit",
    ))


def _bump_failure(world: World, building_id: str, amount: float = 1.0) -> None:
    """v9 — record one more unit of weakness for a building (cross-cycle).

    Routes through the Director module when available so the legacy field
    is initialised on demand; falls back to a direct write on the legacy
    dict so a missing director module (e.g. in a unit test) doesn't break
    persistence.
    """
    try:
        from agents import director as _director
        _director.bump_talisman_failure(world, building_id, amount)
        return
    except Exception:
        pass
    legacy = getattr(world, "legacy", None)
    if legacy is None:
        return
    tfc = getattr(legacy, "talisman_failure_count", None)
    if tfc is None:
        return
    tfc[str(building_id)] = float(tfc.get(str(building_id), 0.0)) + float(amount)


def _destroy_barn(world: World, creature: "Creature") -> None:
    """Mark the barn destroyed. Food regen collapses until repaired or timer expires.

    Idempotent — if the barn is already down, this is a no-op so a second
    breach doesn't extend the timer indefinitely.
    """
    if world.tick_count < int(getattr(world, "barn_destroyed_until_tick", 0)):
        return
    world.barn_destroyed_until_tick = world.tick_count + BARN_DOWN_DEFAULT_TICKS
    world.barn_repair_progress = 0.0
    world.emit(Event(
        tick=world.tick_count,
        type="barn_destroyed",
        subject=creature.id,
        detail="the barn is broken — the food store is gone",
        severity="crit",
    ))
    try:
        _legacy.record(world, "barn_destroyed")
    except Exception:
        pass
    # Mark the barn building as locked so a second creature doesn't loiter on
    # it the same tick (engine treats locked-but-no-talisman as resistant).
    barn = world.buildings.get(_BARN_BUILDING_ID)
    if barn is not None:
        try:
            barn.cooling_off_until_tick = world.barn_destroyed_until_tick
        except Exception:
            pass


def tick_cave_spawn(world: World) -> None:
    """v7 — at NIGHT (v9.1: also DUSK), periodically spawn a stalker from
    the cave entry.

    Cap the count so the cave doesn't dump unlimited creatures; only spawn
    if the current live-creature population is below a soft ceiling. The
    cave is the second front: while creatures from the forest probe
    buildings, cave spawns try to ambush characters in the centre of the
    village.
    """
    if world.time.phase not in (Phase.DUSK, Phase.NIGHT):
        return
    # v9.1 — raised from 8 to 14 so the cave can keep adding bodies even
    # when the dusk cohort has already landed.
    if len(world.creatures) >= 14:
        return
    last = int(getattr(world, "_cave_spawn_last_tick", -10_000))
    if world.tick_count - last < _CAVE_SPAWN_INTERVAL_TICKS:
        return
    if world.rng.random() >= _CAVE_SPAWN_PROB:
        # Still bump the timer so we re-roll later, not next tick.
        world._cave_spawn_last_tick = world.tick_count
        return
    world._cave_spawn_last_tick = world.tick_count
    cx, cy = CAVE_ENTRY_XY
    # Small jitter so successive spawns don't stack.
    jx = cx + world.rng.uniform(-8, 8)
    jy = cy + world.rng.uniform(-8, 8)
    cid = f"cave_d{world.time.day}_c{world.tick_count}_{world.rng.randint(0, 9999)}"
    creature = Creature(cid, jx, jy)
    # Skip the normal "pick a building" — cave creatures wander into town
    # looking for prey. They'll still probe a building if no prey is visible
    # within _HUNT_RADIUS once they reach the village edge.
    creature.target_building_id = None
    world.creatures.append(creature)
    world.emit(Event(
        tick=world.tick_count,
        type="creature_cave_spawn",
        subject=cid,
        detail=f"something climbed out of the cave at ({cx:.0f},{cy:.0f})",
        severity="warn",
    ))


def tick_night_wave(world: World) -> None:
    """v9.1 — sustained NIGHT pressure.

    The DAY→DUSK cohort can be wiped out, retreat after their kills, or
    miss the town entirely; without something else, NIGHT goes quiet and
    the village survives on inertia. This fires exactly once per simulated
    night — at the midnight slot (``hour < 3``) — and drops half-strength
    cohort of stalkers from the same forest spawn points. Director-
    modulated through ``_spawn_count``, so a thriving town gets a juicier
    wave automatically.
    """
    if world.time.phase != Phase.NIGHT:
        return
    # Midnight window: hours 0-2 sim-time. ``SimTime.hour`` is 0-23.
    if world.time.hour >= 3:
        return
    # Fire at most once per sim-day. ``_night_wave_day`` is a lazy
    # per-world cursor so we don't carry state outside of ``world``.
    last_day = getattr(world, "_night_wave_day", None)
    if last_day == world.time.day:
        return
    world._night_wave_day = world.time.day  # type: ignore[attr-defined]

    cohort = max(2, int(round(_spawn_count(world) * 0.5)))
    rng = world.rng
    ids: List[str] = []
    for _ in range(cohort):
        sx, sy = rng.choice(FOREST_SPAWN_POINTS)
        cid = (
            f"nightwave_d{world.time.day}_c{world.tick_count}_"
            f"{rng.randint(0, 9999)}"
        )
        world.creatures.append(Creature(cid, sx, sy))
        ids.append(cid)
    world.emit(Event(
        tick=world.tick_count,
        type="creature_night_wave",
        subject=ids[0] if ids else "world",
        detail=f"a second wave of {cohort} stepped out of the trees at midnight",
        severity="warn",
    ))
    if world.telemetry is not None:
        try:
            world.telemetry.counter_inc(Metric.CREATURES_NIGHT_WAVES_TOTAL, 1.0)
        except Exception:
            pass


def tick_barn_repair(world: World) -> None:
    """v7 — accumulate repair progress while engineers REPAIR near the barn.

    Once progress reaches BARN_REPAIR_THRESHOLD, clear the destroyed flag and
    emit ``barn_rebuilt``.
    """
    from contracts import BARN_REPAIR_PER_TICK, BARN_REPAIR_THRESHOLD
    if int(getattr(world, "barn_destroyed_until_tick", 0)) <= world.tick_count:
        # Either never broken or already cleared / timed out.
        if int(getattr(world, "barn_destroyed_until_tick", 0)) > 0 \
                and world.tick_count >= world.barn_destroyed_until_tick \
                and world.barn_repair_progress < BARN_REPAIR_THRESHOLD:
            # Timer-based recovery: log a less heroic rebuild.
            world.barn_destroyed_until_tick = 0
            world.barn_repair_progress = 0.0
            world.emit(Event(
                tick=world.tick_count,
                type="barn_rebuilt",
                subject="world",
                detail="they patched the barn back together in time",
                severity="info",
            ))
        return
    barn = world.buildings.get(_BARN_BUILDING_ID)
    if barn is None:
        return
    # Look for ENGINEER characters in REPAIRING state near the barn.
    repairing = 0
    for a in world.agents.values():
        if getattr(a, "kind", None) != AgentKind.CHARACTER:
            continue
        if getattr(a, "state", None) != State.REPAIRING:
            continue
        if getattr(a, "role", None) != Role.ENGINEER:
            continue
        if distance(a, barn) <= 30.0:
            repairing += 1
    if repairing > 0:
        world.barn_repair_progress += BARN_REPAIR_PER_TICK * repairing
        if world.barn_repair_progress >= BARN_REPAIR_THRESHOLD:
            world.barn_destroyed_until_tick = 0
            world.barn_repair_progress = 0.0
            world.emit(Event(
                tick=world.tick_count,
                type="barn_rebuilt",
                subject="world",
                detail="the engineer fixed the barn",
                severity="info",
            ))


# ---------------------------------------------------------------------------
# v8 — house destruction + rebuild + talisman crack
# ---------------------------------------------------------------------------


def _accumulate_house_damage(world: World, target, attacker_id: str) -> None:
    """Charge one breach of damage to a building. At threshold → destroyed.

    The barn has its own destruction mechanic; we deliberately don't
    double-book it here. Special buildings without a residential role
    (choosing stone, pool, abandoned bus, lighthouse) are ignored since
    creatures shouldn't have been able to target them anyway.
    """
    from contracts import HOUSE_DESTRUCTION_THRESHOLD

    if target.id == _BARN_BUILDING_ID:
        return
    if target.id in _OFF_LIMITS_BUILDING_IDS:
        return
    if target.footprint <= 0:
        # Not a real shelter (stones, pools, etc.) — nothing to destroy.
        return

    target.damage = int(getattr(target, "damage", 0)) + 1
    if not getattr(target, "destroyed", False) \
            and target.damage >= HOUSE_DESTRUCTION_THRESHOLD:
        target.destroyed = True
        target.rebuild_progress = 0.0
        # Evict anyone notionally inside so they aren't ghost-occupants.
        if target.occupants:
            target.occupants.clear()
        # Talisman is also gone — rebuilt houses come back bare.
        target.has_talisman = False
        world.emit(Event(
            tick=world.tick_count,
            type="house_destroyed",
            subject=attacker_id,
            detail=f"{target.name} has been torn apart",
            severity="crit",
        ))


def tick_talisman_crack(world: World) -> None:
    """v8 — chance per tick that an occupant cracks and breaks the talisman.

    Mechanic: a building with a talisman, with at least one occupant whose
    sanity is low AND fear is high, may have its talisman fail. When it
    does we emit ``talisman_cracked`` and clear ``has_talisman``. The
    building is then full-risk until rebuilt and re-warded.
    """
    from contracts import (
        TALISMAN_CRACK_FEAR,
        TALISMAN_CRACK_PROB,
        TALISMAN_CRACK_SANITY,
    )

    rng = world.rng
    # Only check during NIGHT — that's when fear/sanity bottoms out and the
    # narrative beat (someone snapping in the dark) makes sense.
    if world.time.phase != Phase.NIGHT:
        return

    for b in world.buildings.values():
        if not b.has_talisman or getattr(b, "destroyed", False):
            continue
        if not b.occupants:
            continue
        # Find a cracking occupant.
        cracker = None
        for occ_id in b.occupants:
            agent = world.agents.get(occ_id)
            if agent is None:
                continue
            sanity = float(getattr(agent, "sanity", 1.0))
            fear = float(getattr(agent, "fear", 0.0))
            if sanity <= TALISMAN_CRACK_SANITY and fear >= TALISMAN_CRACK_FEAR:
                cracker = agent
                break
        if cracker is None:
            continue
        if rng.random() >= TALISMAN_CRACK_PROB:
            continue
        # Crack — the talisman fails permanently for this building.
        b.has_talisman = False
        world.emit(Event(
            tick=world.tick_count,
            type="talisman_cracked",
            subject=getattr(cracker, "id", b.id),
            detail=(
                f"{getattr(cracker, 'name', cracker.id)} cracked — the "
                f"talisman at {b.name} no longer holds"
            ),
            severity="crit",
        ))


def tick_house_repair(world: World) -> None:
    """v8 — survivors rebuild destroyed houses over time.

    Any character in REPAIRING state within 30 px of a destroyed house
    contributes HOUSE_REBUILD_PER_TICK toward progress. Multiple workers
    stack. At HOUSE_REBUILD_THRESHOLD the house is rebuilt — flags clear,
    damage zeros out, but the talisman does NOT come back (survivors
    have to find one).
    """
    from contracts import HOUSE_REBUILD_PER_TICK, HOUSE_REBUILD_THRESHOLD

    destroyed_houses = [
        b for b in world.buildings.values()
        if getattr(b, "destroyed", False) and b.id != _BARN_BUILDING_ID
    ]
    if not destroyed_houses:
        return

    for b in destroyed_houses:
        repairing = 0
        for a in world.agents.values():
            if getattr(a, "kind", None) != AgentKind.CHARACTER:
                continue
            if getattr(a, "state", None) != State.REPAIRING:
                continue
            if distance(a, b) <= 30.0:
                repairing += 1
        if repairing == 0:
            continue
        b.rebuild_progress = float(getattr(b, "rebuild_progress", 0.0)) \
            + HOUSE_REBUILD_PER_TICK * repairing
        if b.rebuild_progress >= HOUSE_REBUILD_THRESHOLD:
            b.destroyed = False
            b.damage = 0
            b.rebuild_progress = 0.0
            # Talisman stays off — the rebuilt frame doesn't carry the
            # original ward. has_talisman remains False until something
            # else (story event) restores it.
            world.emit(Event(
                tick=world.tick_count,
                type="house_rebuilt",
                subject="world",
                detail=f"{b.name} has been rebuilt — but it stands without a talisman",
                severity="info",
            ))


def maybe_spawn(world: World) -> None:
    """Spawn creatures only on the DAY -> DUSK boundary.

    Also despawns creatures whose retreat is complete (substate == DESPAWN).
    """
    # Prune retreated creatures first so the list doesn't bloat.
    if world.creatures:
        world.creatures[:] = [c for c in world.creatures if getattr(c, "substate", "") != "DESPAWN"]

    # Detect the DAY -> DUSK edge using last_phase (managed by simulation.py).
    if world.last_phase == Phase.DAY and world.time.phase == Phase.DUSK:
        rng = world.rng
        total = _spawn_count(world)
        spawned = 0
        # v6 — roughly _SWARMER_FRACTION of the batch arrives as swarmer
        # clusters. Each cluster is a 3-pack from one spawn point.
        n_swarm_clusters = 0
        n_swarmers_target = int(round(total * _SWARMER_FRACTION))
        # Ensure at least 1 cluster fires whenever the desired count rounds up
        # to >= half a cluster — otherwise swarms only appear on dusks with 9
        # spawning, which is rare. Half-cluster threshold = 2 swarmers.
        if n_swarmers_target >= max(2, _SWARMERS_PER_CLUSTER // 2):
            n_swarm_clusters = max(1, n_swarmers_target // _SWARMERS_PER_CLUSTER)
        for _ in range(n_swarm_clusters):
            sx, sy = rng.choice(FOREST_SPAWN_POINTS)
            cluster_ids = []
            for _i in range(_SWARMERS_PER_CLUSTER):
                # Small jitter so the three swarmers don't render on the same
                # pixel.
                jx = sx + rng.uniform(-6, 6)
                jy = sy + rng.uniform(-6, 6)
                cid = (
                    f"swarmer_d{world.time.day}_c{world.tick_count}_"
                    f"{rng.randint(0, 9999)}"
                )
                creature = SwarmerCreature(cid, jx, jy)
                world.creatures.append(creature)
                cluster_ids.append(cid)
                spawned += 1
            # One event per cluster — keeps the journal readable when the
            # batch is large.
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="creature_swarm_spawn",
                    subject=cluster_ids[0],
                    detail=(
                        f"a pack of {_SWARMERS_PER_CLUSTER} emerged near "
                        f"({sx:.0f},{sy:.0f})"
                    ),
                    severity="warn",
                )
            )

        # Remaining stalkers, scattered across spawn points.
        remaining = max(0, total - spawned)
        for _ in range(remaining):
            sx, sy = rng.choice(FOREST_SPAWN_POINTS)
            cid = (
                f"creature_d{world.time.day}_c{world.tick_count}_"
                f"{rng.randint(0, 9999)}"
            )
            creature = Creature(cid, sx, sy)
            world.creatures.append(creature)
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="creature_spawn",
                    subject=cid,
                    detail=f"emerged at ({sx:.0f},{sy:.0f})",
                    severity="warn",
                )
            )
