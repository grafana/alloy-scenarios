"""
"Dumb" supernatural entities — short-lived, mostly cosmetic effects.

Three kinds live here:

    BoyInWhite        — appears near a fearful agent; lowers their fear,
                         raises their sanity. Disappears after a few ticks.
    Anghkooey         — only spawns adjacent to an active Faraway Tree event.
                         Wanders the perimeter chanting; emits ``anghkooey_chant``.
    FarawayTreePortal — rare; flips a random wandering agent to ABSENT.

The "Man in Yellow" is NOT here — Agent C owns him.

These entities go into ``world.supernaturals`` (transient list). Each ticks
itself and self-deletes by setting ``alive = False``; ``roll(world)`` prunes
dead entries.
"""

from __future__ import annotations

from typing import List, Optional

from contracts import (
    Agent,
    AgentKind,
    Event,
    FARAWAY_TREES,
    MarkerClass,
    Phase,
    State,
    Status,
    World,
)
from agents.base import distance, move_toward, nearest


# ----------------------------------------------------------- BoyInWhite


class BoyInWhite(Agent):
    """A calming apparition. Walks toward a target, then dissipates."""

    DURATION = 30  # ticks

    def __init__(self, sid: str, x: float, y: float, target_id: Optional[str]) -> None:
        self.id = sid
        self.kind = AgentKind.SUPERNATURAL
        self.marker_class = MarkerClass.BOY_IN_WHITE
        self.x = float(x)
        self.y = float(y)
        self.target_id = target_id
        self.ticks_left = self.DURATION
        self.alive = True

    def tick(self, world: World) -> None:
        self.ticks_left -= 1
        target = world.agents.get(self.target_id) if self.target_id else None
        if target is not None:
            move_toward(self, target.x, target.y, 1.0)
            if distance(self, target) <= 30.0:
                # Calming effect — reduce fear, restore a little sanity.
                fear = float(getattr(target, "fear", 0.0))
                sanity = float(getattr(target, "sanity", 100.0))
                setattr(target, "fear", max(0.0, fear - 4.0))
                setattr(target, "sanity", min(100.0, sanity + 2.0))
        if self.ticks_left <= 0:
            self.alive = False

    def to_dict(self):
        base = super().to_dict()
        base["kind_detail"] = "boy_in_white"
        base["target"] = self.target_id
        return base


# ----------------------------------------------------------- Anghkooey


class Anghkooey(Agent):
    """Wandering chanter — only spawns adjacent to an active Faraway Tree event."""

    DURATION = 60

    def __init__(self, sid: str, x: float, y: float) -> None:
        self.id = sid
        self.kind = AgentKind.SUPERNATURAL
        self.marker_class = MarkerClass.ANGHKOOEY
        self.x = float(x)
        self.y = float(y)
        self.ticks_left = self.DURATION
        self.alive = True
        self._next_chant_in = 8

    def tick(self, world: World) -> None:
        self.ticks_left -= 1
        # Drift slightly each tick.
        self.x += world.rng.uniform(-2.0, 2.0)
        self.y += world.rng.uniform(-2.0, 2.0)
        self._next_chant_in -= 1
        if self._next_chant_in <= 0:
            self._next_chant_in = world.rng.randint(6, 14)
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="anghkooey_chant",
                    subject=self.id,
                    detail="chant from the treeline",
                    severity="info",
                )
            )
        if self.ticks_left <= 0:
            self.alive = False

    def to_dict(self):
        base = super().to_dict()
        base["kind_detail"] = "anghkooey"
        return base


# -------------------------------------------------------- FarawayTreePortal


class FarawayTreePortal(Agent):
    """A glowing portal at a Faraway Tree. Brief — may snatch a passerby."""

    DURATION = 25

    def __init__(self, sid: str, x: float, y: float) -> None:
        self.id = sid
        self.kind = AgentKind.SUPERNATURAL
        self.marker_class = MarkerClass.FARAWAY_TREE
        self.x = float(x)
        self.y = float(y)
        self.ticks_left = self.DURATION
        self.alive = True
        self.snatch_attempted = False

    def tick(self, world: World) -> None:
        self.ticks_left -= 1
        # Halfway through, attempt to snatch a wandering character.
        if not self.snatch_attempted and self.ticks_left <= (self.DURATION // 2):
            self.snatch_attempted = True
            candidates = [
                a for a in world.agents.values()
                if getattr(a, "state", None) == State.WANDERING
                and getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
                and distance(a, self) <= 180.0
            ]
            if candidates and world.rng.random() < 0.4:
                victim = world.rng.choice(candidates)
                setattr(victim, "status", Status.ABSENT)
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="faraway_portal",
                        subject=victim.id,
                        detail="taken by the Faraway Tree",
                        severity="warn",
                    )
                )
        if self.ticks_left <= 0:
            self.alive = False

    def to_dict(self):
        base = super().to_dict()
        base["kind_detail"] = "faraway_tree"
        return base


