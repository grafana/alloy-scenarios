"""
v6 — Car agent.

Cars are the second vehicle in the From simulation, alongside the Bus. A car
drives in along the same S-curve as the bus, parks at a slightly different
spur point (``CAR_PARK_XY``), drops off exactly one NPC arrival, attempts to
leave, and reliably breaks down after a couple of outbound waypoints. The
broken-down hulk becomes a permanent wreck in ``world.legacy.permanent_wrecks``
(capped FIFO at ``MAX_PERMANENT_WRECKS``) so long-running sessions visibly
accumulate scars from past arrivals.

Public surface:

  * ``Car(Agent)``            — the agent class, lives in ``world.supernaturals``.
  * ``spawn_car(world, npc_id)``  — entry point for ``population.py`` to flip a
                                   foot-arrival roll into a car-arrival roll.
  * ``tick_cars(world)``       — engine hook; drives every live Car forward.

The Car re-uses ``CAR_PATH_IN`` / ``CAR_PARK_XY`` / ``CAR_PATH_OUT`` from
contracts; speed mirrors the bus at 6 px/tick.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import legacy as _legacy
from contracts import (
    Agent,
    AgentKind,
    CAR_BREAKDOWN_AFTER_WAYPOINTS,
    CAR_PARK_XY,
    CAR_PATH_IN,
    CAR_PATH_OUT,
    Event,
    MAX_PERMANENT_WRECKS,
    MarkerClass,
    World,
)


# --- tunables -------------------------------------------------------------

_CAR_SPEED_PX = 6.0
_CAR_PARK_DWELL_TICKS = 30  # how long the car sits parked while the NPC alights

# Sub-state strings (kept narrow to this module; not the global State enum).
_STATE_INBOUND = "INBOUND"
_STATE_PARKED = "PARKED"
_STATE_OUTBOUND = "OUTBOUND"
_STATE_BROKEN = "BROKEN"


# Module-local id counter so Car ids never collide across arrivals.
_CAR_COUNTER = {"n": 0}


def _next_car_id(world: World) -> str:
    _CAR_COUNTER["n"] += 1
    return f"car_{world.cycle_number}_{_CAR_COUNTER['n']}"


def _step_toward(
    x: float, y: float, tx: float, ty: float, step: float
) -> Tuple[float, float, bool]:
    """Return (new_x, new_y, arrived). Mirrors bus.py."""
    dx = tx - x
    dy = ty - y
    d = math.hypot(dx, dy)
    if d <= step or d == 0.0:
        return tx, ty, True
    return x + dx * (step / d), y + dy * (step / d), False


class Car(Agent):
    """A survivor's arrival car. Drives in, drops one passenger, breaks down.

    Lives in ``world.supernaturals`` and ticks once per engine tick via
    ``tick_cars``. The car is removed from supernaturals at the BROKEN
    transition; its final (x, y) plus the current cycle number become a row
    in ``world.legacy.permanent_wrecks``.
    """

    kind = AgentKind.SUPERNATURAL  # closest-fit existing kind; mirrors the bus
    marker_class = MarkerClass.CAR

    def __init__(
        self,
        car_id: str,
        passenger_npc_id: Optional[str],
        x: float,
        y: float,
    ) -> None:
        self.id = car_id
        self.passenger_npc_id = passenger_npc_id
        self.x = float(x)
        self.y = float(y)
        self.substate: str = _STATE_INBOUND
        self.path_index: int = 0
        self.parked_for_ticks: int = 0
        # Count outbound waypoints completed so we can trigger breakdown.
        self.outbound_waypoints_done: int = 0

    # --- snapshot ----------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update(
            {
                "substate": self.substate,
                "passenger": self.passenger_npc_id,
                "path_index": self.path_index,
            }
        )
        return d

    # --- tick is the no-op; tick_cars() drives the Car via _step() ---------
    def tick(self, world: World) -> None:  # pragma: no cover - driven externally
        # Cars are driven by ``tick_cars(world)`` so the engine wiring stays
        # explicit (mirrors how the bus works). The Agent ABC requires this
        # method to exist, hence the no-op.
        pass

    # --- internal: one step of the state machine ---------------------------
    def step(self, world: World) -> None:
        if self.substate == _STATE_INBOUND:
            self._step_inbound(world)
        elif self.substate == _STATE_PARKED:
            self._step_parked(world)
        elif self.substate == _STATE_OUTBOUND:
            self._step_outbound(world)
        # BROKEN is terminal and only encountered for one final tick before the
        # Car is removed from supernaturals; nothing to do here.

    def _step_inbound(self, world: World) -> None:
        if self.path_index >= len(CAR_PATH_IN):
            # Snap to the park slot and transition to PARKED.
            self.x, self.y = CAR_PARK_XY
            self._transition_parked(world)
            return
        tx, ty = CAR_PATH_IN[self.path_index]
        new_x, new_y, arrived = _step_toward(self.x, self.y, tx, ty, _CAR_SPEED_PX)
        self.x, self.y = new_x, new_y
        if arrived:
            self.path_index += 1
            if self.path_index >= len(CAR_PATH_IN):
                # Snap to park slot on the same tick we exhaust the waypoints.
                self.x, self.y = CAR_PARK_XY
                self._transition_parked(world)

    def _step_parked(self, world: World) -> None:
        self.parked_for_ticks += 1
        # The car is anchored at the park slot.
        self.x, self.y = CAR_PARK_XY
        if self.parked_for_ticks >= _CAR_PARK_DWELL_TICKS:
            self._transition_outbound(world)

    def _step_outbound(self, world: World) -> None:
        if self.path_index >= len(CAR_PATH_OUT):
            # Ran the whole out-path without breaking down — that means the
            # breakdown threshold was higher than the path length. Treat as
            # a graceful departure: remove the car without registering a
            # wreck. (With the defaults, this branch is unreachable.)
            self._depart_clean(world)
            return
        tx, ty = CAR_PATH_OUT[self.path_index]
        new_x, new_y, arrived = _step_toward(self.x, self.y, tx, ty, _CAR_SPEED_PX)
        self.x, self.y = new_x, new_y
        if arrived:
            self.path_index += 1
            self.outbound_waypoints_done += 1
            # Break down after the configured number of outbound waypoints.
            if self.outbound_waypoints_done >= CAR_BREAKDOWN_AFTER_WAYPOINTS:
                self._transition_broken(world)

    # --- transitions -------------------------------------------------------
    def _transition_parked(self, world: World) -> None:
        self.substate = _STATE_PARKED
        self.parked_for_ticks = 0
        # Snapshot the parked location.
        self.x, self.y = CAR_PARK_XY
        # Flag the pending NPC so population.py can alight them this tick.
        if self.passenger_npc_id is not None:
            world.car_pending_npc_id = self.passenger_npc_id
        world.emit(
            Event(
                tick=world.tick_count,
                type="car_arrival",
                subject=self.id,
                detail=(
                    f"a battered car pulled up — dropping off "
                    f"{self.passenger_npc_id or 'someone'}"
                ),
                severity="info",
            )
        )
        try:
            # Resolve the passenger's display name so the journal entry uses
            # "Lemuel stepped out", not the literal "{name} stepped out".
            passenger_name = "Someone"
            if self.passenger_npc_id is not None:
                npc = world.agents.get(self.passenger_npc_id)
                if npc is not None:
                    passenger_name = getattr(npc, "name", None) or self.passenger_npc_id
            _legacy.record(world, "car_arrival", name=passenger_name, car=self.id)
        except Exception:
            pass

    def _transition_outbound(self, world: World) -> None:
        self.substate = _STATE_OUTBOUND
        self.path_index = 0
        self.outbound_waypoints_done = 0
        world.emit(
            Event(
                tick=world.tick_count,
                type="car_departure",
                subject=self.id,
                detail="the car tried to leave town",
                severity="info",
            )
        )

    def _transition_broken(self, world: World) -> None:
        self.substate = _STATE_BROKEN
        # Register the wreck on legacy with FIFO eviction. The frontend reads
        # ``world.legacy.permanent_wrecks`` directly via snapshot_dict.
        cycle = world.cycle_number
        world.legacy.permanent_wrecks.append((float(self.x), float(self.y), int(cycle)))
        if len(world.legacy.permanent_wrecks) > MAX_PERMANENT_WRECKS:
            world.legacy.permanent_wrecks.pop(0)
        world.emit(
            Event(
                tick=world.tick_count,
                type="car_broke_down",
                subject=self.id,
                detail=f"the car broke down at ({self.x:.0f},{self.y:.0f})",
                severity="warn",
            )
        )
        try:
            _legacy.record(world, "car_broke_down", car=self.id)
        except Exception:
            pass
        # Yank from supernaturals so the moving marker disappears; the wreck
        # is rendered as a separate static layer by the frontend from the
        # legacy list.
        _remove_car(world, self.id)
        # Clear the active-car slot so the next arrival roll is free.
        world.active_car_id = None

    def _depart_clean(self, world: World) -> None:
        """Unreachable with default CAR_BREAKDOWN_AFTER_WAYPOINTS, but safe."""
        world.emit(
            Event(
                tick=world.tick_count,
                type="car_departure",
                subject=self.id,
                detail="the car drove out of town",
                severity="info",
            )
        )
        _remove_car(world, self.id)
        world.active_car_id = None


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _find_car(world: World, car_id: str) -> Optional[Car]:
    for s in world.supernaturals:
        if isinstance(s, Car) and s.id == car_id:
            return s
    return None


def _remove_car(world: World, car_id: str) -> None:
    world.supernaturals[:] = [
        s for s in world.supernaturals
        if not (isinstance(s, Car) and s.id == car_id)
    ]


# ---------------------------------------------------------------------------
# Public — spawn a car (called by population.py)
# ---------------------------------------------------------------------------


def spawn_car(world: World, npc_id: Optional[str]) -> Car:
    """Create a Car and register it as the world's active arrival vehicle.

    The car starts at the first waypoint of ``CAR_PATH_IN`` so it visibly
    rolls in from the road edge. The passenger NPC id is held on the Car;
    when the car parks, ``world.car_pending_npc_id`` is set so population.py
    can alight the passenger that same tick.
    """
    if CAR_PATH_IN:
        x, y = CAR_PATH_IN[0]
    else:
        x, y = CAR_PARK_XY

    car = Car(
        car_id=_next_car_id(world),
        passenger_npc_id=npc_id,
        x=x,
        y=y,
    )
    world.supernaturals.append(car)
    world.active_car_id = car.id
    return car


# ---------------------------------------------------------------------------
# Public — tick driver
# ---------------------------------------------------------------------------


def tick_cars(world: World) -> None:
    """Engine hook — drives every live Car one step.

    Safe to call when no Car is live (cheap no-op). Honours the world's
    ``active_car_id`` slot for end-of-life housekeeping.
    """
    # Iterate over a snapshot so transitions that pop from supernaturals
    # don't break the loop.
    for s in list(world.supernaturals):
        if isinstance(s, Car):
            try:
                s.step(world)
            except Exception:
                # Step failures must never kill the tick. Log via the event
                # emitter so we still get a breadcrumb.
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="tick_warn",
                        subject=getattr(s, "id", "car_unknown"),
                        detail="car step failed",
                        severity="warn",
                    )
                )

    # Defensive: if our ``active_car_id`` no longer corresponds to anything
    # in supernaturals (e.g. a hot-reload wiped the list), clear it.
    if world.active_car_id is not None and _find_car(world, world.active_car_id) is None:
        world.active_car_id = None
