import os
import time
import random
import requests
import threading
import atexit
from collections import deque
from flask import Flask, jsonify, request
from telemetry import AITelemetry
from opentelemetry import trace, baggage
from opentelemetry.trace import SpanKind, Link
from opentelemetry.propagate import inject
from datetime import datetime, timedelta
from enum import Enum

app = Flask(__name__)

# Initialize telemetry
telemetry = AITelemetry()
logger = telemetry.get_logger()
tracer = telemetry.get_tracer()
atexit.register(telemetry.shutdown)

# ─── Constants ─────────────────────────────────────────────────────────────────

MAP_GRAPH = {
    "southern_capital": ["village_1", "village_3"],
    "northern_capital": ["village_2", "village_6"],
    "village_1": ["southern_capital", "village_2", "village_4"],
    "village_2": ["northern_capital", "village_1", "village_5"],
    "village_3": ["southern_capital", "village_5", "village_6"],
    "village_4": ["village_1", "village_5"],
    "village_5": ["village_2", "village_3", "village_4", "village_6"],
    "village_6": ["northern_capital", "village_3", "village_5"],
}

ARMY_COST = 30
VILLAGE_INCOME_PER_MIN = 40  # ~10 resources every 15s
RESOURCE_TRANSFER_THRESHOLD = 30

# Location configuration (matches game_config.py)
LOCATION_PORTS = {
    "southern_capital": 5001,
    "northern_capital": 5002,
    "village_1": 5003,
    "village_2": 5004,
    "village_3": 5005,
    "village_4": 5006,
    "village_5": 5007,
    "village_6": 5008
}

# ─── Game Phase ────────────────────────────────────────────────────────────────

class GamePhase(Enum):
    DESPERATE = "desperate"
    DEFENSIVE = "defensive"
    BALANCED = "balanced"
    DOMINATING = "dominating"
    READY_TO_ATTACK = "ready_to_attack"

# ─── Map Analyzer ──────────────────────────────────────────────────────────────

class MapAnalyzer:
    """Precomputed map analysis: BFS distances, strategic values, path army estimation."""

    def __init__(self):
        self.distances = self._compute_all_distances()
        self.strategic_values = self._compute_strategic_values()

    def _bfs_distances(self, start):
        """BFS from start node, returns dict {node: distance}."""
        visited = {start: 0}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbor in MAP_GRAPH[node]:
                if neighbor not in visited:
                    visited[neighbor] = visited[node] + 1
                    queue.append(neighbor)
        return visited

    def _compute_all_distances(self):
        """Precompute all-pairs BFS distances."""
        return {loc: self._bfs_distances(loc) for loc in MAP_GRAPH}

    def _compute_strategic_values(self):
        """Score each location by connectivity + centrality.
        Village 5 scores highest (4 connections, center of map)."""
        values = {}
        for loc in MAP_GRAPH:
            connections = len(MAP_GRAPH[loc])
            avg_capital_dist = (
                self.distances[loc].get("southern_capital", 99) +
                self.distances[loc].get("northern_capital", 99)
            ) / 2.0
            values[loc] = connections + (4.0 / max(avg_capital_dist, 1))
        return values

    def distance(self, a, b):
        return self.distances[a].get(b, 99)

    def neighbors(self, loc):
        return MAP_GRAPH.get(loc, [])

    def path_army_estimate(self, game_state, from_loc, to_loc, my_faction):
        """Estimate total enemy army along BFS shortest path from from_loc to to_loc."""
        parent = {from_loc: None}
        queue = deque([from_loc])
        while queue:
            node = queue.popleft()
            if node == to_loc:
                break
            for neighbor in MAP_GRAPH[node]:
                if neighbor not in parent:
                    parent[neighbor] = node
                    queue.append(neighbor)

        if to_loc not in parent:
            return 999  # unreachable

        # Walk path and sum enemy armies (excluding from_loc)
        path = []
        node = to_loc
        while node is not None:
            path.append(node)
            node = parent[node]
        path.reverse()

        enemy_army = 0
        for loc in path[1:]:  # skip from_loc
            loc_data = game_state.get(loc, {})
            if loc_data.get('faction') != my_faction:
                enemy_army += loc_data.get('army', 0)
        return enemy_army

# ─── Game Memory ───────────────────────────────────────────────────────────────

