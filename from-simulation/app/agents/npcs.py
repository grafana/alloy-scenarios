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
from typing import List, Optional, Tuple

from contracts import (
    Agent,
    AgentKind,
    Event,
    MarkerClass,
    NPC_HOME_BUILDINGS,
    Phase,
    State,
    Status,
    World,
)
from agents.base import move_toward


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


def pick_home_id(world: World, exclude: Optional[List[str]] = None) -> Optional[str]:
    """Pick a home building id for an NPC from the talisman residential pool.

    Excludes buildings currently in cooling-off (failed talisman) and any caller-
    supplied exclude list (used when re-homing displaced NPCs after a breach so
    they don't pick the same broken house).

    Weighted: ``colony_house`` is 4x more likely than the smaller houses, so the
    "big house" feels populated.
    """
    exclude_set = set(exclude or [])
    tick = world.tick_count
    candidates: List[str] = []
    weights: List[int] = []
    for bid in NPC_HOME_BUILDINGS:
        if bid in exclude_set:
            continue
        b = world.buildings.get(bid)
        if b is None:
            continue
        if b.cooling_off_until_tick > tick:
            continue
        candidates.append(bid)
        weights.append(4 if bid == "colony_house" else 1)
    if not candidates:
        return None
    return world.rng.choices(candidates, weights=weights, k=1)[0]


def _building_id_for_role(world: World, role_tag: str) -> Optional[str]:
    for b in world.buildings.values():
        if b.role_tag == role_tag:
            return b.id
    return None


