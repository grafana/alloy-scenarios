"""
Shared contracts for the From simulation.

This module is the seam between the four subsystems. Every other module
imports from here — agents must not import from each other directly.
The project lead owns this file; subagents propose changes via a stop-the-world
review, never edit unilaterally.

Ownership map (who writes which world fields, who reads which):

  World.time, lighting, buildings, events, food_supply, farm_health    -> Agent A (engine)
  World.creatures, supernaturals                                       -> Agent A (engine)
  World.agents (characters)                                            -> Agent B (main characters)
  World.agents (npcs)                                                  -> Agent C (NPCs)
  World.yellow_touched_npcs, yellow_active, pending_reset, wipes       -> Agent C (Yellow Man)
  World.meeting_outcomes, expedition_authorised, recognition_events    -> Agent B (society)

Anyone may READ any World field. WRITES are gated by ownership above.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Phase(str, enum.Enum):
    DAY = "DAY"
    DUSK = "DUSK"
    NIGHT = "NIGHT"
    DAWN = "DAWN"


class State(str, enum.Enum):
    # Solo states
    SLEEPING = "SLEEPING"
    EATING = "EATING"
    SCAVENGING = "SCAVENGING"
    FARMING = "FARMING"
    GOSSIPING = "GOSSIPING"
    PATROLLING = "PATROLLING"
    SHELTERING = "SHELTERING"
    PRAYING = "PRAYING"
    MEDICAL_CARE = "MEDICAL_CARE"
    MOURNING = "MOURNING"
    REPAIRING = "REPAIRING"
    WANDERING = "WANDERING"
    FLEEING = "FLEEING"
    HYPNOTIZED = "HYPNOTIZED"
    INVESTIGATING = "INVESTIGATING"
    PLAYING = "PLAYING"
    EXPEDITION = "EXPEDITION"
    CARETAKING = "CARETAKING"
    IRRATIONAL = "IRRATIONAL"
    # Multi-agent states (require a partner / venue)
    MEETING = "MEETING"
    ARGUING = "ARGUING"
    CONVERSING = "CONVERSING"
    MEDIATING = "MEDIATING"
    # NPC mini-FSM
    WORKING = "WORKING"
    SOCIALIZING = "SOCIALIZING"


class Role(str, enum.Enum):
    SHERIFF = "SHERIFF"
    DEPUTY = "DEPUTY"
    LEADER_COLONY = "LEADER_COLONY"
    ENGINEER = "ENGINEER"
    CARETAKER = "CARETAKER"
    BRIDGE = "BRIDGE"  # moves between factions
    INVESTIGATOR = "INVESTIGATOR"
    PRIEST = "PRIEST"
    SEER = "SEER"
    CHILD = "CHILD"


class Status(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RETURNING = "RETURNING"
    ABSENT = "ABSENT"
    DEAD = "DEAD"
    INCAPACITATED = "INCAPACITATED"


class AgentKind(str, enum.Enum):
    CHARACTER = "character"
    NPC = "npc"
    CREATURE = "creature"
    SUPERNATURAL = "supernatural"


class MarkerClass(str, enum.Enum):
    CHAR = "char"
    NPC = "npc"
    CREATURE = "creature"
    BOY_IN_WHITE = "boy-in-white"
    MAN_IN_YELLOW = "man-in-yellow"
    ANGHKOOEY = "anghkooey"
    FARAWAY_TREE = "faraway-tree"


class YellowMode(str, enum.Enum):
    DORMANT = "DORMANT"
    VISIBLE_MARCH = "VISIBLE_MARCH"
    IMPOSTER = "IMPOSTER"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SimTime:
    day: int = 0
    hour: int = 6  # sim-day starts at 06:00
    minute: int = 0
    phase: Phase = Phase.DAY

    @property
    def minutes_today(self) -> int:
        return self.hour * 60 + self.minute

    def label(self) -> str:
        return f"D{self.day} {self.hour:02d}:{self.minute:02d} {self.phase.value}"


@dataclass
class Building:
    id: str
    name: str
    x: float
    y: float
    footprint: int  # capacity hint
    has_talisman: bool
    role_tag: str = ""  # e.g. "church", "sheriff", "matthews", "colony", "clinic"
    locked: bool = False
    occupants: Set[str] = field(default_factory=set)


@dataclass
class Event:
    tick: int
    type: str  # see EVENT_TYPES below
    subject: str  # agent id or "world"
    detail: str
    severity: str = "info"  # info | warn | crit


# Canonical event type strings — emit ONLY these.
EVENT_TYPES = {
    # Core / engine
    "tick_warn",
    "phase_change",
    "lighting_update",
    # Creatures
    "creature_spawn",
    "creature_breach",
    "creature_retreat",
    "hypnosis_attempt",
    # Supernatural
    "boy_in_white",
    "anghkooey_chant",
    "faraway_portal",
    # Yellow Man
    "yellow_appearance",
    "yellow_imposter_join",
    "yellow_imposter_acted",
    "imposter_suspicion",
    "imposter_vote",
    "imposter_banished",
    "village_wipe",
    "village_reseed",
    # Population
    "npc_arrival",
    "npc_death",
    "char_death",
    "char_absent",
    "char_returning",
    "homecoming",
    "char_recognised",
    "char_restored",
    # Social
    "meeting_proposed",
    "meeting_started",
    "meeting_outcome",
    "conversation",
    "argument",
    # Fear / irrational
    "paranormal_break",
    "irrational_act",
    "incapacitated",
    "recovered",
    # Food / expedition
    "farm_disaster",
    "expedition_called",
    "expedition_departed",
    "expedition_returned",
    "food_low",
    # LLM
    "llm_decision",
}


@dataclass
class YellowState:
    """State of an active Man in Yellow appearance. Owned by Agent C."""
    mode: YellowMode = YellowMode.DORMANT
    disguised_as: Optional[str] = None  # npc id when in IMPOSTER mode
    started_at_tick: int = 0
    deadline_tick: int = 0  # absolute tick; >0 only when active
    path_index: int = 0  # for visible-march mode


@dataclass
class MeetingOutcome:
    """Emitted by Agent B's social loop, consumed by C/A."""
    tick: int
    topic: str  # "food_supply" | "creature_breach_review" | "imposter_suspicion" | "mourning_X" | "recognise_returner"
    venue_id: str
    attendees: List[str]
    decision: str  # "agree" | "disagree" | "inconclusive"
    payload: Dict[str, Any] = field(default_factory=dict)
    # For imposter votes: payload = {"accused_npc_id": "...", "guilty": bool}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class Config:
    tick_hz: float = 2.0
    time_scale: float = 1.0
    seed: Optional[int] = None
    # LLM
    anthropic_api_key: Optional[str] = None
    llm_model: str = "claude-haiku-4-5"
    llm_decision_rate: float = 0.05
    llm_yellow_rate: float = 0.25
    llm_min_tick_gap: int = 30
    llm_global_rpm: int = 6
    # Population
    npc_floor: int = 18
    resurrection_base_ticks: int = 700
    resurrection_jitter: int = 150
    recognition_threshold: int = 3
    # Yellow Man
    yellow_appearance_days_min: int = 5
    yellow_appearance_days_max: int = 10
    yellow_imposter_prob: float = 0.7
    yellow_deadline_ticks: int = 1500
    # Telemetry
    otlp_endpoint: str = "http://alloy:4318"
    pyroscope_endpoint: str = "http://alloy:9999"
    service_name: str = "from-sim"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, getenv: Callable[[str, Optional[str]], Optional[str]]) -> "Config":
        import os
        g = lambda k, d=None: os.environ.get(k, d)

        def _f(name, default):
            v = g(name)
            return float(v) if v not in (None, "") else default

        def _i(name, default):
            v = g(name)
            return int(v) if v not in (None, "") else default

        def _s(name, default):
            v = g(name)
            return v if v not in (None, "") else default

        return cls(
            tick_hz=_f("TICK_HZ", 2.0),
            time_scale=_f("TIME_SCALE", 1.0),
            seed=int(g("SEED")) if g("SEED") not in (None, "") else None,
            anthropic_api_key=g("ANTHROPIC_API_KEY") or None,
            llm_model=_s("LLM_MODEL", "claude-haiku-4-5"),
            llm_decision_rate=_f("LLM_DECISION_RATE", 0.05),
            llm_yellow_rate=_f("LLM_YELLOW_RATE", 0.25),
            llm_min_tick_gap=_i("LLM_MIN_TICK_GAP", 30),
            llm_global_rpm=_i("LLM_GLOBAL_RPM", 6),
            npc_floor=_i("NPC_FLOOR", 18),
            resurrection_base_ticks=_i("RESURRECTION_BASE_TICKS", 700),
            resurrection_jitter=_i("RESURRECTION_JITTER", 150),
            recognition_threshold=_i("RECOGNITION_THRESHOLD", 3),
            yellow_appearance_days_min=_i("YELLOW_APPEARANCE_DAYS_MIN", 5),
            yellow_appearance_days_max=_i("YELLOW_APPEARANCE_DAYS_MAX", 10),
            yellow_imposter_prob=_f("YELLOW_IMPOSTER_PROB", 0.7),
            yellow_deadline_ticks=_i("YELLOW_DEADLINE_TICKS", 1500),
            otlp_endpoint=_s("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alloy:4318"),
            pyroscope_endpoint=_s("PYROSCOPE_SERVER_ADDRESS", "http://alloy:9999"),
            service_name=_s("SERVICE_NAME", "from-sim"),
            log_level=_s("LOG_LEVEL", "INFO"),
        )


