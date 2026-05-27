"""
The Bus and the Outsiders — visitors from the world that supposedly exists
outside the trees.

A bus rolls into town on a long cycle cadence (``config.bus_arrival_cycle_interval``,
default every 5 cycles, gated on D1 noon of a fresh cycle). It carries 1-3
Outsiders, each with a tiny backstory and a single goal that drives their
target-picking behaviour. They walk around for ``config.bus_stay_ticks`` and
then the bus rolls back out the other side of town; any Outsider still alive
gets back on, anyone dead becomes a journal fragment.

Outsiders are NPC-ish but distinct: they have ``AgentKind.OUTSIDER``, a
different marker class, and pursue ``State.OUTSIDER_GOAL`` instead of the
NPC working/socialising FSM. They never become Yellow Man tendrils.

Public surface:
    * ``Outsider``           — Agent subclass.
    * ``tick_bus(world)``    — engine hook, call once per tick.
    * ``clear_outsiders``    — drop every outsider; safe to call lazily.

Wiring contract for the simulation engine (Agent A): call ``tick_bus(world)``
once per tick, ideally before ``tick_population`` so that any survivors who
boarded the bus are gone from ``world.agents`` before the population reaper
runs.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from contracts import (
    Agent,
    AgentKind,
    BUS_PARK,
    BUS_PATH_IN,
    BUS_PATH_OUT,
    Event,
    FARAWAY_TREES,
    MarkerClass,
    Metric,
    State,
    Status,
    World,
)
import legacy


# ---------------------------------------------------------------------------
# Backstories — used to seed the Outsiders that step off each bus.
# ---------------------------------------------------------------------------

# (name_seed, backstory, goal). The goal string drives _pick_outsider_target.
_BACKSTORIES: List[Tuple[str, str, str]] = [
    ("Sarah",       "doctor returning to Boston",                     "examine the talismans"),
    ("Mike",        "journalist tracking the missing-persons cluster", "interview Khatri"),
    ("Charlie",     "Vietnam vet looking for his brother",            "find the radio tower"),
    ("Eleanor",     "schoolteacher from Tarrytown",                   "talk to the children"),
    ("Marcus",      "trucker who took a wrong turn",                  "leave on the next bus"),
    ("Father Holt", "another priest",                                 "examine the talismans"),
]


def _disambiguate_name(world: World, seed: str) -> str:
    """If ``seed`` collides with an existing agent name, suffix it."""
    existing = {getattr(a, "name", None) for a in world.agents.values()}
    if seed not in existing:
        return seed
    # Match the npcs.py house style (II, III, ...).
    romans = ["II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    for tag in romans:
        cand = f"{seed} {tag}"
        if cand not in existing:
            return cand
    return f"{seed} {world.rng.randint(2, 999)}"


# ---------------------------------------------------------------------------
# Module-local id counter so Outsider ids never collide across arrivals.
# ---------------------------------------------------------------------------

_OUTSIDER_COUNTER = {"n": 0}


def _next_outsider_id(world: World) -> str:
    _OUTSIDER_COUNTER["n"] += 1
    return f"outsider_{world.cycle_number}_{_OUTSIDER_COUNTER['n']}"


# ---------------------------------------------------------------------------
# Outsider — Agent subclass
# ---------------------------------------------------------------------------


class Outsider(Agent):
    """A visitor from beyond the trees. Pursues a single backstory goal."""

    kind = AgentKind.OUTSIDER
    marker_class = MarkerClass.OUTSIDER

    def __init__(
        self,
        outsider_id: str,
        name: str,
        backstory: str,
        goal: str,
        arrives_at_tick: int,
        leaves_at_tick: int,
        x: float,
        y: float,
    ) -> None:
        self.id = outsider_id
        self.name = name
        self.backstory = backstory
        self.goal = goal
        self.arrives_at_tick = arrives_at_tick
        self.leaves_at_tick = leaves_at_tick
        self.x = float(x)
        self.y = float(y)
        self.target_x = float(x)
        self.target_y = float(y)
        self.status: Status = Status.ACTIVE
        self.state: State = State.OUTSIDER_GOAL
        self.fear: float = 0.0
        self.sanity: float = 80.0
        # Re-target cooldown so the outsider doesn't thrash every tick.
        self._retarget_at_tick: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "name": self.name,
                "backstory": self.backstory,
                "goal": self.goal,
                "state": self.state.value,
                "status": self.status.value,
                "fear": round(self.fear, 2),
                "sanity": round(self.sanity, 2),
                "leaves_in": max(0, self.leaves_at_tick - 0),  # filled by snapshot if needed
                "target_x": round(self.target_x, 2),
                "target_y": round(self.target_y, 2),
            }
        )
        return d

    # ------------------------------------------------------------- targeting

    def _pick_target(self, world: World) -> Tuple[float, float]:
        """Pick a target based on the outsider's goal."""
        rng = world.rng
        goal = (self.goal or "").lower()

        if "khatri" in goal:
            khatri = world.agents.get("Khatri")
            if khatri is not None and getattr(khatri, "status", Status.ACTIVE) == Status.ACTIVE:
                return (khatri.x + rng.uniform(-15, 15), khatri.y + rng.uniform(-15, 15))
            # Fallback: church (Khatri's haunt).
            for b in world.buildings.values():
                if b.role_tag == "church":
                    return (b.x + rng.uniform(-20, 20), b.y + rng.uniform(20, 40))

        if "talisman" in goal:
            talismans = [b for b in world.buildings.values() if b.has_talisman]
            if talismans:
                b = rng.choice(talismans)
                return (b.x + rng.uniform(-25, 25), b.y + rng.uniform(20, 45))

        if "radio tower" in goal or "tower" in goal:
            # No actual tower in the map — wander between Faraway Trees as the
            # next-best "looking for the edge of the world" behaviour.
            if FARAWAY_TREES:
                tx, ty = rng.choice(FARAWAY_TREES)
                return (tx + rng.uniform(-30, 30), ty + rng.uniform(-30, 30))

        if "children" in goal or "child" in goal:
            # Drift toward the Matthews house — where the show's children live.
            for b in world.buildings.values():
                if b.role_tag == "matthews":
                    return (b.x + rng.uniform(-25, 25), b.y + rng.uniform(20, 45))

        if "next bus" in goal or "leave" in goal:
            # Stand near the parked bus.
            return (world.bus.x + rng.uniform(-25, 25), world.bus.y + rng.uniform(20, 45))

        # Default: jitter near current position.
        return (self.x + rng.uniform(-40, 40), self.y + rng.uniform(-40, 40))

    # ----------------------------------------------------------------- tick

    def tick(self, world: World) -> None:
        if self.status != Status.ACTIVE:
            return

        # If our exit tick has arrived, mark ABSENT so the bus loop collects us.
        if world.tick_count >= self.leaves_at_tick:
            self.status = Status.ABSENT
            return

        # We haven't actually walked off the bus yet — wait.
        if world.tick_count < self.arrives_at_tick:
            return

        # (Re)pick a target if arrived or cooldown elapsed.
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        d = math.hypot(dx, dy)
        if d < 4.0 or world.tick_count >= self._retarget_at_tick:
            tx, ty = self._pick_target(world)
            self.target_x = tx
            self.target_y = ty
            self._retarget_at_tick = world.tick_count + world.rng.randint(40, 100)

        # Step toward target.
        step = 4.0
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        d = math.hypot(dx, dy)
        if d > step and d > 0.0:
            self.x += dx * (step / d)
            self.y += dy * (step / d)
        else:
            self.x = self.target_x
            self.y = self.target_y