class GameMemory:
    """Tracks territory changes, failed attacks, and enemy push direction."""

    def __init__(self):
        self.territory_history = []  # list of (timestamp, my_territories set)
        self.failed_attacks = {}     # {target_loc: last_failure_time}
        self.enemy_push_direction = None
        self.last_enemy_territories = set()

    def update(self, game_state, my_faction):
        now = time.time()
        my_territories = set()
        enemy_territories = set()

        for loc_id, data in game_state.items():
            if data.get('faction') == my_faction:
                my_territories.add(loc_id)
            elif data.get('faction') not in (my_faction, 'neutral'):
                enemy_territories.add(loc_id)

        self.territory_history.append((now, my_territories.copy()))
        if len(self.territory_history) > 20:
            self.territory_history = self.territory_history[-20:]

        # Detect enemy push direction: new enemy territory closest to our capital
        new_enemy = enemy_territories - self.last_enemy_territories
        if new_enemy:
            self.enemy_push_direction = list(new_enemy)[0]
        self.last_enemy_territories = enemy_territories

        return my_territories, enemy_territories

    def record_failed_attack(self, target):
        self.failed_attacks[target] = time.time()

    def recently_failed(self, target, cooldown=60):
        last = self.failed_attacks.get(target)
        if last is None:
            return False
        return (time.time() - last) < cooldown

    def territory_lost_recently(self, seconds=30):
        """Check if we lost territory in the last N seconds."""
        if len(self.territory_history) < 2:
            return False
        now = time.time()
        current = self.territory_history[-1][1]
        for ts, territories in reversed(self.territory_history[:-1]):
            if now - ts > seconds:
                break
            if len(territories) > len(current):
                return True
        return False

# ─── Phase Detector ────────────────────────────────────────────────────────────

class PhaseDetector:
    """State-based phase detection using territory count and total army."""

    @staticmethod
    def detect(my_territories, enemy_territories, total_army):
        my_count = len(my_territories)
        enemy_count = len(enemy_territories)

        if total_army >= 8:
            return GamePhase.READY_TO_ATTACK
        if my_count <= 1:
            return GamePhase.DESPERATE
        elif my_count < enemy_count:
            return GamePhase.DEFENSIVE
        elif my_count > enemy_count + 1:
            return GamePhase.DOMINATING
        else:
            return GamePhase.BALANCED

# ─── Planner ───────────────────────────────────────────────────────────────────

class Planner:
    """Multi-step goal planning: sequences like [create_army x3, move_army(target)]."""

    def __init__(self):
        self.steps = []
        self.goal = None

    @property
    def active(self):
        return len(self.steps) > 0

    def set_plan(self, goal, steps):
        self.goal = goal
        self.steps = list(steps)

    def next_step(self):
        if self.steps:
            return self.steps[0]
        return None

    def advance(self):
        if self.steps:
            self.steps.pop(0)

    def abandon(self, reason=""):
        self.steps = []
        self.goal = None

    def validate(self, game_state, my_faction, my_capital):
        """Check if the current plan is still valid. Abandon if not."""
        if not self.active:
            return

        step = self.steps[0]
        action = step.get("action")

        if action == "create_army":
            cap_data = game_state.get(my_capital, {})
            if cap_data.get('faction') != my_faction:
                self.abandon("lost capital")
        elif action == "move_army":
            from_loc = step.get("from")
            loc_data = game_state.get(from_loc, {})
            if loc_data.get('faction') != my_faction or loc_data.get('army', 0) == 0:
                self.abandon("lost staging location or no army")
        elif action == "all_out_attack":
            cap_data = game_state.get(my_capital, {})
            if cap_data.get('faction') != my_faction or cap_data.get('army', 0) < 3:
                self.abandon("insufficient army for all-out attack")

# ─── Strategic AI ──────────────────────────────────────────────────────────────