# ---------------------------------------------------------------------------
# Agent ABC
# ---------------------------------------------------------------------------


class Agent(ABC):
    """Base contract every entity in world.agents / world.creatures honours."""

    id: str
    kind: AgentKind
    marker_class: MarkerClass
    x: float
    y: float

    @abstractmethod
    def tick(self, world: "World") -> None: ...

    def to_dict(self) -> Dict[str, Any]:
        """Default snapshot serialisation. Subclasses extend by overriding."""
        return {
            "id": self.id,
            "kind": self.kind.value,
            "marker_class": self.marker_class.value,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
        }


# ---------------------------------------------------------------------------
# Telemetry interface
# ---------------------------------------------------------------------------


class SimTelemetry:
    """Interface — concrete implementation lives in telemetry.py (Agent A).

    Subagents B/C/D use these methods; do not import OTel SDK directly elsewhere.
    """

    def get_logger(self): ...  # returns a stdlib logger wired to OTLP
    def get_tracer(self): ...  # returns an OTel tracer
    def gauge_set(self, name: str, value: float, attrs: Optional[Dict[str, str]] = None) -> None: ...
    def counter_inc(self, name: str, value: float = 1.0, attrs: Optional[Dict[str, str]] = None) -> None: ...
    def shutdown(self) -> None: ...


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