# ---------------------------------------------------------------------------
# Bus marker — purely a render hint; the bus state lives on ``world.bus``.
# ---------------------------------------------------------------------------


class _BusMarker:
    """``Agent``-shaped object so the frontend can render the bus dot.

    We don't subclass ``Agent`` because the bus doesn't tick autonomously —
    ``tick_bus`` drives ``world.bus`` directly and the marker mirrors that.
    """

    kind = AgentKind.SUPERNATURAL  # closest-fit existing kind for snapshot
    marker_class = MarkerClass.BUS

    def __init__(self, x: float, y: float) -> None:
        self.id = "bus_marker"
        self.x = float(x)
        self.y = float(y)

    def tick(self, world: World) -> None:  # pragma: no cover - driven externally
        pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "marker_class": self.marker_class.value,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
        }


def _ensure_bus_marker(world: World) -> _BusMarker:
    """Find or spawn the bus marker in ``world.supernaturals``."""
    for s in world.supernaturals:
        if getattr(s, "id", None) == "bus_marker":
            return s  # type: ignore[return-value]
    marker = _BusMarker(world.bus.x, world.bus.y)
    world.supernaturals.append(marker)
    return marker


def _remove_bus_marker(world: World) -> None:
    world.supernaturals[:] = [
        s for s in world.supernaturals if getattr(s, "id", None) != "bus_marker"
    ]


# ---------------------------------------------------------------------------
# Public: clear outsiders (called lazily when bus is inactive).
# ---------------------------------------------------------------------------