class StrategicAI:
    """Main decision engine with priority cascade."""

    def __init__(self, faction):
        self.faction = faction
        self.my_capital = "southern_capital" if faction == "southern" else "northern_capital"
        self.enemy_capital = "northern_capital" if faction == "southern" else "southern_capital"
        self.map = MapAnalyzer()
        self.memory = GameMemory()
        self.planner = Planner()
        self.phase = GamePhase.BALANCED
        self.my_territories = set()
        self.enemy_territories = set()
        self.total_army = 0
        self._previous_phase = None
        self._previous_territories = set()
        self._last_evaluated = []

    def decide(self, game_state):
        """Run the priority cascade and return an action dict or None."""
        # Update memory and phase
        self.my_territories, self.enemy_territories = self.memory.update(game_state, self.faction)
        self.total_army = sum(
            data.get('army', 0) for loc, data in game_state.items()
            if data.get('faction') == self.faction
        )
        self.phase = PhaseDetector.detect(self.my_territories, self.enemy_territories, self.total_army)

        # Span events: phase transition
        span = trace.get_current_span()
        if self._previous_phase is not None and self.phase != self._previous_phase:
            span.add_event("phase_transition", attributes={
                "previous_phase": self._previous_phase.value,
                "new_phase": self.phase.value,
                "territory_count": len(self.my_territories),
                "total_army": self.total_army,
            })
        self._previous_phase = self.phase

        # Span events: territory change
        current_territory_set = set(self.my_territories)
        gained = current_territory_set - self._previous_territories
        lost = self._previous_territories - current_territory_set
        if gained or lost:
            span.add_event("territory_change", attributes={
                "territories_gained": str(list(gained)),
                "territories_lost": str(list(lost)),
                "current_count": len(current_territory_set),
            })
        self._previous_territories = current_territory_set

        # Validate active plan (track if it gets abandoned)
        had_plan = self.planner.active
        previous_goal = self.planner.goal
        self.planner.validate(game_state, self.faction, self.my_capital)
        if had_plan and not self.planner.active:
            span.add_event("plan_abandoned", attributes={
                "previous_goal": previous_goal or "unknown",
                "reason": "validation_failed",
            })
            telemetry.record_plan_abandoned("validation_failed")

        # Priority cascade with alternatives tracking
        evaluated = []

        action = self._check_capital_defense(game_state)
        if action:
            evaluated.append(f"capital_defense: TRIGGERED ({action.get('reason', '')})")
            self._last_evaluated = evaluated
            return action
        evaluated.append("capital_defense: skipped")

        action = self._find_zero_risk_captures(game_state)
        if action:
            evaluated.append(f"zero_risk_capture: TRIGGERED ({action.get('reason', '')})")
            self._last_evaluated = evaluated
            return action
        evaluated.append("zero_risk_capture: skipped")

        action = self._do_resource_transfers(game_state)
        if action:
            evaluated.append(f"resource_transfer: TRIGGERED ({action.get('reason', '')})")
            self._last_evaluated = evaluated
            return action
        evaluated.append("resource_transfer: skipped")

        action = self._execute_plan_step(game_state)
        if action:
            evaluated.append(f"execute_plan: TRIGGERED ({action.get('reason', '')})")
            self._last_evaluated = evaluated
            return action
        evaluated.append("execute_plan: skipped")

        action = self._create_new_plan(game_state)
        if action:
            evaluated.append(f"create_plan: TRIGGERED ({action.get('reason', '')})")
            self._last_evaluated = evaluated
            return action
        evaluated.append("create_plan: skipped")

        evaluated.append("fallback: TRIGGERED")
        self._last_evaluated = evaluated
        return self._fallback(game_state)

    # ── Priority 1: Capital Defense ────────────────────────────────────────────

    def _check_capital_defense(self, game_state):
        """If enemies adjacent to capital, create armies or reinforce."""
        cap_data = game_state.get(self.my_capital, {})
        if not cap_data or cap_data.get('faction') != self.faction:
            return None

        my_army = cap_data.get('army', 0)
        neighbors = self.map.neighbors(self.my_capital)
        max_threat = 0
        threat_loc = None

        for n in neighbors:
            n_data = game_state.get(n, {})
            if n_data.get('faction') not in (self.faction, 'neutral') and n_data.get('army', 0) > 0:
                if n_data['army'] > max_threat:
                    max_threat = n_data['army']
                    threat_loc = n

        if max_threat == 0:
            return None

        needed = max_threat + 2
        trace.get_current_span().add_event("threat_detected", attributes={
            "threat_location": threat_loc,
            "threat_army": max_threat,
            "capital_army": my_army,
            "armies_needed": needed,
        })
        if my_army < needed:
            if cap_data.get('resources', 0) >= ARMY_COST:
                armies_to_create = min(
                    needed - my_army,
                    cap_data['resources'] // ARMY_COST
                )
                return {
                    "action": "create_army",
                    "location": self.my_capital,
                    "count": max(1, armies_to_create),
                    "reason": f"capital_defense against {max_threat} at {threat_loc}"
                }
            return self._reinforce_capital(game_state)

        return None

    def _reinforce_capital(self, game_state):
        """Move friendly armies within 2 hops toward capital."""
        best_source = None
        best_army = 0
        for loc in MAP_GRAPH:
            if loc == self.my_capital:
                continue
            loc_data = game_state.get(loc, {})
            if loc_data.get('faction') == self.faction and loc_data.get('army', 0) > 0:
                dist = self.map.distance(loc, self.my_capital)
                if dist <= 2 and loc_data['army'] > best_army:
                    best_army = loc_data['army']
                    best_source = loc

        if best_source:
            target = self._step_toward(best_source, self.my_capital)
            if target:
                return {
                    "action": "move_army",
                    "from": best_source,
                    "to": target,
                    "reason": f"reinforce capital from {best_source}"
                }
        return None

    def _step_toward(self, from_loc, toward_loc):
        """Return the neighbor of from_loc that is closest to toward_loc."""
        best = None
        best_dist = 99
        for n in MAP_GRAPH[from_loc]:
            d = self.map.distance(n, toward_loc)
            if d < best_dist:
                best_dist = d
                best = n
        return best

    # ── Priority 2: Zero-Risk Captures ─────────────────────────────────────────

    def _find_zero_risk_captures(self, game_state):
        """Capture locations where our army > target army + 1, sorted by strategic value."""
        candidates = []
        for loc in MAP_GRAPH:
            loc_data = game_state.get(loc, {})
            if loc_data.get('faction') == self.faction:
                continue
            target_army = loc_data.get('army', 0)

            for neighbor in MAP_GRAPH[loc]:
                n_data = game_state.get(neighbor, {})
                if n_data.get('faction') == self.faction and n_data.get('army', 0) > target_army + 1:
                    # Don't attack from capital if it would leave it defenseless
                    if neighbor == self.my_capital:
                        cap_threatened = False
                        for cap_n in MAP_GRAPH[self.my_capital]:
                            cn_data = game_state.get(cap_n, {})
                            if cn_data.get('faction') not in (self.faction, 'neutral') and cn_data.get('army', 0) > 0:
                                cap_threatened = True
                                break
                        if cap_threatened:
                            continue

                    if self.memory.recently_failed(loc):
                        continue

                    candidates.append({
                        "target": loc,
                        "from": neighbor,
                        "our_army": n_data['army'],
                        "their_army": target_army,
                        "strategic_value": self.map.strategic_values.get(loc, 0),
                        "is_neutral": loc_data.get('faction') == 'neutral',
                    })

        if not candidates:
            return None

        candidates.sort(key=lambda c: (-c['is_neutral'], -c['strategic_value']))
        best = candidates[0]
        return {
            "action": "move_army",
            "from": best["from"],
            "to": best["target"],
            "reason": f"zero_risk_capture {best['target']} (our {best['our_army']} vs {best['their_army']})"
        }

    # ── Priority 3: Resource Transfers ─────────────────────────────────────────

    def _do_resource_transfers(self, game_state):
        """Transfer resources from ALL villages above threshold to capital, every cycle."""
        transfer_targets = []
        for loc in MAP_GRAPH:
            if loc == self.my_capital:
                continue
            loc_data = game_state.get(loc, {})
            if (loc_data.get('faction') == self.faction and
                'village' in loc and
                loc_data.get('resources', 0) > RESOURCE_TRANSFER_THRESHOLD):
                transfer_targets.append(loc)

        if not transfer_targets:
            return None

        return {
            "action": "resource_transfer",
            "locations": transfer_targets,
            "reason": f"transfer resources from {len(transfer_targets)} villages"
        }

    # ── Priority 4: Execute Active Plan Step ───────────────────────────────────

    def _execute_plan_step(self, game_state):
        """Execute next step of active plan."""
        if not self.planner.active:
            return None

        step = self.planner.next_step()
        if not step:
            return None

        action = step.get("action")

        if action == "create_army":
            cap_data = game_state.get(self.my_capital, {})
            if cap_data.get('resources', 0) >= ARMY_COST:
                self.planner.advance()
                return {
                    "action": "create_army",
                    "location": self.my_capital,
                    "count": 1,
                    "reason": f"plan step: {self.planner.goal}"
                }
            else:
                return {
                    "action": "collect_resources",
                    "location": self.my_capital,
                    "reason": "waiting for resources for plan"
                }

        elif action == "move_army":
            from_loc = step.get("from")
            to_loc = step.get("to")
            loc_data = game_state.get(from_loc, {})
            if loc_data.get('faction') == self.faction and loc_data.get('army', 0) > 0:
                self.planner.advance()
                return {
                    "action": "move_army",
                    "from": from_loc,
                    "to": to_loc,
                    "reason": f"plan step: {self.planner.goal}"
                }
            else:
                reason = "can't execute move step"
                self.planner.abandon(reason)
                trace.get_current_span().add_event("plan_abandoned", attributes={
                    "reason": reason,
                })
                telemetry.record_plan_abandoned(reason)
                return None

        elif action == "all_out_attack":
            self.planner.advance()
            return {
                "action": "all_out_attack",
                "location": self.my_capital,
                "reason": f"plan step: {self.planner.goal}"
            }

        self.planner.advance()
        return None

    # ── Priority 5: Create New Plan ────────────────────────────────────────────

    def _create_new_plan(self, game_state):
        """Create a new plan based on current phase."""
        # Sub-priority: if total army < 3, always build armies first
        if self.total_army < 3:
            armies_needed = 3 - self.total_army
            steps = [{"action": "create_army"} for _ in range(armies_needed)]
            goal = f"build {armies_needed} armies"
            self.planner.set_plan(goal, steps)
            trace.get_current_span().add_event("plan_created", attributes={
                "goal": goal, "step_count": len(steps),
            })
            telemetry.record_plan_created(goal)
            return self._execute_plan_step(game_state)

        # Sub-priority: capturable targets exist -> plan capture
        capture_plan = self._plan_capture(game_state)
        if capture_plan:
            return capture_plan

        # Sub-priority: READY_TO_ATTACK + feasible all-out
        if self.phase == GamePhase.READY_TO_ATTACK:
            attack_plan = self._plan_all_out_attack(game_state)
            if attack_plan:
                return attack_plan

        # Sub-priority: DESPERATE -> emergency build
        if self.phase == GamePhase.DESPERATE:
            cap_data = game_state.get(self.my_capital, {})
            if cap_data.get('resources', 0) >= ARMY_COST:
                goal = "emergency army build"
                steps = [{"action": "create_army"}]
                self.planner.set_plan(goal, steps)
                trace.get_current_span().add_event("plan_created", attributes={
                    "goal": goal, "step_count": len(steps),
                })
                telemetry.record_plan_created(goal)
                return self._execute_plan_step(game_state)

        # Sub-priority: concentrate isolated armies
        concentrate = self._concentrate_forces(game_state)
        if concentrate:
            return concentrate

        return None

    def _plan_capture(self, game_state):
        """Plan a capture: build N armies then move toward target."""
        targets = self._find_capturable_targets(game_state)
        if not targets:
            return None

        target = targets[0]
        target_loc = target["target"]
        target_army = game_state.get(target_loc, {}).get('army', 0)
        needed_army = target_army + 3

        steps = []

        # Build armies if needed
        armies_to_build = max(0, needed_army - self.total_army)
        for _ in range(min(armies_to_build, 5)):  # cap at 5 to avoid over-planning
            steps.append({"action": "create_army"})

        # Move one hop from capital toward target
        next_hop = self._step_toward(self.my_capital, target_loc)
        if next_hop:
            steps.append({"action": "move_army", "from": self.my_capital, "to": next_hop})

        if steps:
            goal = f"capture {target_loc}"
            self.planner.set_plan(goal, steps)
            trace.get_current_span().add_event("plan_created", attributes={
                "goal": goal, "step_count": len(steps),
            })
            telemetry.record_plan_created(goal)
            return self._execute_plan_step(game_state)

        return None

    def _find_capturable_targets(self, game_state):
        """Find targets we could capture, prioritizing low-defense neutrals for income."""
        targets = []
        for loc in MAP_GRAPH:
            loc_data = game_state.get(loc, {})
            if loc_data.get('faction') == self.faction:
                continue
            if self.memory.recently_failed(loc):
                continue

            target_army = loc_data.get('army', 0)
            is_neutral = loc_data.get('faction') == 'neutral'
            strat_value = self.map.strategic_values.get(loc, 0)

            # Find best staging location (closest of our territories)
            best_staging = None
            best_staging_dist = 99
            for our_loc in self.my_territories:
                dist = self.map.distance(our_loc, loc)
                if dist < best_staging_dist:
                    best_staging_dist = dist
                    best_staging = our_loc

            path_enemy = self.map.path_army_estimate(
                game_state, best_staging, loc, self.faction
            ) if best_staging else 999

            targets.append({
                "target": loc,
                "staging": best_staging,
                "target_army": target_army,
                "path_enemy": path_enemy,
                "is_neutral": is_neutral,
                "strategic_value": strat_value,
                "distance": best_staging_dist,
            })

        # Sort: neutrals first, then by lowest defense, then by strategic value
        targets.sort(key=lambda t: (
            not t['is_neutral'],
            t['target_army'],
            -t['strategic_value'],
        ))

        return targets

    def _plan_all_out_attack(self, game_state):
        """Plan an all-out attack if feasible (expected remaining army > 2)."""
        path_enemy = self.map.path_army_estimate(
            game_state, self.my_capital, self.enemy_capital, self.faction
        )
        expected_remaining = self.total_army - path_enemy
        if expected_remaining > 2:
            goal = "all-out attack on enemy capital"
            steps = [{"action": "all_out_attack"}]
            self.planner.set_plan(goal, steps)
            trace.get_current_span().add_event("plan_created", attributes={
                "goal": goal, "step_count": len(steps),
            })
            telemetry.record_plan_created(goal)
            return self._execute_plan_step(game_state)
        return None

    def _concentrate_forces(self, game_state):
        """Move isolated friendly armies toward threats or strategic hub (V5)."""
        target_loc = self.memory.enemy_push_direction or "village_5"

        for loc in MAP_GRAPH:
            if loc == self.my_capital:
                continue
            loc_data = game_state.get(loc, {})
            if loc_data.get('faction') == self.faction and loc_data.get('army', 0) > 0:
                # Check if this army is isolated (no enemy neighbors)
                has_enemy_neighbor = False
                for n in MAP_GRAPH[loc]:
                    n_data = game_state.get(n, {})
                    if n_data.get('faction') not in (self.faction, 'neutral'):
                        has_enemy_neighbor = True
                        break

                if not has_enemy_neighbor:
                    next_hop = self._step_toward(loc, target_loc)
                    if next_hop and next_hop != loc:
                        n_data = game_state.get(next_hop, {})
                        if n_data.get('faction') == self.faction or n_data.get('army', 0) < loc_data['army']:
                            return {
                                "action": "move_army",
                                "from": loc,
                                "to": next_hop,
                                "reason": f"concentrate forces from {loc} toward {target_loc}"
                            }
        return None

    # ── Priority 6: Fallback ───────────────────────────────────────────────────

    def _fallback(self, game_state):
        """Collect resources at capital."""
        return {
            "action": "collect_resources",
            "location": self.my_capital,
            "reason": "fallback: collect resources"
        }

    # ── Adaptive Timing ────────────────────────────────────────────────────────

    def get_pause_time(self):
        """Adaptive loop timing based on phase."""
        if self.phase == GamePhase.DESPERATE or self.memory.territory_lost_recently():
            return random.randint(2, 5)
        elif self.phase == GamePhase.READY_TO_ATTACK:
            return random.randint(3, 8)
        else:
            return random.randint(5, 15)