@dataclass
class World:
    """The shared mutable state. Ownership of write access documented at top of file."""

    # --- engine fields (Agent A) ---
    config: Config
    rng: Any  # random.Random
    tick_count: int = 0
    time: SimTime = field(default_factory=SimTime)
    lighting: float = 1.0  # 0 = dark, 1 = bright
    buildings: Dict[str, Building] = field(default_factory=dict)
    creatures: List[Agent] = field(default_factory=list)
    supernaturals: List[Agent] = field(default_factory=list)  # transient Boy/Tree/Anghkooey markers
    events: Any = None  # collections.deque[Event] — wired by simulation.py
    food_supply: float = 100.0
    food_capacity: float = 200.0
    farm_health: float = 1.0
    farm_disaster_until_tick: int = 0
    last_phase: Phase = Phase.DAY

    # --- character fields (Agent B) ---
    agents: Dict[str, Agent] = field(default_factory=dict)  # all named characters + NPCs live here
    meeting_outcomes: List[MeetingOutcome] = field(default_factory=list)
    expedition_authorised: bool = False
    expedition_active: bool = False
    recognition_counts: Dict[str, int] = field(default_factory=dict)  # char_id -> count

    # --- yellow man / npc fields (Agent C) ---
    yellow_touched_npcs: Set[str] = field(default_factory=set)
    yellow_active: YellowState = field(default_factory=YellowState)
    pending_reset: bool = False  # set by C when wipe triggers; A consumes next tick
    village_wipes: int = 0

    # --- food signal (Agent A writes, B reads) ---
    food_shortage: bool = False

    # --- shared handles wired by app.py / simulation.start ---
    telemetry: Optional[SimTelemetry] = None
    llm_decider: Optional[Any] = None  # llm.decider.LLMDecider when ANTHROPIC_API_KEY is set
    narrations: List[Dict[str, str]] = field(default_factory=list)  # rolling window of LLM reasons

    @property
    def cycle_number(self) -> int:
        return self.village_wipes + 1

    def emit(self, event: Event) -> None:
        """Append to the rolling log AND mirror to telemetry counter.

        All subagents must use this rather than touching `events` directly.
        """
        if event.type not in EVENT_TYPES:
            # Allow it but mark in telemetry — helps catch typos in dev.
            tag = "unknown"
        else:
            tag = event.type
        if self.events is not None:
            self.events.append(event)
        if self.telemetry is not None:
            self.telemetry.counter_inc("from_sim_events_total", 1.0, {"type": tag})


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def snapshot_dict(world: World) -> Dict[str, Any]:
    """The shape SocketIO emits as a 'tick' event. Frontend (Agent D) renders this.

    Agent A owns this function but B/C contribute via Agent.to_dict() overrides.
    """
    return {
        "tick": world.tick_count,
        "time": {
            "day": world.time.day,
            "hour": world.time.hour,
            "minute": world.time.minute,
            "phase": world.time.phase.value,
            "label": world.time.label(),
        },
        "lighting": round(world.lighting, 3),
        "cycle_number": world.cycle_number,
        "village_wipes": world.village_wipes,
        "food_supply": round(world.food_supply, 2),
        "food_capacity": world.food_capacity,
        "farm_health": round(world.farm_health, 3),
        "yellow": {
            "mode": world.yellow_active.mode.value,
            "disguised_as": world.yellow_active.disguised_as,
            "deadline_in": max(0, world.yellow_active.deadline_tick - world.tick_count)
            if world.yellow_active.deadline_tick
            else 0,
        },
        "narration": list(world.narrations)[-10:],
        "buildings": [
            {
                "id": b.id,
                "name": b.name,
                "x": b.x,
                "y": b.y,
                "has_talisman": b.has_talisman,
                "locked": b.locked,
                "occupants": len(b.occupants),
                "role_tag": b.role_tag,
            }
            for b in world.buildings.values()
        ],
        "agents": [a.to_dict() for a in world.agents.values()],
        "creatures": [c.to_dict() for c in world.creatures],
        "supernaturals": [s.to_dict() for s in world.supernaturals],
        "events": [
            {"tick": e.tick, "type": e.type, "subject": e.subject, "detail": e.detail, "severity": e.severity}
            for e in (list(world.events)[-50:] if world.events is not None else [])
        ],
    }