def clear_outsiders(world: World) -> None:
    """Drop every Outsider from ``world.agents`` and reset the id counter.

    Safe to call between cycles or whenever the bus is inactive — sweeps
    leftover outsider ids without emitting any event.
    """
    out_ids = [
        a.id for a in list(world.agents.values())
        if getattr(a, "kind", None) == AgentKind.OUTSIDER
    ]
    for oid in out_ids:
        world.agents.pop(oid, None)
    world.bus.passengers.clear()
    _remove_bus_marker(world)
    _OUTSIDER_COUNTER["n"] = 0


# ---------------------------------------------------------------------------
# Bus internals
# ---------------------------------------------------------------------------


_BUS_SPEED_PX = 6.0


def _step_toward(x: float, y: float, tx: float, ty: float, step: float) -> Tuple[float, float, bool]:
    """Return new (x, y, arrived)."""
    dx = tx - x
    dy = ty - y
    d = math.hypot(dx, dy)
    if d <= step or d == 0.0:
        return tx, ty, True
    return x + dx * (step / d), y + dy * (step / d), False


def _pick_backstories(world: World, n: int) -> List[Tuple[str, str, str]]:
    """Pick ``n`` distinct backstory tuples for this arrival."""
    pool = list(_BACKSTORIES)
    world.rng.shuffle(pool)
    return pool[: max(1, min(n, len(pool)))]


def _begin_arrival(world: World) -> None:
    """Roll the bus onto the dirt road, spawn 1-3 outsiders, schedule next arrival."""
    cfg = world.config
    rng = world.rng
    bus = world.bus

    bus.active = True
    bus.arrival_tick = world.tick_count
    bus.departure_tick = world.tick_count + cfg.bus_stay_ticks
    bus.path_index = 0
    if BUS_PATH_IN:
        bus.x, bus.y = BUS_PATH_IN[0]
    bus.passengers.clear()
    # Clear any leftover departure sentinel from a prior visit.
    if hasattr(bus, "_departing"):
        try:
            delattr(bus, "_departing")
        except AttributeError:
            pass

    # Reset the marker.
    _remove_bus_marker(world)
    _ensure_bus_marker(world)

    # Schedule the next visit relative to legacy cycles witnessed.
    bus.next_arrival_cycle = (
        world.legacy.cycles_witnessed + cfg.bus_arrival_cycle_interval
    )

    # Spawn 1-3 outsiders.
    n_outsiders = rng.randint(1, 3)
    picks = _pick_backstories(world, n_outsiders)
    arrive_at = world.tick_count + 10
    leave_at = bus.departure_tick - 10
    spawned: List[Outsider] = []
    for seed, backstory, goal in picks:
        name = _disambiguate_name(world, seed)
        oid = _next_outsider_id(world)
        # Start them at the parked-bus location; they only "appear" after arrive_at.
        ox, oy = BUS_PARK
        ox += rng.uniform(-6, 6)
        oy += rng.uniform(8, 18)
        outsider = Outsider(
            outsider_id=oid,
            name=name,
            backstory=backstory,
            goal=goal,
            arrives_at_tick=arrive_at,
            leaves_at_tick=leave_at,
            x=ox,
            y=oy,
        )
        world.agents[oid] = outsider
        bus.passengers.append(oid)
        spawned.append(outsider)

    world.emit(
        Event(
            tick=world.tick_count,
            type="bus_arrival",
            subject="bus",
            detail=f"the bus rolled in with {len(spawned)} passengers",
            severity="info",
        )
    )
    for o in spawned:
        world.emit(
            Event(
                tick=world.tick_count,
                type="outsider_joined",
                subject=o.id,
                detail=f"{o.name} — {o.backstory}; goal: {o.goal}",
                severity="info",
            )
        )


def _drive_in(world: World) -> None:
    """Step the bus along BUS_PATH_IN."""
    bus = world.bus
    if bus.path_index >= len(BUS_PATH_IN):
        # Sit at BUS_PARK.
        bus.x, bus.y = BUS_PARK
        marker = _ensure_bus_marker(world)
        marker.x, marker.y = bus.x, bus.y
        return

    tx, ty = BUS_PATH_IN[bus.path_index]
    new_x, new_y, arrived = _step_toward(bus.x, bus.y, tx, ty, _BUS_SPEED_PX)
    bus.x, bus.y = new_x, new_y
    if arrived:
        bus.path_index += 1
    marker = _ensure_bus_marker(world)
    marker.x, marker.y = bus.x, bus.y


