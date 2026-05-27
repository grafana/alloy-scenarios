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
    # v2 additions
    DREAMING = "DREAMING"
    CALLED = "CALLED"        # heard the lighthouse — biases toward LIGHTHOUSE
    OUTSIDER_GOAL = "OUTSIDER_GOAL"  # outsiders pursuing their backstory goal


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
    OUTSIDER = "outsider"


class MarkerClass(str, enum.Enum):
    CHAR = "char"
    NPC = "npc"
    CREATURE = "creature"
    BOY_IN_WHITE = "boy-in-white"
    MAN_IN_YELLOW = "man-in-yellow"
    ANGHKOOEY = "anghkooey"
    FARAWAY_TREE = "faraway-tree"
    OUTSIDER = "outsider"
    BUS = "bus"


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
    # v2 — cross-cycle memory
    "journal_entry",
    "journal_fragment_found",
    "journal_page_burns",
    "personality_drift",
    "hash_mark_added",
    # v2 — trust
    "trust_shift",
    # v2 — dreams
    "dream_begin",
    "dream_line",
    "dream_end",
    "prophecy_set",
    "prophecy_fired",
    # v2 — bus + outsiders
    "bus_arrival",
    "bus_depart",
    "outsider_joined",
    "outsider_left",
    "outsider_died",
    # v2 — yellow hydra
    "yellow_tendril_added",
    "yellow_tendril_banished",
    # v2 — lighthouse
    "lighthouse_call",
    "lighthouse_enter",
    "lighthouse_voice",
}


@dataclass
class YellowState:
    """State of an active Man in Yellow appearance. Owned by Agent C."""
    mode: YellowMode = YellowMode.DORMANT
    disguised_as: Optional[str] = None  # npc id when in IMPOSTER mode (the "leader" tendril)
    started_at_tick: int = 0
    deadline_tick: int = 0  # absolute tick; >0 only when active
    path_index: int = 0  # for visible-march mode
    tendrils: List[str] = field(default_factory=list)  # v2: hydra mode — all imposter NPC ids


# ---------------------------------------------------------------------------
# v2 — cross-cycle memory, dreams, bus, lighthouse
# ---------------------------------------------------------------------------


@dataclass
class JournalFragment:
    """One line of village history. Lives in Legacy; partially survives wipes."""
    cycle_recorded: int
    text: str
    burned: float = 0.0  # 0=pristine, 1=unreadable


@dataclass
class Prophecy:
    """A cryptic line set in a dream that may come true 1 cycle later."""
    set_at_cycle: int
    fires_at_cycle: int
    trigger: str  # canonical event-type or pseudo-event key
    payload: str  # the line the dream visitor spoke


@dataclass
class Dream:
    """Transient — one active dream per sleeping low-sanity character."""
    character_id: str
    started_at_tick: int
    duration: int  # ticks
    lines: List[str] = field(default_factory=list)
    visitor: str = "self"  # "boy_in_white" | "anghkooey" | "self"


@dataclass
class BusState:
    """Bus arrival schedule. ``next_arrival_cycle`` survives wipes."""
    next_arrival_cycle: int = 5
    active: bool = False
    arrival_tick: int = 0
    departure_tick: int = 0
    passengers: List[str] = field(default_factory=list)  # outsider ids currently in town
    path_index: int = 0  # along YELLOW_MARCH_PATH-like waypoints (reused for bus path)
    x: float = 0.0
    y: float = 0.0