# ---------------------------------------------------------------------------
# SocketIO event names
# ---------------------------------------------------------------------------


class SocketEvent:
    TICK = "tick"            # server -> client: snapshot_dict payload
    INSPECT = "inspect"      # client -> server: {"id": "..."}
    INSPECT_REPLY = "inspect_reply"  # server -> client: full agent state
    CYCLE_RESET = "cycle_reset"      # server -> client: village wipe overlay trigger


# ---------------------------------------------------------------------------
# Metric names — keep in lockstep with telemetry.py and any dashboards
# ---------------------------------------------------------------------------


class Metric:
    AGENTS_ACTIVE = "from_sim_agents_active"          # gauge, attr: role
    NPCS_ACTIVE = "from_sim_npcs_active"              # gauge
    CREATURES_ACTIVE = "from_sim_creatures_active"    # gauge
    EVENTS_TOTAL = "from_sim_events_total"            # counter, attr: type
    LLM_CALLS_TOTAL = "from_sim_llm_calls_total"      # counter, attr: outcome, actor
    PHASE = "from_sim_phase"                          # gauge 0..3
    FOOD_SUPPLY = "from_sim_food_supply"              # gauge
    FARM_HEALTH = "from_sim_farm_health"              # gauge 0..1
    FEAR_AVG = "from_sim_fear_avg"                    # gauge
    SANITY_AVG = "from_sim_sanity_avg"                # gauge
    VILLAGE_WIPES_TOTAL = "from_sim_village_wipes_total"  # counter
    YELLOW_ACTIVE = "from_sim_yellow_active"          # gauge 0/1, attr: mode


PHASE_TO_NUM = {Phase.DAY: 0, Phase.DUSK: 1, Phase.NIGHT: 2, Phase.DAWN: 3}


# ---------------------------------------------------------------------------
# Map layout — fixed coordinates baked into the SVG (viewBox 0 0 1000 700)
# ---------------------------------------------------------------------------


BUILDING_LAYOUT: List[Tuple[str, str, float, float, int, bool, str]] = [
    # (id, name, x, y, footprint, has_talisman, role_tag)
    ("sheriff_house", "Sheriff's House", 350, 360, 4, True, "sheriff"),
    ("matthews_house", "Matthews House", 520, 380, 5, True, "matthews"),
    ("church", "Church", 430, 310, 6, True, "church"),
    ("diner", "Diner", 580, 330, 4, False, "diner"),
    ("clinic", "Clinic", 470, 420, 4, True, "clinic"),
    ("camper", "Boyd's Camper", 300, 420, 2, False, "camper"),
    ("colony_house", "Colony House", 780, 180, 10, True, "colony"),
    ("lighthouse", "Lighthouse", 500, 560, 1, False, "lighthouse"),
]

# Faraway Trees scattered around the forest perimeter
FARAWAY_TREES: List[Tuple[float, float]] = [
    (80, 120),
    (920, 150),
    (60, 560),
    (940, 580),
    (500, 40),
]

# Forest-edge spawn points for creatures (inner edge of forest ring)
FOREST_SPAWN_POINTS: List[Tuple[float, float]] = [
    (140, 110), (300, 90), (500, 85), (700, 95), (860, 130),
    (920, 280), (940, 430), (900, 580),
    (700, 620), (500, 640), (300, 625), (130, 590),
    (90, 440), (70, 290), (180, 200), (820, 220),
]

# NPC "intake" points — where new arrivals appear from the forest
NPC_INTAKE_POINTS: List[Tuple[float, float]] = [
    (140, 350), (860, 350), (500, 90), (500, 620),
]

# Yellow Man visible-march path (sequence of waypoints)
YELLOW_MARCH_PATH: List[Tuple[float, float]] = [
    (90, 350), (250, 360), (400, 380), (520, 380),
    (680, 360), (800, 320), (900, 280),
]
