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
    CAR_GRAVEYARD_XY,
    CAVE_ENTRY_XY,
    CHOOSING_STONE_XY,
    CRASH_SITE_XY,
    Event,
    FARAWAY_TREES,
    FOREST_SPAWN_POINTS,
    GRAVE_MOUNDS,
    HIDEOUT_TRUCK_XY,
    Item,
    LIGHTHOUSE_XY,
    MarkerClass,
    Phase,
    Role,
    RUINS_XY,
    State,
    Status,
    WINDMILL_XY,
    World,
)

# v4: rhyme lines surfaced by Sara, keyed by current music box phase.
_RHYME_LINES: Dict[str, str] = {
    "TOUCH": "They touch — I can hear it from the ruins.",
    "BREAK": "They break — it took Paula. Or someone. Soon.",
    "STEAL": "They come for three. The dungeon. Take it there.",
    "TERMINAL": "They come for three… we are too late.",
}

# v4: ~one sim day at 2 Hz; rhyme cadence for Sara.
_RHYME_TICK_GAP = 720

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
    # v6 — INVESTIGATOR / SEER actively seek out the caves during DAY so we
    # see characters physically explore the unused landmark. EXPLORING_CAVES
    # joins their role-bonus list (2× weight).
    Role.INVESTIGATOR: [State.INVESTIGATING, State.EXPLORING_CAVES, State.WANDERING, State.ARGUING],
    Role.DEPUTY: [State.PATROLLING, State.CARETAKING, State.MEETING],
    Role.PRIEST: [State.PRAYING, State.CONVERSING, State.MEDIATING],
    Role.SEER: [State.WANDERING, State.EXPLORING_CAVES, State.CONVERSING],
}

ROLE_BONUS = 2.0

# Awareness threshold — once a yellow-touched NPC has accumulated this much
# suspicion in a character's eyes, that character will call for a meeting.
AWARENESS_PROXIMITY = 80.0  # px — within this we bump awareness each tick
AWARENESS_BUMP_PER_TICK = 0.05