# ─── AI State ──────────────────────────────────────────────────────────────────

class AIState:
    def __init__(self):
        self.faction = None
        self.active = False
        self.last_action_time = None
        self.game_start_time = None
        self.strategic_ai = None
        self.decision_thread = None
        self.stop_flag = threading.Event()

ai_state = AIState()

# ─── Preserved Helpers ─────────────────────────────────────────────────────────

def get_location_url(location_id):
    """Get the URL for a location's API"""
    if os.environ.get('IN_DOCKER'):
        host = location_id.replace('_', '-')
    else:
        host = 'localhost'

    port = LOCATION_PORTS[location_id]
    return f"http://{host}:{port}"

def make_api_request(location_id, endpoint, method='GET', data=None):
    """Make an API request to a location server with trace context"""
    url = f"{get_location_url(location_id)}/{endpoint}"
    headers = {"Content-Type": "application/json"}

    with tracer.start_as_current_span(
        "ai_api_request",
        kind=SpanKind.CLIENT,
        attributes={
            "location.id": location_id,
            "location.endpoint": endpoint,
            "http.method": method
        }
    ) as span:
        inject(headers)  # Inject trace context

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            else:  # POST
                response = requests.post(url, json=data, headers=headers)

            span.set_attribute("http.status_code", response.status_code)
            response.raise_for_status()
            result = response.json()

            if not result.get("success", True):
                span.set_status(trace.StatusCode.ERROR, result.get("message", "Unknown error"))

            return result
        except requests.RequestException as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            logger.error("API request failed", extra={"error": str(e)})
            return {"error": str(e)}

