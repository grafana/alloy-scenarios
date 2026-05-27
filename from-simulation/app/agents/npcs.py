"""
NPC agents — the unnamed villagers that drift in from the forest.

NPCs have a deliberately thin behavioural surface compared to the named
characters owned by Agent B. They cycle through a three-state mini FSM:

    WORKING  -> SOCIALIZING -> SHELTERING

They pick targets near building entrances during the day, gossip at dusk,
and shelter at night. NPCs in ``world.yellow_touched_npcs`` are subtly
puppeted by the Man in Yellow: at DUSK they drift toward children-of-Matthews
and the Sheriff house; at NIGHT they linger near talisman-protected doors,
which slowly increases the awareness of nearby characters (Agent B reads the
proximity from the snapshot — we just position the pieces).

Population spawning and death cleanup is handled by ``population.py``.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from contracts import (
    Agent,
    AgentKind,
    MarkerClass,
    Phase,
    State,
    Status,
    World,
)


# 40 name pool — these are deliberately generic, frontier-flavoured first names.
# Suffixes are appended on collision (e.g. "Cora", "Cora II").
_NAME_POOL = [
    "Cora", "Wyatt", "Hazel", "Silas", "Mabel", "Otis", "Della", "Roscoe",
    "Pearl", "Earl", "Edith", "Hank", "Vera", "Cletus", "Maeve", "Burl",
    "Ida", "Floyd", "Junie", "Mort", "Nellie", "Cyrus", "Opal", "Reuben",
    "Tess", "Asa", "Lula", "Jonas", "Greta", "Lemuel", "Bessie", "Caleb",
    "Inez", "Dorsey", "Polly", "Eustace", "Beulah", "Wendell", "Sadie", "Orin",
]


def _suffix_for(n: int) -> str:
    """Return a roman-numeral-ish suffix for the n-th re-use of a name (0-indexed)."""
    if n <= 0:
        return ""
    romans = ["II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
    if n - 1 < len(romans):
        return " " + romans[n - 1]
    return f" {n + 1}"


def generate_npc_name(world: World) -> str:
    """Pick a free name out of the pool; collisions get a roman suffix."""
    existing = {getattr(a, "name", None) for a in world.agents.values()}
    # Random shuffle order so we don't always grab the same name.
    pool = list(_NAME_POOL)
    world.rng.shuffle(pool)
    for base in pool:
        if base not in existing:
            return base
    # All bases taken — sweep with suffixes.
    for n in range(1, 50):
        for base in pool:
            candidate = base + _suffix_for(n)
            if candidate not in existing:
                return candidate
    # Pathological fallback.
    return f"NPC-{world.rng.randint(1000, 9999)}"


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    """Euclidean distance; small helper so we don't depend on agents.base existing yet."""
    return math.hypot(ax - bx, ay - by)


def _move_toward(
    x: float, y: float, tx: float, ty: float, step: float
) -> Tuple[float, float]:
    """Move (x,y) up to ``step`` px toward (tx,ty); return new (x,y)."""
    dx = tx - x
    dy = ty - y
    d = math.hypot(dx, dy)
    if d <= step or d == 0.0:
        return tx, ty
    return x + dx * (step / d), y + dy * (step / d)


# Buildings the Yellow Man likes to puppet NPCs toward at DUSK.
_YELLOW_TARGET_TAGS = ("matthews", "sheriff")


def _building_target(world: World, role_tag: str) -> Optional[Tuple[float, float]]:
    for b in world.buildings.values():
        if b.role_tag == role_tag:
            return (b.x, b.y)
    return None


def _nearest_dwelling(world: World, x: float, y: float) -> Optional[Tuple[str, float, float]]:
    """Return id+coords of the closest building tagged as a dwelling-ish role."""
    best = None
    best_d = float("inf")
    # Anything other than the lighthouse counts as shelterable.
    for b in world.buildings.values():
        if b.role_tag == "lighthouse":
            continue
        d = _distance(x, y, b.x, b.y)
        if d < best_d:
            best_d = d
            best = (b.id, b.x, b.y)
    return best


def _talisman_door(world: World, rng) -> Optional[Tuple[float, float]]:
    """Pick a random talisman-protected building's entrance to loiter near."""
    talismans = [b for b in world.buildings.values() if b.has_talisman]
    if not talismans:
        return None
    b = rng.choice(talismans)
    # Stand a few px south of the door (entrance side in our SVG layout).
    return (b.x + rng.uniform(-12, 12), b.y + rng.uniform(18, 28))


