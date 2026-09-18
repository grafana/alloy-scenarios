"""
v8 — Survivor-driven house construction.

When the existing residences fill up (residents == capacity on every house in
NPC_HOME_BUILDINGS) and at least one new arrival is homeless, the village
needs to put up another roof. Engineers (Jim's role) and any character in
``State.REPAIRING`` near an empty lot accumulate progress; once a lot
crosses ``CONSTRUCTION_THRESHOLD`` it becomes a real ``Building`` and the
homeless can claim it as ``home_id``.

Pure additive module. Reads ``world.agents`` + ``world.buildings`` +
``EMPTY_LOTS`` + ``world.construction_progress``. Writes
``world.buildings`` and ``world.consumed_lots``. Emits
``construction_started``, ``construction_progress``, ``house_built``.

Ownership: Agent A (engine) tick this once per sim tick AFTER agents have
moved, so the proximity check sees the latest positions.
"""

from __future__ import annotations

from typing import List, Optional

from contracts import (
    AgentKind,
    Building,
    CONSTRUCTION_PER_TICK,
    CONSTRUCTION_RADIUS_PX,
    CONSTRUCTION_THRESHOLD,
    EMPTY_LOTS,
    Event,
    NEW_HOUSE_CAPACITY,
    Phase,
    Role,
    State,
    Status,
    World,
)
from agents.base import distance


def _homeless_count(world: World) -> int:
    """Living NPCs with no ``home_id`` assigned."""
    return sum(
        1 for a in world.agents.values()
        if getattr(a, "kind", None) == AgentKind.NPC
        and getattr(a, "status", Status.ACTIVE) == Status.ACTIVE
        and getattr(a, "home_id", None) is None
    )


def _builders_near(world: World, x: float, y: float) -> int:
    """Count survivors who count as 'on site' for a lot at (x, y).

    Engineers (the canonical builder role) count regardless of state. Any
    other CHARACTER in REPAIRING state also counts, so a desperate town
    can press whoever's available into rebuilding. NPCs themselves don't
    build — they don't have the right state machine for it.
    """
    n = 0
    for a in world.agents.values():
        if getattr(a, "kind", None) != AgentKind.CHARACTER:
            continue
        if getattr(a, "status", Status.ACTIVE) != Status.ACTIVE:
            continue
        if distance(a, type("Pt", (), {"x": x, "y": y})()) > CONSTRUCTION_RADIUS_PX:
            continue
        if getattr(a, "role", None) == Role.ENGINEER:
            n += 1
        elif getattr(a, "state", None) == State.REPAIRING:
            n += 1
    return n


def _emit_progress(world: World, lot_id: str, progress: float) -> None:
    """Emit a sparse progress event when a multiple of 20 is crossed."""
    last = int(world.construction_progress.get(f"{lot_id}::_last_emit", 0))
    current_bucket = int(progress // 20)
    if current_bucket > last:
        world.construction_progress[f"{lot_id}::_last_emit"] = float(current_bucket)
        pct = min(100, int(progress * 100.0 / CONSTRUCTION_THRESHOLD))
        world.emit(Event(
            tick=world.tick_count,
            type="construction_progress",
            subject=lot_id,
            detail=f"new house at {lot_id} — {pct}% complete",
            severity="info",
        ))


def _convert_lot_to_building(world: World, lot_id: str, x: float, y: float) -> None:
    """Replace an empty lot with a fresh Building in ``world.buildings``."""
    # Pick a unique name: built_house_<seq>
    seq = sum(
        1 for b in world.buildings.values()
        if b.id.startswith("built_house_")
    ) + 1
    bid = f"built_house_{seq}"
    name = f"New House {seq}"
    new_b = Building(
        id=bid,
        name=name,
        x=float(x),
        y=float(y),
        footprint=NEW_HOUSE_CAPACITY,
        has_talisman=False,
        role_tag="house",
        locked=False,
        original_talisman=False,
    )
    world.buildings[bid] = new_b
    world.consumed_lots.add(lot_id)
    # Drop progress entries for this lot.
    world.construction_progress.pop(lot_id, None)
    world.construction_progress.pop(f"{lot_id}::_last_emit", None)

    # Add the new building to the NPC home pool so pick_home_id will find
    # it next tick. We splice it before the small-houses block so it gets
    # picked up roughly proportionally.
    try:
        from contracts import NPC_HOME_BUILDINGS
        if bid not in NPC_HOME_BUILDINGS:
            NPC_HOME_BUILDINGS.append(bid)
    except Exception:
        pass

    world.emit(Event(
        tick=world.tick_count,
        type="house_built",
        subject=bid,
        detail=f"{name} raised on lot {lot_id} — survivors carved out new room",
        severity="info",
    ))


def tick_construction(world: World) -> None:
    """Engine hook — called once per tick after agents have moved.

    Construction only progresses during DAY (the village rests at night).
    Without homeless NPCs there's no demand, so we skip the proximity
    sweep entirely — keeps the per-tick cost down.
    """
    if world.time.phase != Phase.DAY:
        return
    homeless = _homeless_count(world)
    if homeless <= 0:
        return

    # Pick the first lot that hasn't been consumed yet. Building one house
    # at a time keeps the visible cadence readable.
    target_lot: Optional[tuple] = None
    for lot_id, lx, ly in EMPTY_LOTS:
        if lot_id in world.consumed_lots:
            continue
        target_lot = (lot_id, lx, ly)
        break
    if target_lot is None:
        # All lots consumed — survivors can't expand further. Hard cap.
        return

    lot_id, lx, ly = target_lot
    builders = _builders_near(world, lx, ly)
    if builders <= 0:
        # No one on site. Don't emit anything; a future tick might pick up.
        return

    progress = float(world.construction_progress.get(lot_id, 0.0))
    if progress == 0.0:
        # First builder showed up — announce so the player notices.
        world.emit(Event(
            tick=world.tick_count,
            type="construction_started",
            subject=lot_id,
            detail=f"construction has begun on lot {lot_id}",
            severity="info",
        ))
    progress += CONSTRUCTION_PER_TICK * builders
    world.construction_progress[lot_id] = progress
    _emit_progress(world, lot_id, progress)

    if progress >= CONSTRUCTION_THRESHOLD:
        _convert_lot_to_building(world, lot_id, lx, ly)