def get_game_state(parent_ctx):
    """Get the current state of all locations"""
    with tracer.start_as_current_span(
        "get_game_state",
        kind=SpanKind.INTERNAL,
        context=parent_ctx,
        attributes={"location_count": len(LOCATION_PORTS)}
    ) as span:
        game_state = {}
        error_count = 0

        for location_id in LOCATION_PORTS.keys():
            data = make_api_request(location_id, '')
            if 'error' not in data:
                game_state[location_id] = data
            else:
                error_count += 1
                span.add_event(
                    "location_fetch_error",
                    attributes={
                        "location": location_id,
                        "error": str(data.get('error', 'Unknown error'))
                    }
                )

        span.set_attribute("locations_retrieved", len(game_state))
        span.set_attribute("errors", error_count)

        if error_count > 0:
            span.set_status(trace.StatusCode.ERROR, f"Failed to fetch {error_count} locations")

        return game_state

# ─── Action Executor ───────────────────────────────────────────────────────────

def execute_strategic_action(action, game_state, parent_ctx, decision_link=None):
    """Execute an action returned by StrategicAI.decide()."""
    if not action:
        return

    action_type = action.get("action")
    reason = action.get("reason", "")

    links = []
    if decision_link:
        links = [Link(decision_link, attributes={"link.type": "ai_decision_trigger"})]

    with tracer.start_as_current_span(
        "execute_ai_action",
        kind=SpanKind.INTERNAL,
        context=parent_ctx,
        links=links,
        attributes={
            "action_type": action_type,
            "reason": reason,
        }
    ) as span:
        try:
            if action_type == "create_army":
                location = action.get("location", ai_state.strategic_ai.my_capital)
                count = action.get("count", 1)
                armies_created = 0
                for i in range(count):
                    result = make_api_request(location, 'create_army', method='POST')
                    if result.get('success'):
                        armies_created += 1
                        logger.info("AI created army", extra={"army_number": armies_created, "total_requested": count, "reason": reason})
                    else:
                        logger.warning("Failed to create army", extra={"message": result.get('message', 'unknown')})
                        break
                    if i < count - 1:
                        time.sleep(0.5)
                span.set_attribute("armies_created", armies_created)
                span.set_attribute("armies_requested", count)

            elif action_type == "move_army":
                from_loc = action["from"]
                to_loc = action["to"]
                result = make_api_request(
                    from_loc,
                    'move_army',
                    method='POST',
                    data={"target_location": to_loc}
                )
                success = result.get('success', False)
                span.set_attribute("from_location", from_loc)
                span.set_attribute("target_location", to_loc)
                span.set_attribute("move_success", success)
                logger.info("AI move army", extra={"from_location": from_loc, "to_location": to_loc, "reason": reason, "success": success})
                if not success:
                    ai_state.strategic_ai.memory.record_failed_attack(to_loc)

            elif action_type == "all_out_attack":
                location = action.get("location", ai_state.strategic_ai.my_capital)
                result = make_api_request(location, 'all_out_attack', method='POST')
                span.set_attribute("all_out_attack", True)
                logger.info("AI all-out attack", extra={"location": location, "reason": reason})

            elif action_type == "collect_resources":
                location = action.get("location", ai_state.strategic_ai.my_capital)
                result = make_api_request(location, 'collect_resources', method='POST')
                logger.info("AI collected resources", extra={"location": location, "reason": reason})

            elif action_type == "resource_transfer":
                locations = action.get("locations", [])
                for loc in locations:
                    result = make_api_request(loc, 'send_resources_to_capital', method='POST')
                    logger.info("AI transferred resources", extra={"from_location": loc})
                span.set_attribute("transfers_count", len(locations))

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            logger.error("Error executing AI action", extra={"error": str(e), "action_type": action_type})