def _drive_out(world: World) -> None:
    """Drive the bus along BUS_PATH_OUT; on completion, collect passengers."""
    bus = world.bus
    # path_index resets to 0 when departure begins; we track via a sentinel:
    # we re-use ``path_index`` after departure (since drive-in is complete by then).
    if bus.path_index < len(BUS_PATH_OUT):
        tx, ty = BUS_PATH_OUT[bus.path_index]
        new_x, new_y, arrived = _step_toward(bus.x, bus.y, tx, ty, _BUS_SPEED_PX)
        bus.x, bus.y = new_x, new_y
        if arrived:
            bus.path_index += 1
        marker = _ensure_bus_marker(world)
        marker.x, marker.y = bus.x, bus.y
        return

    # Path complete — collect survivors and depart.
    survivors: List[Outsider] = []
    for oid in list(bus.passengers):
        agent = world.agents.get(oid)
        if isinstance(agent, Outsider) and agent.status in (Status.ACTIVE, Status.ABSENT):
            survivors.append(agent)
            world.agents.pop(oid, None)

    for o in survivors:
        world.emit(
            Event(
                tick=world.tick_count,
                type="outsider_left",
                subject=o.id,
                detail=f"{o.name} boarded the bus out of town",
                severity="info",
            )
        )

    world.emit(
        Event(
            tick=world.tick_count,
            type="bus_depart",
            subject="bus",
            detail=f"the bus left with {len(survivors)} passenger(s)",
            severity="info",
        )
    )

    # Reset bus state.
    bus.active = False
    bus.passengers.clear()
    bus.path_index = 0
    bus.arrival_tick = 0
    bus.departure_tick = 0
    if hasattr(bus, "_departing"):
        try:
            delattr(bus, "_departing")
        except AttributeError:
            pass
    _remove_bus_marker(world)


def _begin_departure(world: World) -> None:
    """Flip the bus into drive-out mode.

    We use a sentinel attribute ``_departing`` on ``world.bus`` (set via
    ``setattr``) to distinguish drive-in from drive-out phases, since both
    re-use ``path_index``.
    """
    bus = world.bus
    bus.path_index = 0
    # Snap to the parked location to start the outbound run cleanly.
    bus.x, bus.y = BUS_PARK
    setattr(bus, "_departing", True)


def _reap_dead_outsiders(world: World) -> None:
    """Sweep DEAD outsiders, emit event + journal."""
    dead_ids: List[str] = []
    for a in list(world.agents.values()):
        if getattr(a, "kind", None) != AgentKind.OUTSIDER:
            continue
        if getattr(a, "status", Status.ACTIVE) == Status.DEAD:
            dead_ids.append(a.id)

    for oid in dead_ids:
        outsider = world.agents.pop(oid, None)
        if outsider is None:
            continue
        name = getattr(outsider, "name", oid)
        goal = getattr(outsider, "goal", "something they would not say")
        # Drop from passenger list — they will not be boarding.
        if oid in world.bus.passengers:
            world.bus.passengers.remove(oid)
        world.emit(
            Event(
                tick=world.tick_count,
                type="outsider_died",
                subject=oid,
                detail=f"{name} did not get back on the bus",
                severity="warn",
            )
        )
        try:
            legacy.record(world, "outsider_died", name=name, goal=goal)
        except Exception:
            # Journal failure must never break the tick.
            pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _count_active_outsiders(world: World) -> int:
    return sum(
        1
        for a in world.agents.values()
        if getattr(a, "kind", None) == AgentKind.OUTSIDER
        and getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
    )


def tick_bus(world: World) -> None:
    """Engine hook — call once per tick.

    Drives the bus state machine:

        1. If bus inactive and the cycle/D1-noon conditions are met -> arrive.
        2. If bus inactive and stray outsiders remain -> lazily sweep them.
        3. While active: drive in / park / drive out.
        4. Always: reap any newly DEAD outsiders + update telemetry gauge.
    """
    cfg = world.config
    bus = world.bus

    if not bus.active:
        # Decide whether to arrive.
        ready = (
            world.legacy.cycles_witnessed >= bus.next_arrival_cycle
            and world.time.day == 1
            and world.time.hour == 12
        )
        if ready:
            _begin_arrival(world)
        else:
            # Lazy sweep — if the bus isn't here, no outsider should be either.
            stragglers = [
                a.id for a in list(world.agents.values())
                if getattr(a, "kind", None) == AgentKind.OUTSIDER
            ]
            if stragglers:
                clear_outsiders(world)

    else:
        # Active — drive the state machine.
        departing = bool(getattr(bus, "_departing", False))

        if departing:
            _drive_out(world)
        elif world.tick_count >= bus.departure_tick:
            # Departure tick hit. Fast-forward through any remaining drive-in
            # waypoints (so the bus visibly leaves rather than vanishing).
            _begin_departure(world)
            _drive_out(world)
        else:
            _drive_in(world)

    # Always reap dead outsiders + update gauge.
    _reap_dead_outsiders(world)
    if world.telemetry is not None:
        world.telemetry.gauge_set(
            Metric.OUTSIDERS_ACTIVE,
            float(_count_active_outsiders(world)),
        )