# ----------------------------------------------------------- roll table


# Per-tick spawn probabilities. Tuned so the village sees a couple of events
# per sim-day at 2 Hz. Anghkooey is gated on FarawayTree active.
_P_BOY = 0.0015        # mostly DUSK/NIGHT
_P_FARAWAY = 0.0008
_P_ANGHKOOEY = 0.004   # only when Faraway Tree active


def _any_faraway_active(supernaturals: List[Agent]) -> bool:
    return any(isinstance(s, FarawayTreePortal) and getattr(s, "alive", True) for s in supernaturals)


def roll(world: World) -> None:
    """Once-per-tick supernatural dispatcher.

    Prunes dead entities, ticks the live ones, then rolls for new spawns.
    """
    # 1) Tick live entities.
    for s in list(world.supernaturals):
        if getattr(s, "alive", True):
            s.tick(world)
    # 2) Prune dead.
    world.supernaturals[:] = [s for s in world.supernaturals if getattr(s, "alive", True)]

    rng = world.rng
    phase = world.time.phase

    # --- Boy in White ---
    boy_bias = 1.8 if phase in (Phase.DUSK, Phase.NIGHT) else 0.6
    if rng.random() < _P_BOY * boy_bias:
        # Pick the most-fearful active agent within view.
        candidates = [
            a for a in world.agents.values()
            if getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
            and float(getattr(a, "fear", 0.0)) >= 30.0
        ]
        if candidates:
            target = max(candidates, key=lambda a: float(getattr(a, "fear", 0.0)))
            sx = target.x + rng.uniform(-30, 30)
            sy = target.y + rng.uniform(-30, 30)
            sid = f"boywhite_{world.tick_count}_{rng.randint(0, 9999)}"
            world.supernaturals.append(BoyInWhite(sid, sx, sy, target.id))
            world.emit(
                Event(
                    tick=world.tick_count,
                    type="boy_in_white",
                    subject=target.id,
                    detail="visited by the boy in white",
                    severity="info",
                )
            )

    # --- Faraway Tree portal (rare, mostly at night/dusk/dawn) ---
    tree_bias = 1.6 if phase in (Phase.NIGHT, Phase.DUSK, Phase.DAWN) else 0.3
    if rng.random() < _P_FARAWAY * tree_bias:
        tx, ty = rng.choice(FARAWAY_TREES)
        sid = f"faraway_{world.tick_count}_{rng.randint(0, 9999)}"
        world.supernaturals.append(FarawayTreePortal(sid, float(tx), float(ty)))

    # --- Anghkooey (gated on active Faraway Tree) ---
    if _any_faraway_active(world.supernaturals) and rng.random() < _P_ANGHKOOEY:
        # Spawn near one of the active portals.
        portals = [s for s in world.supernaturals if isinstance(s, FarawayTreePortal)]
        portal = rng.choice(portals)
        sx = portal.x + rng.uniform(-40, 40)
        sy = portal.y + rng.uniform(-40, 40)
        sid = f"anghk_{world.tick_count}_{rng.randint(0, 9999)}"
        world.supernaturals.append(Anghkooey(sid, sx, sy))


def spawn_glitch_marker(world: World, agent) -> Optional[Agent]:
    """Helper used by fear.py to attach a transient glitch sprite to an agent.

    Returns the marker (also appended to ``world.supernaturals``) so the caller
    can hold a reference if it wants to track it.
    """
    marker = FarawayTreePortal(
        sid=f"glitch_{agent.id}_{world.tick_count}",
        x=float(agent.x),
        y=float(agent.y),
    )
    # Repurpose marker_class for the glitch overlay so the UI knows.
    marker.marker_class = MarkerClass.FARAWAY_TREE
    marker.snatch_attempted = True  # don't try to abduct on a glitch marker
    marker.ticks_left = 12
    world.supernaturals.append(marker)
    return marker