# ─── Decision Loop ─────────────────────────────────────────────────────────────

def ai_decision_loop():
    """Main AI decision loop that runs in a separate thread"""
    logger.info("AI decision loop started", extra={"faction": ai_state.faction})

    decision_count = 0

    while ai_state.active and not ai_state.stop_flag.is_set():
        decision_count += 1

        with tracer.start_as_current_span(
            "ai_decision_cycle",
            kind=SpanKind.INTERNAL,
            attributes={
                "faction": ai_state.faction,
                "game_phase": ai_state.strategic_ai.phase.value if ai_state.strategic_ai else "unknown",
                "cycle_number": decision_count,
                "cycle_start": datetime.now().isoformat(),
                "session_start": ai_state.game_start_time.isoformat() if ai_state.game_start_time else None
            }
        ) as cycle_span:
            parent_ctx = baggage.set_baggage("context", "parent")
            cycle_start_time = time.time()
            try:
                # Get current game state
                game_state = get_game_state(parent_ctx)
                my_capital = ai_state.strategic_ai.my_capital

                # Check if game is over
                if my_capital not in game_state or game_state[my_capital].get('faction') != ai_state.faction:
                    logger.info("AI detected game over", extra={"faction": ai_state.faction, "cycle_number": decision_count})
                    cycle_span.set_attribute("game_over_detected", True)
                    cycle_span.set_attribute("final_cycle", True)
                    ai_state.active = False
                    break

                # Make decision using StrategicAI
                decision_context = None
                with tracer.start_as_current_span(
                    "ai_decision",
                    kind=SpanKind.INTERNAL,
                    context=parent_ctx,
                    attributes={"game_phase": ai_state.strategic_ai.phase.value}
                ) as decision_span:
                    action = ai_state.strategic_ai.decide(game_state)
                    decision_context = decision_span.get_span_context()

                    if action:
                        decision_span.set_attribute("chosen_action", action.get("action", "none"))
                        decision_span.set_attribute("reason", action.get("reason", ""))

                    # Strategic context on spans
                    decision_span.set_attribute("my_territories", str(list(ai_state.strategic_ai.my_territories)))
                    decision_span.set_attribute("enemy_territories", str(list(ai_state.strategic_ai.enemy_territories)))
                    decision_span.set_attribute("total_army", ai_state.strategic_ai.total_army)
                    decision_span.set_attribute("game_phase", ai_state.strategic_ai.phase.value)
                    decision_span.set_attribute("priorities_evaluated", str(ai_state.strategic_ai._last_evaluated))

                if action:
                    action_type = action.get("action", "none")
                    telemetry.record_decision(action_type, ai_state.strategic_ai.phase.value)
                    execute_strategic_action(action, game_state, parent_ctx, decision_link=decision_context)
                    ai_state.last_action_time = datetime.now()
                    cycle_span.set_attribute("action_executed", True)
                    cycle_span.set_attribute("action_type", action_type)
                else:
                    cycle_span.set_attribute("no_action_taken", True)

                cycle_span.set_attribute("cycle_complete", True)

                # Session metrics
                if ai_state.game_start_time:
                    elapsed_time = (datetime.now() - ai_state.game_start_time).total_seconds()
                    cycle_span.set_attribute("session_elapsed_seconds", elapsed_time)

                # Record cycle duration
                telemetry.record_cycle_duration(time.time() - cycle_start_time)

                # Adaptive pause
                pause_time = ai_state.strategic_ai.get_pause_time()
                cycle_span.set_attribute("pause_duration_seconds", pause_time)
                logger.info("AI waiting", extra={"pause_seconds": pause_time, "phase": ai_state.strategic_ai.phase.value})

                if ai_state.stop_flag.wait(pause_time):
                    cycle_span.set_attribute("interrupted", True)
                    break

                if not ai_state.active:
                    cycle_span.set_attribute("ai_deactivated", True)
                    break

            except Exception as e:
                cycle_span.record_exception(e)
                cycle_span.set_status(trace.StatusCode.ERROR, str(e))
                logger.error("Error in AI decision cycle", extra={"error": str(e), "cycle_number": decision_count})
                time.sleep(5)