def _personality_bucket(npc_id: str) -> str:
    """Stable hash bucket: 50% worker, 25% socializer, 25% wanderer."""
    # ``hash`` differs across runs in Python 3 by default, but the salted hash
    # is stable within a process — good enough for "this NPC has a temperament"
    # since NPC ids are themselves regenerated each cycle.
    bucket = (sum(ord(c) for c in npc_id)) % 4
    if bucket < 2:
        return "worker"
    if bucket == 2:
        return "socializer"
    return "wanderer"


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
        # v4: NPCs use the 0-100 sanity/fear scale to match characters and the
        # ``npc_sanity_break_*`` thresholds in Config.
        self.fear: float = 0.0
        self.sanity: float = 100.0
        self.status: Status = Status.ACTIVE
        self.arrived_at_tick: int = 0
        # WANDERING is forced for a few ticks when the Yellow Man marches by.
        self._wander_until_tick: int = 0
        # Re-target cooldown so we don't thrash every tick.
        self._retarget_at_tick: int = 0
        # v4 — home binding + daily contributions.
        self.home_id: Optional[str] = None
        self.contribution_this_day: float = 0.0
        self.last_contribution_tick: int = 0
        # ``_indoors`` is True when we're currently inside our home (snapped to
        # the building and added to its occupant set). Tracked locally so we
        # can clean up the occupant entry when we leave.
        self._indoors: bool = False
        # Stable personality bucket — set lazily on first tick once we have a
        # home id; kept here as a cache so we don't recompute every tick.
        self._bucket: Optional[str] = None
        # Socializer NPCs alternate between bar and diner. Toggled on retarget.
        self._social_pref: str = "bar"
        # Last day we flushed the daily contribution summary, so we only emit
        # the npc_contribution event once per sim-day.
        self._last_summary_day: int = -1

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
                "home_id": self.home_id,
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
            # If we're close to home (or any dwelling), count as sheltering.
            if self._indoors:
                self.state = State.SHELTERING
                return
            near = _nearest_dwelling(world, self.x, self.y)
            if near is not None and _distance(self.x, self.y, near[1], near[2]) < 35:
                self.state = State.SHELTERING
            else:
                self.state = State.WORKING  # still trying to get home
        elif phase == Phase.DUSK:
            self.state = State.SOCIALIZING
        else:
            # DAY / DAWN — socializer bucket gets SOCIALIZING, others WORKING.
            if (self._bucket or _personality_bucket(self.id)) == "socializer":
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

        # ----- Ensure we have a home (and a personality bucket).
        if self.home_id is None:
            self.home_id = pick_home_id(world)
        if self._bucket is None:
            self._bucket = _personality_bucket(self.id)

        # If our home went into cool-off (e.g. a sanity break happened there),
        # drop it and try to find a new one next tick.
        if self.home_id is not None:
            home = world.buildings.get(self.home_id)
            if home is not None and home.cooling_off_until_tick > world.tick_count:
                home.occupants.discard(self.id)
                self._indoors = False
                self.home_id = pick_home_id(world, exclude=[self.home_id])

        phase = world.time.phase
        rng = world.rng
        touched = self.id in world.yellow_touched_npcs

        # ----- Pick / refresh the target based on phase + bucket.
        arrived = _distance(self.x, self.y, self.target_x, self.target_y) < 3.0
        if arrived or world.tick_count >= self._retarget_at_tick:
            # Yellow-touched bias overrides everything except going home.
            if touched and phase == Phase.DUSK:
                tag = rng.choice(_YELLOW_TARGET_TAGS)
                t = _building_target(world, tag)
                if t is not None:
                    self.target_x = t[0] + rng.uniform(-25, 25)
                    self.target_y = t[1] + rng.uniform(10, 35)
                else:
                    self.target_x, self.target_y = self._home_target(world)
            elif touched and phase == Phase.NIGHT:
                t = _talisman_door(world, rng)
                if t is not None:
                    self.target_x, self.target_y = t
                else:
                    self.target_x, self.target_y = self._home_target(world)
            elif phase == Phase.NIGHT or phase == Phase.DUSK:
                # Head home for shelter (DUSK gets a head-start so they arrive
                # before NIGHT proper).
                self.target_x, self.target_y = self._home_target(world)
            else:
                # DAY / DAWN — drive by personality bucket.
                self.target_x, self.target_y = self._day_target(world)

            self._retarget_at_tick = world.tick_count + rng.randint(20, 60)
            if arrived:
                self.arrived_at_tick = world.tick_count

        # ----- Move and update FSM state.
        if self.state == State.WANDERING:
            step = 6.0
        else:
            step = 3.5
        # Use the canonical move_toward so future tooling can rely on it.
        move_toward(self, self.target_x, self.target_y, step)
        self._update_state(world)

        # ----- NIGHT shelter snap.
        if phase == Phase.NIGHT and self.home_id is not None:
            home = world.buildings.get(self.home_id)
            if home is not None and _distance(self.x, self.y, home.x, home.y) < 20.0:
                self.x = home.x
                self.y = home.y
                home.occupants.add(self.id)
                self._indoors = True
                self.state = State.SHELTERING
            elif self._indoors:
                # We left home (rare — but cleanup the occupants set).
                if home is not None:
                    home.occupants.discard(self.id)
                self._indoors = False
        elif self._indoors and self.home_id is not None:
            # Phase rolled out of NIGHT — leave the home occupant set.
            home = world.buildings.get(self.home_id)
            if home is not None:
                home.occupants.discard(self.id)
            self._indoors = False

        # ----- Daytime contributions.
        if phase == Phase.DAY:
            colony = world.buildings.get("colony_house")
            if (
                self.state == State.WORKING
                and self._bucket == "worker"
                and colony is not None
                and _distance(self.x, self.y, colony.x, colony.y) < 80.0
            ):
                delta = 0.0008
                world.farm_health = min(1.0, world.farm_health + delta)
                self.contribution_this_day += delta
                self.last_contribution_tick = world.tick_count
            elif self.state == State.SOCIALIZING and self._bucket == "socializer":
                bar = world.buildings.get("bar")
                diner = world.buildings.get("diner")
                near_venue = False
                for venue in (bar, diner):
                    if venue is not None and _distance(self.x, self.y, venue.x, venue.y) < 60.0:
                        near_venue = True
                        break
                if near_venue:
                    delta = 0.04
                    for other in world.agents.values():
                        if getattr(other, "kind", None) != AgentKind.CHARACTER:
                            continue
                        if _distance(self.x, self.y, other.x, other.y) > 60.0:
                            continue
                        cur = getattr(other, "sanity", None)
                        if cur is None:
                            continue
                        # Characters use 0-100 scale.
                        setattr(other, "sanity", min(100.0, cur + delta))
                    self.contribution_this_day += delta
                    self.last_contribution_tick = world.tick_count

        # ----- Daily summary at DUSK boundary (18:00).
        if (
            world.time.hour == 18
            and world.time.minute == 0
            and self._last_summary_day != world.time.day
        ):
            if self.contribution_this_day > 0.0:
                world.emit(
                    Event(
                        tick=world.tick_count,
                        type="npc_contribution",
                        subject=self.id,
                        detail=f"contributed {self.contribution_this_day:.2f}",
                        severity="info",
                    )
                )
            self.contribution_this_day = 0.0
            self._last_summary_day = world.time.day

        # ----- Yellow-touched flavour drain (kept from v1, scaled to 0-100).
        if touched and phase == Phase.NIGHT:
            for b in world.buildings.values():
                if b.has_talisman and _distance(self.x, self.y, b.x, b.y) < 30:
                    self.sanity = max(0.0, self.sanity - 0.1)
                    self.fear = min(100.0, self.fear + 0.05)
                    break

    # ----- helpers used by the new tick body --------------------------------

    def _home_target(self, world: World) -> Tuple[float, float]:
        """Where to walk at NIGHT/DUSK — toward the assigned home with jitter."""
        if self.home_id is None:
            # No home yet — fall back to the nearest dwelling like v1.
            near = _nearest_dwelling(world, self.x, self.y)
            if near is not None:
                _, bx, by = near
                return (bx, by)
            return (self.x, self.y)
        home = world.buildings.get(self.home_id)
        if home is None:
            return (self.x, self.y)
        rng = world.rng
        return (home.x + rng.uniform(-6, 6), home.y + rng.uniform(-6, 6))

    def _day_target(self, world: World) -> Tuple[float, float]:
        """DAY target driven by the personality bucket."""
        rng = world.rng
        bucket = self._bucket or _personality_bucket(self.id)
        if bucket == "worker":
            colony = world.buildings.get("colony_house")
            if colony is not None:
                return (colony.x + rng.uniform(-40, 40), colony.y + rng.uniform(-20, 30))
        if bucket == "socializer":
            # Alternate between bar and diner so the two venues stay populated.
            self._social_pref = "diner" if self._social_pref == "bar" else "bar"
            venue = world.buildings.get(self._social_pref)
            if venue is not None:
                return (venue.x + rng.uniform(-30, 30), venue.y + rng.uniform(-20, 20))
        # Wanderer (and any fallback): drift around town centre.
        cx, cy = 465.0, 475.0
        return (cx + rng.uniform(-80, 80), cy + rng.uniform(-80, 80))