class NPC(Agent):
    """Unnamed villager. Owned by Agent C."""

    kind = AgentKind.NPC
    marker_class = MarkerClass.NPC

    def __init__(
        self,
        npc_id: str,
        name: str,
        x: float,
        y: float,
    ) -> None:
        self.id = npc_id
        self.name = name
        self.x = float(x)
        self.y = float(y)
        self.target_x = float(x)
        self.target_y = float(y)
        self.state: State = State.WORKING
        self.fear: float = 0.0
        self.sanity: float = 1.0
        self.status: Status = Status.ACTIVE
        self.arrived_at_tick: int = 0
        # WANDERING is forced for a few ticks when the Yellow Man marches by.
        self._wander_until_tick: int = 0
        # Re-target cooldown so we don't thrash every tick.
        self._retarget_at_tick: int = 0

    # ---------------------------------------------------------------- API

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "name": self.name,
                "state": self.state.value,
                "status": self.status.value,
                "fear": round(self.fear, 2),
                "sanity": round(self.sanity, 2),
                "target_x": round(self.target_x, 2),
                "target_y": round(self.target_y, 2),
            }
        )
        return d

    # ------------------------------------------------------------ helpers

    def _pick_target(self, world: World) -> Tuple[float, float]:
        """Pick a wander/work/shelter destination based on phase + touched bias."""
        rng = world.rng
        phase = world.time.phase
        touched = self.id in world.yellow_touched_npcs

        # Yellow-touched bias: DUSK = drift toward Matthews/Sheriff,
        # NIGHT = loiter near talisman doors.
        if touched and phase == Phase.DUSK:
            tag = rng.choice(_YELLOW_TARGET_TAGS)
            t = _building_target(world, tag)
            if t is not None:
                return (t[0] + rng.uniform(-25, 25), t[1] + rng.uniform(10, 35))

        if touched and phase == Phase.NIGHT:
            t = _talisman_door(world, rng)
            if t is not None:
                return t

        if phase == Phase.NIGHT:
            # Head to nearest dwelling to shelter.
            near = _nearest_dwelling(world, self.x, self.y)
            if near is not None:
                _, bx, by = near
                return (bx + rng.uniform(-10, 10), by + rng.uniform(-10, 10))

        if phase == Phase.DUSK:
            # Hang around the diner/church area to socialize.
            socials = [
                b for b in world.buildings.values()
                if b.role_tag in ("diner", "church")
            ]
            if socials:
                b = rng.choice(socials)
                return (b.x + rng.uniform(-30, 30), b.y + rng.uniform(-30, 30))

        # DAY / DAWN — work near a random non-colony building entrance.
        candidates = [
            b for b in world.buildings.values()
            if b.role_tag not in ("colony", "lighthouse")
        ]
        if candidates:
            b = rng.choice(candidates)
            return (b.x + rng.uniform(-40, 40), b.y + rng.uniform(15, 50))

        # Fallback: jitter.
        return (self.x + rng.uniform(-30, 30), self.y + rng.uniform(-30, 30))

    def _update_state(self, world: World) -> None:
        """Translate phase + position into the mini-FSM state."""
        if world.tick_count < self._wander_until_tick:
            self.state = State.WANDERING
            return

        phase = world.time.phase
        if phase == Phase.NIGHT:
            # If we're close to a building, count as sheltering.
            near = _nearest_dwelling(world, self.x, self.y)
            if near is not None and _distance(self.x, self.y, near[1], near[2]) < 35:
                self.state = State.SHELTERING
            else:
                self.state = State.WORKING  # still trying to get home
        elif phase == Phase.DUSK:
            self.state = State.SOCIALIZING
        else:
            self.state = State.WORKING

    def force_wander(self, until_tick: int) -> None:
        """Called by yellow_man.py when the visible march passes nearby."""
        self._wander_until_tick = max(self._wander_until_tick, until_tick)
        self.state = State.WANDERING

    # ----------------------------------------------------------------- tick

    def tick(self, world: World) -> None:
        if self.status != Status.ACTIVE:
            return

        # (Re)pick a target if we've arrived or our cooldown ran out.
        arrived = _distance(self.x, self.y, self.target_x, self.target_y) < 3.0
        if arrived or world.tick_count >= self._retarget_at_tick:
            tx, ty = self._pick_target(world)
            self.target_x = tx
            self.target_y = ty
            # 20 - 60 ticks until we re-pick, jittered per-NPC.
            self._retarget_at_tick = world.tick_count + world.rng.randint(20, 60)
            if arrived:
                self.arrived_at_tick = world.tick_count

        # Step toward target. NPCs are deliberately slow vs creatures.
        step = 6.0 if self.state == State.WANDERING else 3.5
        self.x, self.y = _move_toward(self.x, self.y, self.target_x, self.target_y, step)

        # FSM state mostly follows phase + position.
        self._update_state(world)

        # Yellow-touched + standing near a talisman door at NIGHT subtly drains
        # sanity for the NPC itself (a flavour effect; Agent B reads sanity from
        # the snapshot, so this surfaces as "this newcomer seems off").
        if (
            self.id in world.yellow_touched_npcs
            and world.time.phase == Phase.NIGHT
        ):
            # Are we hovering next to a talisman building?
            for b in world.buildings.values():
                if b.has_talisman and _distance(self.x, self.y, b.x, b.y) < 30:
                    self.sanity = max(0.0, self.sanity - 0.001)
                    self.fear = min(1.0, self.fear + 0.0005)
                    break