# Per-tick drift constants.
HUNGER_RATE = 0.04
# In EATING state with food available, hunger drops faster than it climbs and
# the meal taxes the larder. Tuned so 1 EATING tick erases roughly 1 minute of
# normal hunger gain — characters don't need to camp at the diner all day, a
# couple of minutes of eating brings them back to comfortable.
HUNGER_EATING_RECOVERY = 0.40
# Food drained per character-tick spent eating, on top of the per-agent
# background drain in food.py. Kept small so the village's standing larder
# is mostly drained by passive consumption rather than active eaters.
HUNGER_EATING_FOOD_COST = 0.02
FATIGUE_RATE = 0.03
SANITY_RECOVERY = 0.05
# Sleeping (only valid when sheltered) restores sanity quickly so a peaceful
# night offsets the wakeful corrosion. Tuned so a ~6 sim-hour rest gets a
# character from 0 back to ~70 — enough to function the next day.
SANITY_SLEEP_RECOVERY = 0.20
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
        dwelling_id="sheriff_office",
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
        dwelling_id="matthews_home",
        role=Role.ENGINEER,
        personality={"brave": 0.7, "social": 0.5, "devout": 0.2,
                     "paranoid": 0.6, "caretaker": 0.5, "leader": 0.4},
        schedule=[(Phase.DAY, State.REPAIRING), (Phase.NIGHT, State.SHELTERING)],
    ),
    _Seed(
        name="Tabitha",
        dwelling_id="matthews_home",
        role=Role.CARETAKER,
        personality={"brave": 0.5, "social": 0.7, "devout": 0.6,
                     "paranoid": 0.5, "caretaker": 0.95, "leader": 0.4},
        schedule=[(Phase.DAY, State.CARETAKING), (Phase.DUSK, State.MOURNING)],
    ),
    _Seed(
        name="Ethan",
        dwelling_id="matthews_home",
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
        dwelling_id="lius_home",
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
        dwelling_id="myers_home",
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
        # v5 — passive event observation (avoid recording the same event twice).
        self._last_observed_event_tick: int = -10_000

        # v6 — short human-readable sentence describing what this character is
        # doing right now. Refreshed on every _enter(); also rotated when the
        # CALLED override kicks in. Surfaced via to_dict() for the roster row +
        # dossier "Right now" line. Default empty until first _enter().
        self.intent: str = ""
        # v8 — flips True when the character is at their dwelling in a
        # SHELTERING/SLEEPING/DREAMING state. The frontend reads this and
        # hides the map token so the user sees who is exposed.
        self._indoors: bool = False
        # v6 — cursors for landmark rotations. Lazy zero-init.
        self._patrol_index: int = 0
        self._invest_index: int = 0
        # v6 — last major intent category emitted as an ``intent_change`` event.
        # Used to keep the event log sparse — only fire when category changes.
        self._last_intent_category: str = ""
        # v9 — per-character cognitive layer. Lazy import to dodge the
        # ``characters`` ↔ ``mind`` cycle at module-load time.
        try:
            from agents.mind import Mind
            self.mind = Mind(self.id)
        except Exception:
            self.mind = None

    # ----------------------------------------------------------- v5 inventory
    def _inv_has(self, item: str) -> bool:
        """True if this character is carrying at least one of ``item``."""
        try:
            return int(self.inventory.get(item, 0)) > 0
        except Exception:
            return False

    def _inv_add(self, item: str, delta: int, world: World) -> int:
        """Adjust inventory, persist to memory, and emit pickup/drop events.

        Returns the new quantity. ``delta`` may be negative to drop. Quantity
        is clamped at zero — callers should check ``_inv_has`` before
        attempting a drop.
        """
        try:
            cur = int(self.inventory.get(item, 0))
        except Exception:
            cur = 0
        new = max(0, cur + int(delta))
        if new == 0:
            self.inventory.pop(item, None)
        else:
            self.inventory[item] = new
        # v5 — record via memory if attached.
        if world.memory is not None:
            try:
                world.memory.record_inventory_change(
                    world, self.id, item, int(delta), new,
                )
            except Exception:
                pass
        # Emit a canonical event so other subsystems see the transfer.
        if delta > 0:
            world.emit(Event(
                tick=world.tick_count, type="item_picked_up",
                subject=self.id, detail=f"{item} x{int(delta)} (have {new})",
            ))
        elif delta < 0:
            world.emit(Event(
                tick=world.tick_count, type="item_dropped",
                subject=self.id, detail=f"{item} x{abs(int(delta))} (have {new})",
            ))
        return new

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

        # ---- v4: Sara/Khatri/Boyd music-box reactions --------------------
        self._music_box_reaction(world)

        # ---- Drives & sanity ---------------------------------------------
        # Hunger rises every tick unless the agent is actively eating AND
        # there's food in the larder. EATING in an empty village still drains
        # nothing (food is gone) but it doesn't satisfy them either, so the
        # food economy stays load-bearing.
        if self.state == State.EATING and world.food_supply > 0:
            self.hunger = max(0.0, self.hunger - HUNGER_EATING_RECOVERY)
            world.food_supply = max(0.0, world.food_supply - HUNGER_EATING_FOOD_COST)
        else:
            self.hunger = min(100.0, self.hunger + HUNGER_RATE)
        if self.state == State.SLEEPING:
            self.fatigue = max(0.0, self.fatigue - FATIGUE_RATE * 5)
        else:
            self.fatigue = min(100.0, self.fatigue + FATIGUE_RATE)
        # Sanity drain: NIGHT outside of sleep is corrosive. NIGHT spent
        # asleep recovers modestly; daytime recovery is gentle but enough to
        # claw back most of an undisturbed night by sundown.
        if world.time.phase == Phase.NIGHT and self.state != State.SLEEPING:
            self.sanity = max(0.0, self.sanity - SANITY_NIGHT_DRAIN)
        elif self.state == State.SLEEPING:
            self.sanity = min(100.0, self.sanity + SANITY_SLEEP_RECOVERY)
        else:
            self.sanity = min(100.0, self.sanity + SANITY_RECOVERY)
        # Starvation: above ~85 hunger, sanity erodes slowly. Above 95, fear
        # creeps up too. This couples the food economy back into the panic
        # loop so creature nights are deadlier when the larder is empty.
        if self.hunger > 85:
            self.sanity = max(0.0, self.sanity - 0.02)
        if self.hunger > 95:
            self.fear = min(100.0, self.fear + 0.03)

        # ---- Awareness: bump for nearby yellow-touched NPCs --------------
        self._update_awareness(world)

        # ---- v5: passive observation of recent breach events --------------
        self._observe_recent_events(world)

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

        # ---- v9: cognitive bias ------------------------------------------
        # Reflection (cadence-gated inside) and goal-derived menu weights.
        # Bias is additive on existing weights; the weighted-FSM choice
        # below still makes the final pick, so SEED determinism holds.
        extra_context = ""
        if getattr(self, "mind", None) is not None:
            try:
                self.mind.maybe_reflect(world, self)
                menu = self.mind.shape_menu(world, self, menu)
                extra_context = self.mind.goal_context()
            except Exception:  # never let cognition kill a tick
                pass

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
                # v9 — call site previously passed (self, world, menu) which
                # didn't match the decider signature; it always raised and
                # the LLM never actually fired. Pass the real arguments.
                menu_states = [s for s, _ in menu]
                result = world.llm_decider.maybe_decide(
                    actor_id=self.id,
                    current_state=self.state,
                    phase=world.time.phase,
                    fear=float(self.fear),
                    menu=menu_states,
                    current_tick=int(world.tick_count),
                    extra_context=extra_context,
                )
                if isinstance(result, tuple) and result:
                    chosen = result[0]
                elif isinstance(result, State):
                    chosen = result
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

        # v8 — keep the CONVERSING target refreshed each tick so partners
        # actually converge instead of drifting apart with stale targets.
        if self.state == State.CONVERSING:
            self.target = self._target_for_role_and_state(self.state, world)

        self._step_toward_target(world)

        # v8 — track whether the character is actually inside their dwelling.
        # When indoors, the frontend hides the map token so the user can see
        # who is exposed. We also keep the building's occupants set live so
        # the click-house dossier reflects "who is here right now".
        self._update_indoor_presence(world)

    def _update_indoor_presence(self, world: World) -> None:
        """Sync ``self._indoors`` and the dwelling's occupant set."""
        from agents.base import distance as _dist
        home = world.buildings.get(self.dwelling_id) if self.dwelling_id else None
        # Indoor states + close to the dwelling => indoors.
        indoor_states = (State.SHELTERING, State.SLEEPING, State.DREAMING)
        is_indoors = False
        if home is not None and self.state in indoor_states:
            if _dist(self, home) <= 24.0:
                is_indoors = True
        # Update occupancy set + flag.
        if is_indoors:
            if home is not None:
                home.occupants.add(self.id)
            self._indoors = True
        else:
            if home is not None and self.id in home.occupants:
                home.occupants.discard(self.id)
            self._indoors = False

    # ----------------------------------------------------------- v4 helpers
    def _music_box_reaction(self, world: World) -> None:
        """Sara hears the Rhyme; Khatri calls a meeting; Boyd grabs the box.

        All three reactions are character-role-gated and self-throttled with
        per-instance state. None of them mutate engine-owned fields except via
        the documented v4 contracts (``world.music_box_carrier`` / events).
        """
        phase = getattr(world, "music_box_phase", "DORMANT")

        # ---- Sara hears the music (SEER + non-dormant box) -----------------
        if self.role == Role.SEER and phase != "DORMANT":
            last_tick = getattr(self, "_sara_last_rhyme_tick", -10_000)
            last_phase = getattr(self, "_sara_last_phase", None)
            # Find nearest music box marker (if any) within 200 px.
            near_box = False
            try:
                for s in world.supernaturals:
                    if getattr(s, "marker_class", None) == MarkerClass.MUSIC_BOX:
                        d = math.hypot(self.x - s.x, self.y - s.y)
                        if d <= 200.0:
                            near_box = True
                            break
            except Exception:
                near_box = False
            phase_advanced = (phase != last_phase)
            cadence_ok = (world.tick_count - last_tick) >= _RHYME_TICK_GAP
            if (cadence_ok and near_box) or phase_advanced:
                line = _RHYME_LINES.get(phase)
                if line:
                    try:
                        world.narrations.append({
                            "actor": "Sara",
                            "reason": line,
                            "state": State.WANDERING.value,
                        })
                        if len(world.narrations) > 50:
                            del world.narrations[: len(world.narrations) - 50]
                    except Exception:
                        pass
                    try:
                        world.rhyme_heard.append(line)
                    except Exception:
                        pass
                    world.emit(Event(
                        tick=world.tick_count, type="rhyme_heard",
                        subject=self.id, detail=line, severity="warn",
                    ))
                    self.sanity = max(0.0, self.sanity - 0.3)
                    self._sara_last_rhyme_tick = world.tick_count
                    self._sara_last_phase = phase
                    world._sara_has_warned = True  # type: ignore[attr-defined]

        # ---- Khatri calls the meeting (PRIEST after Sara has warned) -------
        if (
            self.role == Role.PRIEST
            and getattr(world, "_sara_has_warned", False)
            and self.state not in (State.MEETING, State.ARGUING,
                                   State.DREAMING, State.IRRATIONAL)
            and not getattr(self, "_khatri_proposed_destroy", False)
        ):
            already = any(
                mo.topic == "destroy_music_box"
                for mo in (world.meeting_outcomes or [])
            )
            if not already:
                try:
                    from agents.social import propose_meeting
                    propose_meeting(world, "Khatri", "destroy_music_box", "church")
                    self._khatri_proposed_destroy = True
                except Exception:
                    pass

        # ---- Boyd picks up the box (SHERIFF) -------------------------------
        if (
            self.role == Role.SHERIFF
            and getattr(world, "music_box_carrier", None) is None
            and phase != "DORMANT"
        ):
            try:
                target = None
                for s in world.supernaturals:
                    if getattr(s, "marker_class", None) != MarkerClass.MUSIC_BOX:
                        continue
                    d = math.hypot(self.x - s.x, self.y - s.y)
                    if d <= 80.0:
                        target = s
                        break
                if target is not None:
                    world.music_box_carrier = self.id
                    self.state = State.CARRYING_BOX
                    self.state_since_tick = world.tick_count
                    world.emit(Event(
                        tick=world.tick_count, type="music_box_picked_up",
                        subject=self.id,
                        detail="Boyd took it from where it was dropped.",
                        severity="warn",
                    ))
            except Exception:
                pass

    # ----------------------------------------------------------- helpers
    def _hard_override(self, world: World) -> Optional[State]:
        if self.state == State.IRRATIONAL:
            return State.IRRATIONAL  # sticky
        # v6 — once the lighthouse picks you, you walk to it. Sticky until the
        # lighthouse module clears ``world.lighthouse_called`` (e.g. on
        # swallow / cycle reset). agents/lighthouse.py owns the selection;
        # this branch just enforces the destination bias.
        if self.state == State.CALLED:
            return State.CALLED  # sticky
        if getattr(world, "lighthouse_called", None) == self.id:
            return State.CALLED
        if self.fear > 80.0:
            return State.FLEEING
        if world.time.phase == Phase.NIGHT:
            b = world.buildings.get(self.dwelling_id)
            if b is not None and b.has_talisman:
                return State.SHELTERING
        # Starving and safe: drop everything and find food. Diner/Bar by day,
        # dwelling kitchen otherwise. Skipped when already eating so we don't
        # thrash transitions.
        if (
            self.hunger > 75.0
            and self.state != State.EATING
            and world.food_supply > 0
            and world.time.phase in (Phase.DAY, Phase.DUSK, Phase.DAWN)
        ):
            return State.EATING
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
        # v4: music-box carrier wants to deal with this — strong EXPEDITION bias.
        if self.id == getattr(world, "music_box_carrier", None):
            # Either boost an existing EXPEDITION slot, or inject one so the
            # LLM (and any future relaxed precondition) sees the intent.
            boosted = False
            for i, (s, w) in enumerate(out):
                if s == State.EXPEDITION:
                    out[i] = (s, w * 3.0)
                    boosted = True
                    break
            if not boosted:
                out.append((State.EXPEDITION, 3.0))
        # v7: barn destroyed → strong FORAGING bias for any character whose
        # current state is reasonably interruptible (FARMING/WANDERING/
        # GOSSIPING/SCAVENGING). Also nudges when food is low even without a
        # barn breach. ENGINEER takes a smaller boost — they head to repair
        # instead (see REPAIRING below).
        barn_down = (
            getattr(world, "barn_destroyed_until_tick", 0) > world.tick_count
        )
        food_low = getattr(world, "food_shortage", False)
        if (barn_down or food_low) and world.time.phase == Phase.DAY:
            mult = 4.0 if barn_down else 2.0
            # ENGINEER's role is to fix; they get a REPAIRING boost not FORAGING.
            if self.role == Role.ENGINEER and barn_down:
                boosted_repair = False
                for i, (s, w) in enumerate(out):
                    if s == State.REPAIRING:
                        out[i] = (s, w * 4.0)
                        boosted_repair = True
                        break
                if not boosted_repair:
                    out.append((State.REPAIRING, 4.0))
            else:
                boosted = False
                for i, (s, w) in enumerate(out):
                    if s == State.FORAGING:
                        out[i] = (s, w * mult)
                        boosted = True
                        break
                if not boosted:
                    # Inject FORAGING into the menu if it wasn't already there
                    # (transition table only lists it from FARMING).
                    out.append((State.FORAGING, mult))
        # v5: nudge from SQLite memory before returning.
        out = self._apply_memory_bias_list(out, world)
        return out

    # ----------------------------------------------------------- v5 memory
    def _apply_memory_bias_list(
        self, menu: List[Tuple[State, float]], world: World,
    ) -> List[Tuple[State, float]]:
        """Bias a (state, weight) list by recent character_memory rows.

        Wraps :meth:`_apply_memory_bias` so callers can keep menu as a list of
        tuples (the format the LLM/weighted-choice expects). Falls through
        without error if memory is missing or malformed.
        """
        if world.memory is None or not menu:
            return menu
        weights: Dict[State, float] = {s: w for s, w in menu}
        try:
            biased = self._apply_memory_bias(weights, world)
        except Exception:
            return menu
        return [(s, biased.get(s, w)) for s, w in menu]

    def _apply_memory_bias(
        self, weights: Dict[State, float], world: World,
    ) -> Dict[State, float]:
        """Multiplier-style bias from this character's recent memory.

        Pulls in argument / breach / meeting rows for the configured recall
        window and scales relevant state weights. Carrying a music box also
        boosts EXPEDITION via the memory channel so v4 carrier behaviour
        survives even when the engine's transient ``music_box_carrier`` flag
        is briefly cleared.
        """
        if world.memory is None:
            return weights
        cfg = world.config
        recall_window = int(getattr(cfg, "memory_recall_window_ticks", 1200))

        try:
            recent_args = world.memory.recall_for(
                world, self.id,
                kinds={"argument", "meeting_disagree"},
                lookback_ticks=recall_window,
            )
        except Exception:
            recent_args = []
        if recent_args:
            if State.ARGUING in weights:
                weights[State.ARGUING] *= 1.30
            if State.CONVERSING in weights:
                weights[State.CONVERSING] *= 0.60

        try:
            recent_breaches = world.memory.recall_for(
                world, self.id,
                kinds={"breach_observed"},
                lookback_ticks=1500,
            )
        except Exception:
            recent_breaches = []
        if recent_breaches:
            if State.SHELTERING in weights:
                weights[State.SHELTERING] *= 0.50

        try:
            positive_meetings = world.memory.recall_for(
                world, self.id,
                kinds={"meeting_agree", "recognized"},
                lookback_ticks=1500,
            )
        except Exception:
            positive_meetings = []
        if positive_meetings and len(positive_meetings) >= 2:
            if State.MEETING in weights:
                weights[State.MEETING] *= 1.20

        # Carrying a music box — reinforce v4 carrier behaviour via memory.
        if self._inv_has(Item.MUSIC_BOX.value):
            if State.EXPEDITION in weights:
                weights[State.EXPEDITION] *= 3.0

        return weights

    # ----------------------------------------------------------- v5 observe
    def _observe_recent_events(self, world: World) -> None:
        """Record a ``breach_observed`` memory if a creature_breach happened nearby.

        We peek at the tail of ``world.events`` and use a ``_last_observed_event_tick``
        guard so we never write the same observation twice.
        """
        if world.memory is None:
            return
        events = world.events
        if events is None:
            return
        try:
            recent = list(events)[-5:]
        except Exception:
            return
        for evt in recent:
            try:
                if evt.tick <= self._last_observed_event_tick:
                    continue
                if evt.type != "creature_breach":
                    continue
            except Exception:
                continue
            # Locate the building involved. Subject may be the building id
            # (npc_problems.py path) or the creature id (creatures.py path,
            # in which case the building name lives in the detail).
            building_id: Optional[str] = None
            subj = getattr(evt, "subject", "") or ""
            if subj in world.buildings:
                building_id = subj
            else:
                detail = (getattr(evt, "detail", "") or "").lower()
                for bid, b in world.buildings.items():
                    if b.name.lower() in detail:
                        building_id = bid
                        break
            # Skip if we can't locate the building.
            if building_id is None:
                continue
            b = world.buildings.get(building_id)
            if b is None:
                continue
            d = math.hypot(self.x - b.x, self.y - b.y)
            if d > 200.0:
                continue
            try:
                world.memory.record_character_memory(
                    world, self.id, "breach_observed", subject=building_id,
                )
            except Exception:
                pass
            self._last_observed_event_tick = evt.tick

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
        # v6 — CALLED is set externally by lighthouse.py; do not let the
        # weighted FSM wander into it on its own.
        if s == State.CALLED:
            return False
        # v6 — EXPLORING_CAVES is a DAY-only investigative state, primarily for
        # the INVESTIGATOR and SEER. Other roles may occasionally take it but at
        # a much lower weight (handled by base weight + role bonus in the
        # transition table); the precondition here just gates time-of-day.
        if s == State.EXPLORING_CAVES:
            if world.time.phase != Phase.DAY:
                return False
        # v7 — FORAGING is DAY-only. Walking 200+ px to the windmill at night
        # would just feed the foragers to a creature.
        if s == State.FORAGING:
            if world.time.phase != Phase.DAY:
                return False
        return True

    def _enter(self, world: World, new_state: State) -> None:
        if new_state == self.state:
            return
        self.state = new_state
        self.state_since_tick = world.tick_count
        self.target = self._target_for_role_and_state(new_state, world)
        # v6 — refresh intent sentence on every state change.
        self._refresh_intent(world)

    # ----------------------------------------------------------- v6 landmarks
    # Patrol rotation order — used by SHERIFF / DEPUTY in PATROLLING.
    _PATROL_ROUTE: List[str] = [
        "sheriff_office", "church", "colony_house", "diner",
    ]

    # SEER (Sara) investigation rotation — far trees + the choosing stone.
    _SEER_INVEST_POINTS: List[Tuple[float, float]] = [
        FARAWAY_TREES[0], FARAWAY_TREES[1], FARAWAY_TREES[2], CHOOSING_STONE_XY,
    ]

    # INVESTIGATOR (Jade) investigation rotation — every unsolved landmark.
    _INVESTIGATOR_POINTS: List[Tuple[float, float]] = [
        CAVE_ENTRY_XY, CRASH_SITE_XY, HIDEOUT_TRUCK_XY, CHOOSING_STONE_XY,
    ]

    # Wandering pool (used when paranoia is low).
    _WANDER_POINTS: List[Tuple[float, float]] = [
        CHOOSING_STONE_XY, WINDMILL_XY, CAR_GRAVEYARD_XY,
    ]

    # Friendly landmark names keyed by exact (x, y). Used by intent strings.
    _LANDMARK_NAMES: Dict[Tuple[float, float], str] = {
        CAVE_ENTRY_XY: "the caves",
        CRASH_SITE_XY: "the crash site",
        HIDEOUT_TRUCK_XY: "the hideout truck",
        CHOOSING_STONE_XY: "the Choosing Stone",
        WINDMILL_XY: "the windmill",
        CAR_GRAVEYARD_XY: "the car graveyard",
        LIGHTHOUSE_XY: "the lighthouse",
        RUINS_XY: "the Dungeon",
        FARAWAY_TREES[0]: "the Faraway Tree",
        FARAWAY_TREES[1]: "the Faraway Tree",
        FARAWAY_TREES[2]: "the Faraway Tree",
    }

    def _target_for_role_and_state(
        self, s: State, world: World,
    ) -> Optional[Tuple[float, float]]:
        """v6 purposeful-movement table.

        Every state resolves to a real landmark (or a per-role rotation of
        landmarks) rather than a random map coordinate, so the viewer can
        always read what a character is doing from where they are walking.
        """
        rng = world.rng
        b = world.buildings.get(self.dwelling_id)
        home = (b.x, b.y) if b else (self.x, self.y)

        if s in (State.SLEEPING, State.SHELTERING, State.DREAMING):
            return home
        if s == State.FLEEING:
            return home
        if s == State.EATING:
            # Day -> diner; otherwise home kitchen.
            if world.time.phase in (Phase.DAY, Phase.DAWN, Phase.DUSK):
                diner = world.buildings.get("diner")
                if diner is not None:
                    return (diner.x, diner.y)
            return home
        if s == State.GOSSIPING:
            diner = world.buildings.get("diner")
            return (diner.x, diner.y) if diner else home
        if s == State.PRAYING:
            ch = world.buildings.get("church")
            return (ch.x, ch.y) if ch else home
        if s == State.FARMING:
            ch = world.buildings.get("colony_house")
            return (ch.x + 20, ch.y + 60) if ch else home
        if s == State.REPAIRING:
            # Pick the building still cooling off the longest; otherwise the
            # sheriff's office as a sensible default for the engineer.
            best_b = None
            best_left = 0
            for bld in world.buildings.values():
                left = bld.cooling_off_until_tick - world.tick_count
                if left > best_left:
                    best_left = left
                    best_b = bld
            if best_b is not None:
                return (best_b.x, best_b.y)
            so = world.buildings.get("sheriff_office")
            return (so.x, so.y) if so else home
        if s in (State.CARETAKING, State.MEDICAL_CARE):
            clinic = world.buildings.get("clinic")
            return (clinic.x, clinic.y) if clinic else home
        if s == State.PLAYING:
            # Children play between the pool and the bar — a real "village
            # green" cluster rather than empty coordinates.
            pool = world.buildings.get("pool")
            cx, cy = (pool.x, pool.y) if pool else (470.0, 480.0)
            return (cx + rng.uniform(-25, 25), cy + rng.uniform(-25, 25))
        if s == State.PATROLLING:
            if self.role in (Role.SHERIFF, Role.DEPUTY):
                route = self._PATROL_ROUTE
                bid = route[self._patrol_index % len(route)]
                self._patrol_index = (self._patrol_index + 1) % len(route)
                bld = world.buildings.get(bid)
                if bld is not None:
                    return (
                        bld.x + rng.uniform(-8.0, 8.0),
                        bld.y + rng.uniform(-8.0, 8.0),
                    )
            # Fallback: village centre near sheriff's office.
            so = world.buildings.get("sheriff_office")
            if so is not None:
                return (so.x + rng.uniform(-40, 40), so.y + rng.uniform(-40, 40))
            return home
        if s == State.WANDERING:
            paranoid = self.personality.get("paranoid", 0.0)
            if paranoid > 0.5 and FOREST_SPAWN_POINTS:
                tx, ty = rng.choice(FOREST_SPAWN_POINTS)
                return (tx + rng.uniform(-10, 10), ty + rng.uniform(-10, 10))
            # Mostly-safe wanderers visit map landmarks.
            pool = list(self._WANDER_POINTS) + [rng.choice(FARAWAY_TREES)]
            bus = world.buildings.get("abandoned_bus")
            if bus is not None:
                pool.append((bus.x, bus.y))
            tx, ty = rng.choice(pool)
            return (tx + rng.uniform(-12, 12), ty + rng.uniform(-12, 12))
        if s == State.SCAVENGING:
            if FOREST_SPAWN_POINTS:
                # Pick the closest 3 forest waypoints and choose randomly
                # among them — keeps scavenging local rather than teleporty.
                pts = sorted(
                    FOREST_SPAWN_POINTS,
                    key=lambda p: math.hypot(p[0] - self.x, p[1] - self.y),
                )[:3]
                tx, ty = rng.choice(pts)
                return (tx + rng.uniform(-8, 8), ty + rng.uniform(-8, 8))
            return home
        if s == State.INVESTIGATING:
            if self.role == Role.SEER:
                pts = self._SEER_INVEST_POINTS
                tx, ty = pts[self._invest_index % len(pts)]
                self._invest_index = (self._invest_index + 1) % len(pts)
                return (tx + rng.uniform(-10, 10), ty + rng.uniform(-10, 10))
            if self.role == Role.INVESTIGATOR:
                pts = self._INVESTIGATOR_POINTS
                tx, ty = pts[self._invest_index % len(pts)]
                self._invest_index = (self._invest_index + 1) % len(pts)
                return (tx + rng.uniform(-10, 10), ty + rng.uniform(-10, 10))
            # Other roles: poke around a building entrance.
            bld_ids = list(world.buildings.keys())
            if bld_ids:
                bld = world.buildings[rng.choice(bld_ids)]
                return (bld.x + rng.uniform(-15, 15), bld.y + rng.uniform(-15, 15))
            return home
        if s == State.EXPLORING_CAVES:
            return (
                CAVE_ENTRY_XY[0] + rng.uniform(-8, 8),
                CAVE_ENTRY_XY[1] + rng.uniform(-8, 8),
            )
        if s == State.FORAGING:
            # v7 — pick a forage zone (windmill/lake/pond). We stick to the
            # one we chose at state entry by stashing it on the character; on
            # first entry the cursor is None so we pick at random.
            from contracts import FORAGE_ZONES
            chosen = getattr(self, "_forage_zone", None)
            if chosen is None or chosen not in FORAGE_ZONES:
                chosen = rng.choice(FORAGE_ZONES)
                self._forage_zone = chosen
            return (chosen[0] + rng.uniform(-12, 12), chosen[1] + rng.uniform(-12, 12))
        if s == State.CALLED:
            return LIGHTHOUSE_XY
        if s == State.MOURNING:
            # Nearest grave mound to current position. Falls back to churchyard.
            if GRAVE_MOUNDS:
                gx, gy = min(
                    GRAVE_MOUNDS,
                    key=lambda p: math.hypot(p[0] - self.x, p[1] - self.y),
                )
                return (gx, gy)
            ch = world.buildings.get("church")
            return (ch.x + 10, ch.y + 30) if ch else home
        if s == State.CARRYING_BOX:
            return RUINS_XY
        if s == State.CONVERSING:
            # v8 — converge on the partner so the conversation reads as
            # "these two are talking to each other" instead of two ghosts
            # staring across the village. Use the midpoint so both dots
            # drift together.
            partner_id = getattr(self, "conversation_partner", None)
            partner = world.agents.get(partner_id) if partner_id else None
            if partner is not None:
                mx = (self.x + partner.x) * 0.5
                my = (self.y + partner.y) * 0.5
                return (mx, my)
            return home
        if s == State.GOSSIPING:
            # Already returns the diner above — but if the diner is somehow
            # missing, prefer the bar (the secondary social hub) over home.
            bar = world.buildings.get("bar")
            if bar is not None:
                return (bar.x + rng.uniform(-10, 10), bar.y + rng.uniform(-10, 10))
            return home
        return home

    # Backwards-compat: keep the old name as a thin alias in case any
    # subsystem still calls ``_target_for`` directly.
    def _target_for(self, s: State, world: World) -> Optional[Tuple[float, float]]:
        return self._target_for_role_and_state(s, world)

    # ----------------------------------------------------------- v6 intent
    def _refresh_intent(self, world: World) -> None:
        """Recompute ``self.intent`` for the current state.

        Called from ``_enter``. Emits a sparse ``intent_change`` event only when
        the intent category transitions to one of a handful of major beats
        (heading to lighthouse / caves / Dungeon / mourning) — the per-tick
        roster row reads the string directly, so we don't need an event for
        every minor wander.
        """
        s = self.state
        target = self.target
        landmark = self._pick_landmark_name_in_world(target, world)

        if s == State.PATROLLING:
            text = f"{self.name} is patrolling toward {landmark}."
            cat = "patrolling"
        elif s == State.EXPLORING_CAVES:
            text = f"{self.name} is walking to the caves."
            cat = "caves"
        elif s == State.FORAGING:
            zone = getattr(self, "_forage_zone", None)
            place = "the windmill"
            if zone is not None:
                if zone[1] < 230:
                    place = "the western pond" if zone[0] < 300 else "the windmill"
                else:
                    place = "the lakeside river"
            text = f"{self.name} is foraging at {place}."
            cat = "foraging"
        elif s == State.CARRYING_BOX:
            text = f"{self.name} is carrying the music box to the Dungeon."
            cat = "music_box_carry"
        elif s == State.EXPEDITION:
            text = f"{self.name} is leading a party into the forest."
            cat = "expedition"
        elif s == State.EATING:
            text = f"{self.name} is heading {('to the diner' if landmark.lower() == 'diner' else 'home')} to eat."
            cat = "eating"
        elif s == State.MOURNING:
            text = f"{self.name} is mourning at {landmark}."
            cat = "mourning"
        elif s == State.PRAYING:
            text = f"{self.name} is praying at the church."
            cat = "praying"
        elif s == State.MEETING:
            text = f"{self.name} is at a meeting at Colony House."
            cat = "meeting"
        elif s == State.ARGUING:
            partner = getattr(self, "conversation_partner", None) or "someone"
            text = f"{self.name} is arguing with {partner}."
            cat = "arguing"
        elif s == State.FLEEING:
            text = f"{self.name} is fleeing in panic."
            cat = "fleeing"
        elif s == State.SHELTERING:
            home = world.buildings.get(self.dwelling_id)
            home_name = home.name if home is not None else "home"
            text = f"{self.name} is sheltering at {home_name}."
            cat = "sheltering"
        elif s == State.CALLED:
            text = f"{self.name} is being drawn to the lighthouse."
            cat = "called"
        elif s == State.SLEEPING:
            text = f"{self.name} is sleeping."
            cat = "sleeping"
        elif s == State.FARMING:
            text = f"{self.name} is tending the colony farm."
            cat = "farming"
        elif s == State.SCAVENGING:
            text = f"{self.name} is scavenging the forest edge."
            cat = "scavenging"
        elif s == State.INVESTIGATING:
            text = f"{self.name} is investigating {landmark}."
            cat = "investigating"
        elif s == State.WANDERING:
            text = f"{self.name} is wandering near {landmark}."
            cat = "wandering"
        elif s == State.CONVERSING:
            partner = getattr(self, "conversation_partner", None) or "someone"
            text = f"{self.name} is conversing with {partner}."
            cat = "conversing"
        elif s == State.IRRATIONAL:
            text = f"{self.name} is not themselves."
            cat = "irrational"
        elif s == State.CARETAKING:
            text = f"{self.name} is caring for the wounded."
            cat = "caretaking"
        elif s == State.MEDICAL_CARE:
            text = f"{self.name} is at the clinic."
            cat = "medical"
        elif s == State.REPAIRING:
            text = f"{self.name} is repairing {landmark}."
            cat = "repairing"
        elif s == State.GOSSIPING:
            text = f"{self.name} is gossiping at the diner."
            cat = "gossiping"
        elif s == State.PLAYING:
            text = f"{self.name} is playing near the pool."
            cat = "playing"
        elif s == State.MEDIATING:
            text = f"{self.name} is trying to keep the peace."
            cat = "mediating"
        else:
            text = f"{self.name} is here."
            cat = "idle"

        self.intent = text

        # Only emit an intent_change event for a small allowlist of "major"
        # category transitions — the dossier reads ``self.intent`` directly,
        # so we don't need one event per wander.
        major = {"called", "caves", "music_box_carry", "expedition",
                 "fleeing", "mourning"}
        if cat != self._last_intent_category and cat in major:
            try:
                world.emit(Event(
                    tick=world.tick_count,
                    type="intent_change",
                    subject=self.id,
                    detail=text,
                    severity="info",
                ))
            except Exception:
                pass
        self._last_intent_category = cat

    def _pick_landmark_name_in_world(
        self, xy: Optional[Tuple[float, float]], world: World,
    ) -> str:
        """Friendly name for an (x, y) — closest landmark, grave, or building.

        When the character is in MOURNING, grave mounds win even if they share
        a tile with the Choosing Stone — the player wants to read "at Abby's
        grave", not the geographic coincidence.
        """
        if xy is None:
            return "somewhere"
        if self.state == State.MOURNING:
            for gx, gy in GRAVE_MOUNDS:
                if math.hypot(xy[0] - gx, xy[1] - gy) < 25.0:
                    return "Abby's grave"
        # Match named landmarks within their natural jitter radius (15 px).
        for k, name in self._LANDMARK_NAMES.items():
            if math.hypot(xy[0] - k[0], xy[1] - k[1]) < 15.0:
                return name
        for gx, gy in GRAVE_MOUNDS:
            if math.hypot(xy[0] - gx, xy[1] - gy) < 25.0:
                return "Abby's grave"
        best: Optional[str] = None
        best_d = 60.0
        for b in world.buildings.values():
            d = math.hypot(xy[0] - b.x, xy[1] - b.y)
            if d < best_d:
                best_d = d
                best = b.name
        return best or "the woods"

    def _step_toward_target(self, world: World) -> None:
        if self.target is None:
            return
        # Walk speed depends on state.
        speed = 2.5
        if self.state == State.FLEEING:
            speed = 5.0
        elif self.state == State.PLAYING:
            speed = 3.5
        elif self.state in (State.SLEEPING, State.MEDIATING):
            # Genuinely stationary: only freeze once we've arrived. Until then
            # the character hurries to the right spot so the SVG shows them
            # where they're supposed to be.
            dx = self.target[0] - self.x
            dy = self.target[1] - self.y
            d = math.hypot(dx, dy)
            speed = 0.0 if d < 6.0 else 3.0
        elif self.state in (State.SHELTERING, State.PRAYING, State.MOURNING):
            # v8 — these used to be speed=0 which stranded the token wherever
            # the character was when the state flipped. Keep walking until we
            # arrive at the church / grave / dwelling, then snap still.
            dx = self.target[0] - self.x
            dy = self.target[1] - self.y
            d = math.hypot(dx, dy)
            speed = 0.0 if d < 6.0 else 3.5
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
            # v6 — current intent sentence (may be "" if the character hasn't
            # ticked through a state change yet). Surfaced in the roster row
            # and the click-dossier "Right now" line.
            "intent": self.intent,
            # v8 — frontend hides the dot when ``indoors`` is true so the
            # map shows only who is currently outside / exposed.
            "indoors": bool(getattr(self, "_indoors", False)),
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