# ─── Flask Endpoints ───────────────────────────────────────────────────────────

@app.route('/activate', methods=['POST'])
def activate_ai():
    """Activate the AI for a specific faction"""
    data = request.get_json()
    faction = data.get('faction')

    if faction not in ['southern', 'northern']:
        return jsonify({"success": False, "message": "Invalid faction"}), 400

    if ai_state.active:
        return jsonify({"success": False, "message": "AI already active"}), 400

    ai_state.faction = faction
    ai_state.active = True
    ai_state.game_start_time = datetime.now()
    ai_state.stop_flag.clear()
    ai_state.strategic_ai = StrategicAI(faction)

    # Register state callback for observable gauges
    telemetry.set_state_callback(lambda: {
        "territory_count": len(ai_state.strategic_ai.my_territories),
        "total_army": ai_state.strategic_ai.total_army,
        "faction": ai_state.faction or "unknown",
    } if ai_state.strategic_ai else None)

    # Start AI decision thread
    ai_state.decision_thread = threading.Thread(target=ai_decision_loop, daemon=True)
    ai_state.decision_thread.start()

    logger.info("AI activated", extra={"faction": faction})
    return jsonify({"success": True, "message": f"AI activated for {faction} faction"})

@app.route('/deactivate', methods=['POST'])
def deactivate_ai():
    """Deactivate the AI"""
    if not ai_state.active:
        return jsonify({"success": False, "message": "AI not active"}), 400

    ai_state.active = False
    ai_state.stop_flag.set()

    # Wait for thread to stop (with timeout)
    if ai_state.decision_thread:
        ai_state.decision_thread.join(timeout=5)

    logger.info("AI deactivated", extra={"faction": ai_state.faction})
    return jsonify({"success": True, "message": "AI deactivated"})

@app.route('/status', methods=['GET'])
def ai_status():
    """Get current AI status"""
    return jsonify({
        "active": ai_state.active,
        "faction": ai_state.faction,
        "last_action": ai_state.last_action_time.isoformat() if ai_state.last_action_time else None,
        "game_phase": ai_state.strategic_ai.phase.value if ai_state.active and ai_state.strategic_ai else None
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8081))
    app.run(host='0.0.0.0', port=port, debug=False)
