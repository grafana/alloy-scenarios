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
from typing import Optional

from contracts import (
    Agent,
    AgentKind,
    Event,
    FOREST_SPAWN_POINTS,
    MarkerClass,
    Phase,
    Role,
    State,
    World,
)
from agents.base import distance, move_toward, nearest


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

    # ------------------------------------------------------------- helpers
    def _pick_target(self, world: World) -> Optional[str]:
        """Prefer the nearest building without a talisman; fall back to any."""
        unprotected = [b for b in world.buildings.values() if not b.has_talisman]
        if unprotected:
            target = nearest(unprotected, self.x, self.y)
        else:
            target = nearest(list(world.buildings.values()), self.x, self.y)
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
            }
        )
        return base


# ----------------------------------------------------------- spawning


def _spawn_count_for_day(day: int, rng) -> int:
    """1–3 creatures on early days, scaling up gently with cycle length."""
    base = 1 + min(3, day // 3)
    return rng.randint(base, base + 1)


def maybe_spawn(world: World) -> None:
    """Spawn creatures only on the DAY -> DUSK boundary.

    Also despawns creatures whose retreat is complete (substate == DESPAWN).
    """
    # Prune retreated creatures first so the list doesn't bloat.
    if world.creatures:
        world.creatures[:] = [c for c in world.creatures if getattr(c, "substate", "") != "DESPAWN"]

    # Detect the DAY -> DUSK edge using last_phase (managed by simulation.py).
    if world.last_phase == Phase.DAY and world.time.phase == Phase.DUSK:
        n = _spawn_count_for_day(world.time.day, world.rng)
        for _ in range(n):
            sx, sy = world.rng.choice(FOREST_SPAWN_POINTS)
            cid = f"creature_d{world.time.day}_c{world.tick_count}_{world.rng.randint(0, 9999)}"
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
