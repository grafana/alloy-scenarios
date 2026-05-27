"""
Main characters of From — the named townsfolk who drive social life.

Agent B owns this module. Characters are full ``Agent`` subclasses; their state
machine is the canonical one from ``agents/states.py`` (TRANSITION_TABLE).
Each tick we:

1. Sample candidate next states from the transition table.
2. Filter by precondition (time of day, status, dwelling state, etc.).
3. Weight each candidate by ``base * tod_mult * personality_mult * role_bonus``.
4. Apply hard overrides (night-in-talisman -> SHELTERING, fear>80 -> FLEEING,
   IRRATIONAL sticky).
5. Optionally consult the LLM (``world.llm_decider.maybe_decide``).
6. Pick weighted-random.
7. Move toward target relevant to the new state.
8. Bookkeeping: hunger/fatigue/sanity drift, awareness bumps for nearby
   yellow-touched NPCs.

The bottom of this file also exposes ``tick_societies(world)`` — Agent A is
expected to call this once per simulation tick AFTER the character ticks have
run; it drives social rituals, resurrection, and expeditions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from contracts import (
    Agent,
    AgentKind,
    BUILDING_LAYOUT,
    Event,
    MarkerClass,
    Phase,
    Role,
    State,
    Status,
    World,
)

# Agent A's helpers — we trust the names from the brief.
from agents.base import distance, move_toward  # type: ignore  # noqa: F401
from agents.states import TRANSITION_TABLE  # type: ignore  # noqa: F401

import legacy


# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------

# Time-of-day multipliers applied per candidate state.
TOD_MULT: Dict[Phase, Dict[State, float]] = {
    Phase.DAWN: {
        State.SLEEPING: 1.4,
        State.PRAYING: 1.3,
        State.WANDERING: 0.6,
        State.PATROLLING: 0.8,
    },
    Phase.DAY: {
        State.FARMING: 1.6,
        State.PATROLLING: 1.4,
        State.REPAIRING: 1.4,
        State.GOSSIPING: 1.3,
        State.PLAYING: 1.5,
        State.SCAVENGING: 1.2,
        State.EXPEDITION: 1.3,
        State.SLEEPING: 0.2,
        State.SHELTERING: 0.3,
    },
    Phase.DUSK: {
        State.SHELTERING: 1.3,
        State.MEETING: 1.2,
        State.PRAYING: 1.1,
        State.WANDERING: 0.6,
        State.PATROLLING: 1.0,
    },
    Phase.NIGHT: {
        State.SLEEPING: 1.8,
        State.SHELTERING: 1.6,
        State.PATROLLING: 0.4,
        State.WANDERING: 0.1,
        State.FARMING: 0.05,
        State.PLAYING: 0.05,
    },
}

# Personality -> states that personality boosts.
PERSONALITY_BOOST: Dict[str, Dict[State, float]] = {
    "brave": {
        State.PATROLLING: 1.4, State.EXPEDITION: 1.5,
        State.INVESTIGATING: 1.3, State.FLEEING: 0.4,
    },
    "social": {
        State.GOSSIPING: 1.5, State.MEETING: 1.4,
        State.CONVERSING: 1.5, State.MEDIATING: 1.2,
    },
    "devout": {
        State.PRAYING: 1.8, State.MOURNING: 1.3, State.MEDIATING: 1.2,
    },
    "paranoid": {
        State.INVESTIGATING: 1.6, State.SHELTERING: 1.4,
        State.FLEEING: 1.4, State.ARGUING: 1.2, State.GOSSIPING: 1.2,
    },
    "caretaker": {
        State.CARETAKING: 1.8, State.MEDICAL_CARE: 1.5, State.MOURNING: 1.2,
    },
    "leader": {
        State.MEETING: 1.5, State.MEDIATING: 1.4, State.PATROLLING: 1.1,
    },
}

ROLE_PRIORITY: Dict[Role, List[State]] = {
    Role.SHERIFF: [State.PATROLLING, State.MEETING, State.EXPEDITION],
    Role.LEADER_COLONY: [State.MEETING, State.FARMING, State.ARGUING],
    Role.ENGINEER: [State.REPAIRING, State.EXPEDITION, State.CARETAKING],
    Role.CARETAKER: [State.CARETAKING, State.MOURNING, State.CONVERSING],
    Role.CHILD: [State.PLAYING, State.SLEEPING],
    Role.BRIDGE: [State.GOSSIPING, State.EXPEDITION],
    Role.INVESTIGATOR: [State.INVESTIGATING, State.WANDERING, State.ARGUING],
    Role.DEPUTY: [State.PATROLLING, State.CARETAKING, State.MEETING],
    Role.PRIEST: [State.PRAYING, State.CONVERSING, State.MEDIATING],
    Role.SEER: [State.WANDERING, State.CONVERSING],
}

ROLE_BONUS = 2.0

# Awareness threshold — once a yellow-touched NPC has accumulated this much
# suspicion in a character's eyes, that character will call for a meeting.
AWARENESS_PROXIMITY = 80.0  # px — within this we bump awareness each tick
AWARENESS_BUMP_PER_TICK = 0.05

# Per-tick drift constants.
HUNGER_RATE = 0.04
FATIGUE_RATE = 0.03
SANITY_RECOVERY = 0.01
SANITY_NIGHT_DRAIN = 0.04


# ---------------------------------------------------------------------------
# Character class
# ---------------------------------------------------------------------------


@dataclass
class _Seed:
    """Static seed for one character — turned into a Character at world init."""
    name: str
    dwelling_id: str
    role: Role
    personality: Dict[str, float]
    schedule: List[Tuple[Phase, State]] = field(default_factory=list)


CHARACTER_SEEDS: List[_Seed] = [
    _Seed(
        name="Boyd",
        dwelling_id="camper",
        role=Role.SHERIFF,
        personality={"brave": 0.9, "social": 0.5, "devout": 0.3,
                     "paranoid": 0.4, "caretaker": 0.6, "leader": 0.8},
        schedule=[(Phase.DAY, State.PATROLLING), (Phase.NIGHT, State.SHELTERING)],
    ),
    _Seed(
        name="Donna",
        dwelling_id="colony_house",
        role=Role.LEADER_COLONY,
        personality={"brave": 0.6, "social": 0.8, "devout": 0.4,
                     "paranoid": 0.4, "caretaker": 0.6, "leader": 0.95},
        schedule=[(Phase.DAY, State.FARMING), (Phase.DUSK, State.MEETING)],
    ),
    _Seed(
        name="Jim",
        dwelling_id="matthews_house",
        role=Role.ENGINEER,
        personality={"brave": 0.7, "social": 0.5, "devout": 0.2,
                     "paranoid": 0.6, "caretaker": 0.5, "leader": 0.4},
        schedule=[(Phase.DAY, State.REPAIRING), (Phase.NIGHT, State.SHELTERING)],
    ),
    _Seed(
        name="Tabitha",
        dwelling_id="matthews_house",
        role=Role.CARETAKER,
        personality={"brave": 0.5, "social": 0.7, "devout": 0.6,
                     "paranoid": 0.5, "caretaker": 0.95, "leader": 0.4},
        schedule=[(Phase.DAY, State.CARETAKING), (Phase.DUSK, State.MOURNING)],
    ),
    _Seed(
        name="Ethan",
        dwelling_id="matthews_house",
        role=Role.CHILD,
        personality={"brave": 0.6, "social": 0.6, "devout": 0.2,
                     "paranoid": 0.4, "caretaker": 0.2, "leader": 0.1},
        schedule=[(Phase.DAY, State.PLAYING), (Phase.NIGHT, State.SLEEPING)],
    ),
    _Seed(
        name="Julie",
        dwelling_id="colony_house",
        role=Role.BRIDGE,
        personality={"brave": 0.7, "social": 0.8, "devout": 0.3,
                     "paranoid": 0.5, "caretaker": 0.5, "leader": 0.4},
        schedule=[(Phase.DAY, State.GOSSIPING), (Phase.DUSK, State.WANDERING)],
    ),
    _Seed(
        name="Jade",
        dwelling_id="colony_house",
        role=Role.INVESTIGATOR,
        personality={"brave": 0.7, "social": 0.4, "devout": 0.2,
                     "paranoid": 0.85, "caretaker": 0.3, "leader": 0.4},
        schedule=[(Phase.DAY, State.INVESTIGATING), (Phase.DUSK, State.WANDERING)],
    ),
    _Seed(
        name="Kenny",
        dwelling_id="colony_house",
        role=Role.DEPUTY,
        personality={"brave": 0.7, "social": 0.7, "devout": 0.3,
                     "paranoid": 0.4, "caretaker": 0.6, "leader": 0.4},
        schedule=[(Phase.DAY, State.PATROLLING), (Phase.NIGHT, State.SHELTERING)],
    ),
    _Seed(
        name="Khatri",
        dwelling_id="church",
        role=Role.PRIEST,
        personality={"brave": 0.5, "social": 0.6, "devout": 0.95,
                     "paranoid": 0.3, "caretaker": 0.7, "leader": 0.5},
        schedule=[(Phase.DAWN, State.PRAYING), (Phase.DUSK, State.PRAYING)],
    ),
    _Seed(
        name="Sara",
        dwelling_id="lighthouse",
        role=Role.SEER,
        personality={"brave": 0.5, "social": 0.4, "devout": 0.6,
                     "paranoid": 0.7, "caretaker": 0.4, "leader": 0.3},
        schedule=[(Phase.DAY, State.WANDERING), (Phase.NIGHT, State.CONVERSING)],
    ),
]


class Character(Agent):
    """One named townsperson."""

    kind = AgentKind.CHARACTER
    marker_class = MarkerClass.CHAR

    def __init__(
        self,
        name: str,
        dwelling_id: str,
        role: Role,
        personality: Dict[str, float],
        schedule: List[Tuple[Phase, State]],
        x: float,
        y: float,
    ) -> None:
        self.id = name
        self.name = name
        self.dwelling_id = dwelling_id
        self.role = role
        self.personality = dict(personality)
        self.schedule = list(schedule)
        self.x = float(x)
        self.y = float(y)

        # Behavioural state
        self.state: State = State.SLEEPING
        self.state_since_tick: int = 0

        # Drives
        self.hunger: float = 20.0
        self.fatigue: float = 20.0
        self.fear: float = 0.0
        self.sanity: float = 100.0

        self.inventory: Dict[str, int] = {}
        self.status: Status = Status.ACTIVE
        self.last_llm_tick: int = -10_000
        self.awareness: Dict[str, float] = {}

        # Social / society bookkeeping
        self.meeting_until_tick: int = 0
        self.arguing_until_tick: int = 0
        self.conversation_partner: Optional[str] = None
        self.expedition_role: Optional[str] = None  # "leader" | "member" | None
        self.target: Optional[Tuple[float, float]] = None

        # Cross-cycle bookkeeping
        self._obituary_written: bool = False

    # ------------------------------------------------------------------ tick
    def tick(self, world: World) -> None:
        if self.status == Status.DEAD:
            # First DEAD-status tick: write an obituary into the journal.
            if not self._obituary_written:
                self._obituary_written = True
                try:
                    legacy.record(world, "char_death", name=self.name)
                except Exception:
                    pass
            return
        if self.status == Status.ABSENT:
            return

        # ---- Drives & sanity ---------------------------------------------
        self.hunger = min(100.0, self.hunger + HUNGER_RATE)
        if self.state == State.SLEEPING:
            self.fatigue = max(0.0, self.fatigue - FATIGUE_RATE * 5)
        else:
            self.fatigue = min(100.0, self.fatigue + FATIGUE_RATE)
        if world.time.phase == Phase.NIGHT and self.state != State.SLEEPING:
            self.sanity = max(0.0, self.sanity - SANITY_NIGHT_DRAIN)
        else:
            self.sanity = min(100.0, self.sanity + SANITY_RECOVERY)

        # ---- Awareness: bump for nearby yellow-touched NPCs --------------
        self._update_awareness(world)

        # ---- Sticky / pinned states --------------------------------------
        if self.state == State.MEETING and world.tick_count < self.meeting_until_tick:
            return
        if self.state == State.ARGUING and world.tick_count < self.arguing_until_tick:
            self.fear = min(100.0, self.fear + 0.3)
            self.sanity = max(0.0, self.sanity - 0.1)
            return

        # ---- Hard overrides ----------------------------------------------
        forced = self._hard_override(world)
        if forced is not None:
            self._enter(world, forced)
            self._step_toward_target(world)
            return

        # ---- Build candidate menu ----------------------------------------
        menu = self._candidate_menu(world)
        if not menu:
            # Fall through to WANDERING — should be a node in any sane table.
            menu = [(State.WANDERING, 1.0)]

        # ---- Optional LLM consultation -----------------------------------
        chosen: Optional[State] = None
        cfg = world.config
        if (
            cfg.anthropic_api_key
            and getattr(world, "llm_decider", None) is not None
            and world.rng.random() < cfg.llm_decision_rate
            and (world.tick_count - self.last_llm_tick) >= cfg.llm_min_tick_gap
        ):
            try:
                chosen = world.llm_decider.maybe_decide(self, world, menu)
            except Exception:  # never let an LLM hiccup kill the tick
                chosen = None
            self.last_llm_tick = world.tick_count
            if chosen is not None:
                world.emit(Event(
                    tick=world.tick_count, type="llm_decision",
                    subject=self.id, detail=f"{self.state.value}->{chosen.value}",
                ))

        if chosen is None:
            states = [s for s, _ in menu]
            weights = [w for _, w in menu]
            chosen = world.rng.choices(states, weights=weights, k=1)[0]

        if chosen != self.state:
            self._enter(world, chosen)

        self._step_toward_target(world)

    # ----------------------------------------------------------- helpers
    def _hard_override(self, world: World) -> Optional[State]:
        if self.state == State.IRRATIONAL:
            return State.IRRATIONAL  # sticky
        if self.fear > 80.0:
            return State.FLEEING
        if world.time.phase == Phase.NIGHT:
            b = world.buildings.get(self.dwelling_id)
            if b is not None and b.has_talisman:
                return State.SHELTERING
        return None

    def _candidate_menu(self, world: World) -> List[Tuple[State, float]]:
        table = TRANSITION_TABLE.get(self.state, {})
        if not table:
            return []
        phase = world.time.phase
        tod = TOD_MULT.get(phase, {})
        priority = set(ROLE_PRIORITY.get(self.role, []))
        prophecy_mult = self._prophecy_bias(world)

        out: List[Tuple[State, float]] = []
        # TRANSITION_TABLE entries are (next_state, base_weight, tod_multipliers)
        # 3-tuples (Agent A's format). We apply both A's per-transition phase
        # multiplier AND B's coarser TOD_MULT bias on top of it.
        for next_state, base, tod_mult in table:
            if not self._precondition_ok(next_state, world):
                continue
            w = float(base) * float(tod_mult.get(phase, 1.0))
            w *= tod.get(next_state, 1.0)
            # Personality multiplier — product over all traits that touch this state.
            for trait, val in self.personality.items():
                boost_map = PERSONALITY_BOOST.get(trait, {})
                if next_state in boost_map:
                    factor = boost_map[next_state]
                    # Lerp 1.0 -> factor by trait strength.
                    w *= 1.0 + (factor - 1.0) * val
            if next_state in priority:
                w *= ROLE_BONUS
            # Prophecy bias — pending prophecies mentioning this character.
            w *= prophecy_mult.get(next_state, 1.0)
            if w > 0:
                out.append((next_state, w))
        return out

    # Words inside a prophecy payload that hint at a state being warned against.
    _PROPHECY_WARNINGS: Dict[str, List[State]] = {
        "door": [State.PATROLLING, State.SHELTERING],
        "sleep through": [State.SLEEPING, State.SHELTERING],
        "do not sleep": [State.SLEEPING],
        "do not pray": [State.PRAYING],
        "stay inside": [State.PATROLLING, State.WANDERING],
        "leave": [State.SHELTERING, State.SLEEPING],
    }

    _ROLE_HINTS: Dict[Role, List[str]] = {
        Role.SHERIFF: ["sheriff"],
        Role.DEPUTY: ["deputy"],
        Role.LEADER_COLONY: ["leader", "colony"],
        Role.ENGINEER: ["engineer"],
        Role.CARETAKER: ["caretaker", "nurse"],
        Role.BRIDGE: ["bridge"],
        Role.INVESTIGATOR: ["investigator"],
        Role.PRIEST: ["priest", "father"],
        Role.SEER: ["seer"],
        Role.CHILD: ["child"],
    }

    def _prophecy_bias(self, world: World) -> Dict[State, float]:
        """Return per-state multipliers from pending prophecies that mention us.

        Heuristic: any prophecy whose payload substring-matches this character's
        name or a role keyword applies; +20% to states named in the payload,
        -50% on states the prophecy 'warns against' (via ``_PROPHECY_WARNINGS``).
        Does NOT consume the prophecy — Agent A's ``fire_due_prophecies`` does
        that on the proper trigger.
        """
        legacy_obj = getattr(world, "legacy", None)
        if legacy_obj is None:
            return {}
        prophecies = getattr(legacy_obj, "pending_prophecies", None)
        if not prophecies:
            return {}
        name_lower = self.name.lower()
        role_keywords = self._ROLE_HINTS.get(self.role, [])
        mult: Dict[State, float] = {}
        for p in prophecies:
            payload = (getattr(p, "payload", "") or "").lower()
            if not payload:
                continue
            mentions_me = name_lower in payload or any(k in payload for k in role_keywords)
            if not mentions_me:
                continue
            # +20% on states whose name appears in the payload.
            for s in State:
                if s.value.lower() in payload:
                    mult[s] = mult.get(s, 1.0) * 1.2
            # -50% on warned-against states.
            for trigger, states in self._PROPHECY_WARNINGS.items():
                if trigger in payload:
                    for s in states:
                        mult[s] = mult.get(s, 1.0) * 0.5
        return mult

    def _precondition_ok(self, s: State, world: World) -> bool:
        # Multi-agent states are entered by the social loop, not by self.tick().
        if s in (State.MEETING, State.ARGUING, State.CONVERSING,
                 State.MEDIATING, State.EXPEDITION):
            return False
        if s == State.SLEEPING and world.time.phase == Phase.DAY:
            # children may nap, others mostly don't
            if self.role != Role.CHILD:
                return False
        if s == State.PLAYING and self.role != Role.CHILD:
            return False
        if s == State.PRAYING and self.role not in (Role.PRIEST, Role.SEER) \
                and self.personality.get("devout", 0.0) < 0.4:
            return False
        if s == State.IRRATIONAL:
            return False  # entered via fear.py only
        if s == State.HYPNOTIZED:
            return False  # entered via creatures
        return True

    def _enter(self, world: World, new_state: State) -> None:
        if new_state == self.state:
            return
        self.state = new_state
        self.state_since_tick = world.tick_count
        self.target = self._target_for(new_state, world)

    def _target_for(self, s: State, world: World) -> Optional[Tuple[float, float]]:
        b = world.buildings.get(self.dwelling_id)
        home = (b.x, b.y) if b else (self.x, self.y)
        if s in (State.SLEEPING, State.SHELTERING):
            return home
        if s == State.PRAYING:
            ch = world.buildings.get("church")
            return (ch.x, ch.y) if ch else home
        if s == State.FARMING:
            ch = world.buildings.get("colony_house")
            return (ch.x + 20, ch.y + 60) if ch else home
        if s == State.REPAIRING:
            ch = world.buildings.get("matthews_house")
            return (ch.x, ch.y) if ch else home
        if s == State.CARETAKING or s == State.MEDICAL_CARE:
            ch = world.buildings.get("clinic")
            return (ch.x, ch.y) if ch else home
        if s == State.PATROLLING:
            # roam the village centre
            return (
                world.rng.uniform(300, 700),
                world.rng.uniform(300, 500),
            )
        if s == State.PLAYING:
            return (
                world.rng.uniform(400, 600),
                world.rng.uniform(380, 480),
            )
        if s == State.WANDERING:
            return (
                world.rng.uniform(150, 850),
                world.rng.uniform(150, 600),
            )
        if s == State.FLEEING:
            return home
        if s == State.SCAVENGING:
            return (
                world.rng.uniform(100, 900),
                world.rng.uniform(100, 600),
            )
        if s == State.GOSSIPING:
            diner = world.buildings.get("diner")
            return (diner.x, diner.y) if diner else home
        if s == State.MOURNING:
            ch = world.buildings.get("church")
            return (ch.x + 10, ch.y + 30) if ch else home
        if s == State.INVESTIGATING:
            return (
                world.rng.uniform(150, 850),
                world.rng.uniform(150, 600),
            )
        return home

    def _step_toward_target(self, world: World) -> None:
        if self.target is None:
            return
        # Walk speed depends on state.
        speed = 2.5
        if self.state == State.FLEEING:
            speed = 5.0
        elif self.state in (State.SLEEPING, State.SHELTERING, State.PRAYING,
                            State.MOURNING, State.MEDIATING):
            speed = 0.0
        elif self.state == State.PLAYING:
            speed = 3.5
        if speed <= 0:
            return
        try:
            nx, ny = move_toward((self.x, self.y), self.target, speed)
            self.x, self.y = nx, ny
        except Exception:
            # If A's helper signature differs, fall back to a tiny linear step.
            dx = self.target[0] - self.x
            dy = self.target[1] - self.y
            d = math.hypot(dx, dy) or 1.0
            self.x += speed * dx / d
            self.y += speed * dy / d

    def _update_awareness(self, world: World) -> None:
        touched = getattr(world, "yellow_touched_npcs", set())
        if not touched:
            return
        for npc_id in list(touched):
            other = world.agents.get(npc_id)
            if other is None:
                continue
            try:
                d = distance((self.x, self.y), (other.x, other.y))
            except Exception:
                d = math.hypot(self.x - other.x, self.y - other.y)
            if d <= AWARENESS_PROXIMITY:
                # paranoid characters notice more.
                paranoid = self.personality.get("paranoid", 0.5)
                bump = AWARENESS_BUMP_PER_TICK * (0.7 + 0.6 * paranoid)
                self.awareness[npc_id] = self.awareness.get(npc_id, 0.0) + bump

    # ------------------------------------------------------------ serialise
    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "name": self.name,
            "role": self.role.value,
            "state": self.state.value,
            "status": self.status.value,
            "dwelling_id": self.dwelling_id,
            "hunger": round(self.hunger, 1),
            "fatigue": round(self.fatigue, 1),
            "fear": round(self.fear, 1),
            "sanity": round(self.sanity, 1),
            "personality": {k: round(v, 2) for k, v in self.personality.items()},
            "awareness": {k: round(v, 2) for k, v in self.awareness.items()},
        })
        return d


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _building_xy(building_id: str) -> Tuple[float, float]:
    for (bid, _name, x, y, _f, _t, _r) in BUILDING_LAYOUT:
        if bid == building_id:
            return (float(x), float(y))
    return (500.0, 350.0)


def _personality_with_drift(world: World, seed: "_Seed") -> Dict[str, float]:
    """Apply accumulated legacy drift to a seed's personality (clamped [0,1])."""
    base = dict(seed.personality)
    deltas = world.legacy.personality_drift.get(seed.name, {}) if world.legacy else {}
    for trait, dv in deltas.items():
        base[trait] = max(0.0, min(1.0, base.get(trait, 0.5) + dv))
    return base