@dataclass
class Legacy:
    """The one thing the universe remembers across wipes.

    ``reset_world`` preserves this object; everything else is bulldozed.
    """
    journal_fragments: List[JournalFragment] = field(default_factory=list)
    building_breach_marks: Dict[str, int] = field(default_factory=dict)  # building_id -> count
    personality_drift: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # char_name -> {trait_name: delta}, accumulated forever
    deaths_by_creature: Dict[str, int] = field(default_factory=dict)
    cycles_witnessed: int = 0  # incremented once per village_wipe
    pending_prophecies: List[Prophecy] = field(default_factory=list)


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
    # v2 — cross-cycle memory + drift
    personality_drift_rate: float = 0.04
    journal_fragment_survival_prob: float = 0.6
    # v2 — dreams
    dream_trigger_sanity_threshold: float = 40.0
    dream_trigger_prob: float = 0.08
    dream_duration_ticks: int = 30
    # v2 — bus
    bus_arrival_cycle_interval: int = 5
    bus_stay_ticks: int = 1440
    # v2 — yellow hydra
    yellow_hydra_min: int = 2
    yellow_hydra_max: int = 3
    # v2 — lighthouse
    lighthouse_call_tick_frac: float = 0.4
    # v2 — trust
    trust_baseline: float = 0.5

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
            personality_drift_rate=_f("PERSONALITY_DRIFT_RATE", 0.04),
            journal_fragment_survival_prob=_f("JOURNAL_FRAGMENT_SURVIVAL_PROB", 0.6),
            dream_trigger_sanity_threshold=_f("DREAM_TRIGGER_SANITY_THRESHOLD", 40.0),
            dream_trigger_prob=_f("DREAM_TRIGGER_PROB", 0.08),
            dream_duration_ticks=_i("DREAM_DURATION_TICKS", 30),
            bus_arrival_cycle_interval=_i("BUS_ARRIVAL_CYCLE_INTERVAL", 5),
            bus_stay_ticks=_i("BUS_STAY_TICKS", 1440),
            yellow_hydra_min=_i("YELLOW_HYDRA_MIN", 2),
            yellow_hydra_max=_i("YELLOW_HYDRA_MAX", 3),
            lighthouse_call_tick_frac=_f("LIGHTHOUSE_CALL_TICK_FRAC", 0.4),
            trust_baseline=_f("TRUST_BASELINE", 0.5),
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

    # --- v2: cross-cycle memory, dreams, bus, lighthouse, trust ---
    legacy: "Legacy" = field(default_factory=lambda: Legacy())  # persists through wipes
    trust: Dict[Tuple[str, str], float] = field(default_factory=dict)  # (id_a, id_b) -> [0,1]
    active_dreams: List[Dream] = field(default_factory=list)
    bus: BusState = field(default_factory=BusState)
    lighthouse_called: Optional[str] = None  # char id when a call is active
    lighthouse_voice_active: bool = False

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


def _enrich_agent(agent: Agent, world: World) -> Dict[str, Any]:
    """Decorate the bare agent dict with cross-cycle fields known only to World.

    Currently adds a ``drift`` bool for named characters who have any non-zero
    entry in ``world.legacy.personality_drift``. Outsiders already expose
    ``backstory`` / ``goal`` via their own to_dict; we don't override those.
    """
    d = agent.to_dict()
    name = getattr(agent, "name", None)
    if name and getattr(agent, "kind", None) == AgentKind.CHARACTER:
        deltas = world.legacy.personality_drift.get(name)
        d["drift"] = bool(deltas) and any(abs(v) > 1e-6 for v in deltas.values())
    return d


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
            "tendrils": list(world.yellow_active.tendrils),
            "deadline_in": max(0, world.yellow_active.deadline_tick - world.tick_count)
            if world.yellow_active.deadline_tick
            else 0,
        },
        "narration": list(world.narrations)[-10:],
        "legacy": {
            "cycles_witnessed": world.legacy.cycles_witnessed,
            "journal_fragments": [
                {"text": j.text, "burned": round(j.burned, 2), "cycle": j.cycle_recorded}
                for j in world.legacy.journal_fragments[-12:]
            ],
            "building_breach_marks": dict(world.legacy.building_breach_marks),
            "pending_prophecies": len(world.legacy.pending_prophecies),
        },
        "dreams": [
            {"character_id": d.character_id, "lines": list(d.lines),
             "visitor": d.visitor, "duration_left": max(0, d.duration - (world.tick_count - d.started_at_tick))}
            for d in world.active_dreams
        ],
        "bus": {
            "active": world.bus.active,
            "passengers": list(world.bus.passengers),
            "next_arrival_cycle": world.bus.next_arrival_cycle,
            "x": round(world.bus.x, 2),
            "y": round(world.bus.y, 2),
            "departure_in_ticks": (
                max(0, world.bus.departure_tick - world.tick_count)
                if world.bus.active and world.bus.departure_tick
                else 0
            ),
        },
        "lighthouse": {
            "called": world.lighthouse_called,
            "voice_active": world.lighthouse_voice_active,
        },
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
        "agents": [_enrich_agent(a, world) for a in world.agents.values()],
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
    # v2 metrics
    LEGACY_JOURNAL_FRAGMENTS = "from_sim_legacy_journal_fragments"  # gauge
    LEGACY_CYCLES_WITNESSED = "from_sim_legacy_cycles_witnessed"    # gauge
    OUTSIDERS_ACTIVE = "from_sim_outsiders_active"                  # gauge
    YELLOW_TENDRILS = "from_sim_yellow_tendrils"                    # gauge
    LIGHTHOUSE_VOICE_ACTIVE = "from_sim_lighthouse_voice_active"    # gauge 0/1
    DREAMS_ACTIVE = "from_sim_dreams_active"                        # gauge
    TRUST_AVG = "from_sim_trust_avg"                                # gauge


PHASE_TO_NUM = {Phase.DAY: 0, Phase.DUSK: 1, Phase.NIGHT: 2, Phase.DAWN: 3}


# ---------------------------------------------------------------------------
# Map layout — fixed coordinates baked into the SVG (viewBox 0 0 1000 700)
# ---------------------------------------------------------------------------


# 18 town buildings + the Lighthouse (separate clearing). 5 talisman-protected.
# Coordinates match the hand-drawn Fromville map (viewBox 0 0 1000 700).
BUILDING_LAYOUT: List[Tuple[str, str, float, float, int, bool, str]] = [
    # (id, name, x, y, footprint, has_talisman, role_tag)
    ("colony_house",     "Colony House",            385, 420, 10, True,  "colony"),
    ("green_house",      "Green House",             418, 400,  3, False, "house"),
    ("shed",             "Shed",                    442, 388,  1, False, "shed"),
    ("clinic",           "Clinic",                  478, 402,  4, True,  "clinic"),
    ("root_cellar",      "Root Cellar",             495, 432,  2, False, "cellar"),
    ("choosing_stone",   "Choosing Ceremony Stone", 390, 470,  0, False, "stone"),
    ("church",           "Church",                  385, 510,  6, True,  "church"),
    ("grey_house",       "Grey House",              420, 490,  3, False, "house"),
    ("blue_house",       "Blue House",              440, 490,  3, False, "house"),
    ("pool",             "Pool",                    462, 478,  0, False, "pool"),
    ("lius_home",        "Liu's Home",              478, 462,  4, False, "house"),
    ("bar",              "Bar",                     510, 458,  3, False, "bar"),
    ("barn",             "Barn",                    555, 454,  5, False, "barn"),
    ("sheriff_office",   "Sheriff's Office",        490, 510,  4, True,  "sheriff"),
    ("abandoned_bus",    "Abandoned Bus",           460, 538,  0, False, "wreck"),
    ("matthews_home",    "Matthews' Home",          430, 545,  5, True,  "matthews"),
    ("diner",            "Diner",                   405, 530,  4, False, "diner"),
    ("myers_home",       "Myers' Home",             382, 552,  3, False, "house"),
    # Lighthouse lives in its own clearing south-west of town.
    ("lighthouse",       "Lighthouse",              140, 585,  1, False, "lighthouse"),
]

# Faraway / Bottle Trees scattered around the surrounding land.
# Tree 1 (Boyd / Sara), Tree 2 (Victor / Ethan), Tree 3 (south).
FARAWAY_TREES: List[Tuple[float, float]] = [
    (560, 55),
    (735, 485),
    (575, 660),
]

# Creature spawn points — 16 around a ring centred on the town cluster
# (cx=465, cy=475, rx=220, ry=165), matching the generated wedges in the
# hand-drawn map's spawn-toggle overlay.
import math as _math
_RING_CX, _RING_CY, _RING_RX, _RING_RY = 465.0, 475.0, 220.0, 165.0
FOREST_SPAWN_POINTS: List[Tuple[float, float]] = [
    (
        _RING_CX + _math.cos((i / 16.0) * _math.tau - _math.pi / 2) * _RING_RX,
        _RING_CY + _math.sin((i / 16.0) * _math.tau - _math.pi / 2) * _RING_RY,
    )
    for i in range(16)
]
del _math, _RING_CX, _RING_CY, _RING_RX, _RING_RY

# NPC arrival points — the S-curve road enters from the west, leaves to the
# south-east, and has a spur into town. New arrivals appear at road edges.
NPC_INTAKE_POINTS: List[Tuple[float, float]] = [
    (20, 210),    # west end of the road, off-map entry
    (760, 720),   # south-east end of the road, off-map exit
    (240, 320),   # along the road between the two
    (565, 540),   # spur into town from the south
]

# Yellow Man visible-march path — west to east along the road through town.
YELLOW_MARCH_PATH: List[Tuple[float, float]] = [
    (0, 200), (160, 280), (240, 320), (395, 405),
    (555, 405), (575, 425), (565, 555), (720, 690),
]

# Bus path — drives in along the S-curve, parks just off the spur near the
# diner (NOT the abandoned wreck, which is a static map feature), drives out.
BUS_PATH_IN: List[Tuple[float, float]] = [
    (-20, 200), (80, 240), (240, 320), (395, 405), (520, 410),
]
BUS_PARK: Tuple[float, float] = (520, 425)   # on the road spur near the diner
BUS_PATH_OUT: List[Tuple[float, float]] = [
    (520, 425), (575, 425), (565, 555), (720, 690), (760, 720),
]

# Lighthouse direct-coord alias (lighthouse.py and bus.py read this).
LIGHTHOUSE_XY: Tuple[float, float] = (140.0, 585.0)