def build_characters(world: World) -> None:
    """Instantiate every seeded character and register in ``world.agents``.

    Applies any accumulated legacy drift to each personality before
    construction so reborn characters carry their previous-cycle scars.
    """
    for seed in CHARACTER_SEEDS:
        x, y = _building_xy(seed.dwelling_id)
        # Small jitter so they don't all overlap at spawn.
        x += world.rng.uniform(-15.0, 15.0)
        y += world.rng.uniform(-15.0, 15.0)
        c = Character(
            name=seed.name,
            dwelling_id=seed.dwelling_id,
            role=seed.role,
            personality=_personality_with_drift(world, seed),
            schedule=seed.schedule,
            x=x, y=y,
        )
        world.agents[c.id] = c
        b = world.buildings.get(seed.dwelling_id)
        if b is not None:
            b.occupants.add(c.id)


def respawn_character(world: World, name: str) -> None:
    """Re-instantiate a character at a forest intake point with status RETURNING.

    Applies any accumulated legacy drift (``world.legacy.personality_drift``) to
    the seed personality before instantiating. Each trait is clamped to [0,1].
    """
    seed = next((s for s in CHARACTER_SEEDS if s.name == name), None)
    if seed is None:
        return
    from contracts import NPC_INTAKE_POINTS
    ix, iy = world.rng.choice(NPC_INTAKE_POINTS)
    ix += world.rng.uniform(-15.0, 15.0)
    iy += world.rng.uniform(-15.0, 15.0)

    # Apply legacy drift to the seed personality.
    personality = dict(seed.personality)
    drift = world.legacy.personality_drift.get(name, {}) if world.legacy else {}
    for trait, delta in drift.items():
        cur = personality.get(trait, 0.5)
        personality[trait] = max(0.0, min(1.0, cur + delta))

    c = Character(
        name=seed.name,
        dwelling_id=seed.dwelling_id,
        role=seed.role,
        personality=personality,
        schedule=seed.schedule,
        x=ix, y=iy,
    )
    c.status = Status.RETURNING
    c.state = State.WANDERING
    world.agents[c.id] = c
    world.recognition_counts[c.id] = 0
    world.emit(Event(
        tick=world.tick_count, type="homecoming",
        subject=c.id, detail=f"{c.name} has returned from the forest",
        severity="warn",
    ))


# ---------------------------------------------------------------------------
# Top-level society tick — Agent A must call this once per tick AFTER agents.
# ---------------------------------------------------------------------------


def tick_societies(world: World) -> None:
    """Drive social loop, resurrection countdown, and expedition lifecycle.

    Agent A should call this exactly once at the END of each simulation tick,
    after every Agent.tick() has run.
    """
    # Late imports — avoid hard fail at module import time if a sibling file
    # is still being authored.
    try:
        from agents.social import tick_social
        tick_social(world)
    except Exception as exc:  # pragma: no cover
        if world.telemetry is not None:
            try:
                world.telemetry.get_logger().exception("tick_social failed: %s", exc)
            except Exception:
                pass

    try:
        from agents.resurrection import tick_resurrection
        tick_resurrection(world)
    except Exception as exc:  # pragma: no cover
        if world.telemetry is not None:
            try:
                world.telemetry.get_logger().exception("tick_resurrection failed: %s", exc)
            except Exception:
                pass

    try:
        from agents.expedition import tick_expeditions
        tick_expeditions(world)
    except Exception as exc:  # pragma: no cover
        if world.telemetry is not None:
            try:
                world.telemetry.get_logger().exception("tick_expeditions failed: %s", exc)
            except Exception:
                pass
