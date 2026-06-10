"""Location server implementation.

Each of the 8 location containers has a constant ``SLOT_ID`` env var
(``slot_1`` … ``slot_8``). The in-game identity a slot serves (e.g.
``southern_capital`` in War of Kingdoms, ``wall_west`` in White Walkers
Attack) is resolved at boot and on ``/reload`` via the active map stored
in the shared ``game_config`` key-value table. See ``game_config.MAPS``.

The per-container SERVICE_NAME (used by Grafana dashboards) stays stable
regardless of map — it's derived from ``LOCATION_NAME`` env / slot id, not
from the logical location id.
"""
import os, sqlite3, requests, random, time, threading, atexit, uuid
from threading import Thread, Lock
from datetime import datetime, timedelta
from flask import Flask, g, jsonify, request
from game_config import (
    MAPS,
    COSTS,
    DATABASE_FILE,
    DEFAULT_MAP_ID,
    LOCATIONS,
    RESOURCE_GENERATION,
    SLOT_IDS,
    get_army_cost,
    get_army_currency,
    get_location_config,
    get_map,
    get_rules,
    resolve_slot,
)
from telemetry import GameTelemetry
from opentelemetry.propagate import extract, inject
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opentelemetry.context import get_current, attach, detach
from enum import Enum
from typing import Optional, List, Tuple, Dict

class PathType(Enum):
    RESOURCE = 'resource'
    ATTACK = 'attack'

class LocationServer:
    def __init__(self, slot_or_location=None):
        # Accept either a slot id (new, preferred) or a legacy location id
        # (for backward compat with local dev scripts). Falls back to env.
        raw = slot_or_location or os.environ.get('SLOT_ID')
        if raw in SLOT_IDS:
            self.slot_id = raw
        elif raw in MAPS[DEFAULT_MAP_ID]["locations"]:
            # Legacy: caller passed a War of Kingdoms location id; resolve to
            # its slot via the reverse map.
            inverse = {v: k for k, v in MAPS[DEFAULT_MAP_ID]["slot_assignments"].items()}
            self.slot_id = inverse[raw]
        else:
            raise ValueError(
                f"Cannot determine SLOT_ID from {raw!r}; expected one of {SLOT_IDS} "
                f"or a War of Kingdoms location id."
            )

        self.app = Flask(__name__)
        self.last_resource_collection = {}
        self.resource_cooldown = {}
        self.lock = Lock()
        # Idempotency cache for /receive_army: movement_id → (timestamp,
        # response). Deliveries are retried on transport errors, so the same
        # army could otherwise arrive (and fight) twice. Per-process and
        # time-pruned — fine for a demo; a real system would use a durable
        # idempotency store.
        self._processed_movements = {}
        # Passive background threads by name, surfaced via /health so a dead
        # economy loop is visible instead of silently starving the game.
        self._passive_threads = {}

        # SERVICE_NAME must stay stable across map switches so Grafana
        # dashboards keep their series. Prefer the explicit LOCATION_NAME env
        # (matches container name in docker-compose); else synthesise from the
        # slot id.
        service_name = os.environ.get('LOCATION_NAME') or self.slot_id.replace('_', '-')
        self.telemetry = GameTelemetry(service_name=service_name)
        self.logger = self.telemetry.get_logger()
        self.tracer = self.telemetry.get_tracer()

        # Give telemetry access to location state
        self.telemetry._get_location_state = self._get_location_state
        # And access to faction-scoped economy (for the corpse gauge).
        self.telemetry._get_corpse_count = self._get_corpses

        self.db_path = os.environ.get('DATABASE_FILE', DATABASE_FILE)

        # Populated by _load_identity().
        self.map_id = DEFAULT_MAP_ID
        self.location_id = None
        self.location_info = None
        self._passive_thread_started = False
        self._barbarian_thread_started = False
        self._corpse_thread_started = False
        self._nw_capital_thread_started = False

        self._initialize_database()
        self._load_identity()
        self.setup_routes()

        atexit.register(self.telemetry.shutdown)

    # ----------------------------------------------------------------
    # Map / slot identity resolution
    # ----------------------------------------------------------------

    def _current_locations(self) -> Dict:
        """Return the active map's ``location_id → config`` dict."""
        return MAPS[self.map_id]["locations"]

    def _current_rules(self) -> Dict:
        return MAPS[self.map_id]["rules"]

    def _read_active_map_id(self) -> str:
        conn = self._get_db_connection()
        try:
            row = conn.execute(
                "SELECT value FROM game_config WHERE key = 'active_map_id'"
            ).fetchone()
        finally:
            conn.close()
        return row['value'] if row else DEFAULT_MAP_ID

    def _load_identity(self):
        """Resolve slot → (map, location_id, config); seed this slot's row."""
        self.map_id = self._read_active_map_id()
        self.location_id = resolve_slot(self.map_id, self.slot_id)
        self.location_info = get_location_config(self.map_id, self.location_id)

        # Publish live identity to the telemetry instance so the observable
        # gauges report the currently-served id, not whatever id was derived
        # from the container's SERVICE_NAME at boot.
        self.telemetry._location_id = self.location_id
        self.telemetry._location_type = self.location_info["type"]

        # Seed this slot's row in the locations table if missing. Idempotent:
        # INSERT OR IGNORE handles the case where war_map already re-seeded.
        conn = self._get_db_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO locations (id, resources, army, faction) VALUES (?, ?, ?, ?)",
                (
                    self.location_id,
                    self.location_info["initial_resources"],
                    self.location_info["initial_army"],
                    self.location_info["faction"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self._start_passive_threads_if_needed()

        self.logger.info(
            f"Identity loaded: slot={self.slot_id} map={self.map_id} "
            f"location_id={self.location_id} type={self.location_info['type']} "
            f"faction={self.location_info['faction']}"
        )

    def _start_passive_threads_if_needed(self):
        """Kick off whichever passive loop matches this slot's identity.

        Threads are started at most once per process lifetime. If a slot's
        identity changes through ``/reload``, the *old* thread keeps running
        but becomes a no-op because it guards each iteration against the
        current location type/faction.
        """
        loc_type = self.location_info["type"]
        faction = self.location_info["faction"]
        rules = self._current_rules()

        # Launch the village resource thread for *every* village, including
        # barbarian-faction slots (Free Folk camps). The thread guards each
        # iteration on ``faction != "barbarian"``, so it stays a no-op while
        # the camp is still barbarian and starts producing for the player
        # the moment they capture it. Without this fallthrough, captured
        # camps stay unproductive because the thread was never started.
        if loc_type == "village" and not self._passive_thread_started:
            self._start_passive_generation()
            self._passive_thread_started = True

        if faction == "barbarian" and not self._barbarian_thread_started:
            interval = rules.get("barbarian_army_growth_interval_s", 0) or 0
            if interval > 0:
                self._start_barbarian_growth(interval)
                self._barbarian_thread_started = True

        if (
            loc_type == "capital"
            and faction == "white_walkers"
            and not self._corpse_thread_started
        ):
            interval = rules.get("white_walker_passive_corpse_interval_s", 0) or 0
            if interval > 0:
                self._start_white_walker_corpse_tick(interval)
                self._corpse_thread_started = True

        if (
            loc_type == "capital"
            and faction == "nights_watch"
            and not self._nw_capital_thread_started
        ):
            interval = rules.get("nights_watch_capital_passive_interval_s", 0) or 0
            amount = rules.get("nights_watch_capital_passive_amount", 0) or 0
            if interval > 0 and amount > 0:
                self._start_nights_watch_capital_resource_tick(interval, amount)
                self._nw_capital_thread_started = True

    # ----------------------------------------------------------------
    # Corpse economy (faction-scoped; lives in faction_economy table)
    # ----------------------------------------------------------------

    def _get_corpses(self, faction: str = "white_walkers") -> int:
        conn = self._get_db_connection()
        try:
            row = conn.execute(
                "SELECT corpses FROM faction_economy WHERE faction = ?", (faction,)
            ).fetchone()
        finally:
            conn.close()
        return int(row['corpses']) if row else 0

    def _add_corpses(self, delta: int, faction: str = "white_walkers"):
        if delta <= 0:
            return
        # Cap the pool: the passive tick runs forever, so an idle game must
        # not bank an unbounded corpse economy (see rules["max_corpses"]).
        cap = self._current_rules().get("max_corpses") or 10**9
        conn = self._get_db_connection()
        try:
            conn.execute(
                "INSERT INTO faction_economy (faction, corpses) VALUES (?, ?) "
                "ON CONFLICT(faction) DO UPDATE SET corpses = MIN(corpses + excluded.corpses, ?)",
                (faction, min(delta, cap), cap),
            )
            conn.commit()
        finally:
            conn.close()

    def _spend_corpses(self, amount: int, faction: str = "white_walkers") -> bool:
        """Atomically decrement ``faction``'s corpse pool. Returns True on success."""
        conn = self._get_db_connection()
        try:
            cursor = conn.execute(
                "UPDATE faction_economy SET corpses = corpses - ? "
                "WHERE faction = ? AND corpses >= ?",
                (amount, faction, amount),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def _find_capital(self, faction: str) -> Optional[str]:
        """Return the location_id of the capital with the given faction in the active map, by static config."""
        for loc_id, cfg in self._current_locations().items():
            if cfg["type"] == "capital" and cfg["faction"] == faction:
                return loc_id
        return None

    def _find_enemy_capital(self, faction: str) -> Optional[str]:
        """Return the location_id of a capital not belonging to ``faction`` (and not barbarian), by static config."""
        for loc_id, cfg in self._current_locations().items():
            if cfg["type"] == "capital" and cfg["faction"] not in (faction, "barbarian"):
                return loc_id
        return None

    def _get_db_connection(self):
        # ``timeout`` applies before the first PRAGMA runs, so concurrent
        # boot of all 8 containers doesn't race on ``PRAGMA journal_mode=WAL``
        # (which briefly acquires an exclusive lock to switch modes).
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_database(self):
        conn = self._get_db_connection()
        cursor = conn.cursor()

        # Canonical per-location state.
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY,
            resources INTEGER NOT NULL,
            army INTEGER NOT NULL,
            faction TEXT NOT NULL
        )
        ''')

        # Key/value game-wide config; holds active_map_id (authoritative at
        # runtime; overrides whatever the process started with).
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        ''')
        cursor.execute(
            "INSERT OR IGNORE INTO game_config (key, value) VALUES ('active_map_id', ?)",
            (DEFAULT_MAP_ID,),
        )

        # Faction-scoped economy (White Walkers' corpse pool today; room for
        # additional faction-level currencies later).
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS faction_economy (
            faction TEXT PRIMARY KEY,
            corpses INTEGER NOT NULL DEFAULT 0
        )
        ''')

        conn.commit()
        conn.close()

    def _get_location_state(self, location_id):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM locations WHERE id = ?", (location_id,))
        row = cursor.fetchone()
        
        state = None
        if row:
            state = {
                "resources": row['resources'],
                "army": row['army'],
                "faction": row['faction']
            }
        conn.close()
        return state

    def _update_location_state(self, location_id, resources=None, army=None, faction=None):
        # Central clamp: every write path (passive ticks, battles, refunds)
        # funnels through here, so the per-map economy caps are enforced in
        # exactly one place. See rules["max_resources"] / rules["max_army"].
        rules = self._current_rules()
        max_resources = rules.get("max_resources")
        max_army = rules.get("max_army")
        if resources is not None and max_resources:
            resources = min(resources, max_resources)
        if army is not None and max_army:
            army = min(army, max_army)

        set_clauses = []
        params = []

        if resources is not None:
            set_clauses.append("resources = ?")
            params.append(resources)
        if army is not None:
            set_clauses.append("army = ?")
            params.append(army)
        if faction is not None:
            set_clauses.append("faction = ?")
            params.append(faction)
        
        if not set_clauses:
            return False
        
        params.append(location_id)
        
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE locations SET {', '.join(set_clauses)} WHERE id = ?",
            params
        )
        conn.commit()
        conn.close()

        # Force metric collection on important state changes
        if faction is not None or resources is not None or army is not None:
            self.telemetry.collect_metrics()

        return True

    def _take_all_army(self, expected_army: int) -> bool:
        """Optimistic-concurrency debit of this location's whole army.

        Two near-simultaneous /move_army requests both read the same army
        count; the guarded UPDATE only matches for the first one, so the
        same troops can never march twice. Callers retry/409 on False.
        """
        conn = self._get_db_connection()
        try:
            cursor = conn.execute(
                "UPDATE locations SET army = 0 WHERE id = ? AND army = ?",
                (self.location_id, expected_army),
            )
            conn.commit()
            taken = cursor.rowcount > 0
        finally:
            conn.close()
        if taken:
            self.telemetry.collect_metrics()
        return taken

    def _credit_army(self, location_id: str, amount: int):
        """Additive army credit (refund/compensation path).

        Additive UPDATE — not a read-then-write — so it composes with any
        reinforcements that arrived while the refunded army was in flight.
        """
        cap = self._current_rules().get("max_army") or 10**9
        conn = self._get_db_connection()
        try:
            conn.execute(
                "UPDATE locations SET army = MIN(army + ?, ?) WHERE id = ?",
                (amount, cap, location_id),
            )
            conn.commit()
        finally:
            conn.close()
        self.telemetry.collect_metrics()

    def _debit_resources(self, location_id: str, amount: int) -> bool:
        """Guarded resource debit; False if the balance no longer covers it."""
        conn = self._get_db_connection()
        try:
            cursor = conn.execute(
                "UPDATE locations SET resources = resources - ? "
                "WHERE id = ? AND resources >= ?",
                (amount, location_id, amount),
            )
            conn.commit()
            debited = cursor.rowcount > 0
        finally:
            conn.close()
        if debited:
            self.telemetry.collect_metrics()
        return debited

    def _credit_resources(self, location_id: str, amount: int):
        """Additive resource credit (delivery or refund), capped per map rules."""
        cap = self._current_rules().get("max_resources") or 10**9
        conn = self._get_db_connection()
        try:
            conn.execute(
                "UPDATE locations SET resources = MIN(resources + ?, ?) WHERE id = ?",
                (amount, cap, location_id),
            )
            conn.commit()
        finally:
            conn.close()
        self.telemetry.collect_metrics()

    def _find_path(self, target: str, path_type: PathType) -> Optional[List[str]]:
        """Unified pathfinding for both resources and armies on the active map."""
        locations = self._current_locations()
        location_state = self._get_location_state(self.location_id)
        faction = location_state["faction"]

        # Resource routing only makes sense for factions that have a resource
        # economy. ``barbarian`` and ``white_walkers`` don't send resources.
        resource_factions = {"southern", "northern", "nights_watch"}
        if path_type == PathType.RESOURCE and faction not in resource_factions:
            return None

        distances = {loc: float('infinity') for loc in locations.keys()}
        distances[self.location_id] = 0
        previous = {loc: None for loc in locations.keys()}
        unvisited = set(locations.keys())

        def get_weight(loc_id: str) -> float:
            state = self._get_location_state(loc_id)
            loc_faction = state["faction"] if state else "neutral"

            if path_type == PathType.RESOURCE:
                if loc_faction == faction:
                    return 1
                elif loc_faction == "neutral":
                    return 2
                return float('infinity')
            else:  # PathType.ATTACK
                if loc_faction == faction:
                    return 1
                elif loc_faction == "neutral":
                    return 2
                return 3

        while unvisited:
            current = min(unvisited, key=lambda loc: distances[loc])
            if current == target:
                break

            unvisited.remove(current)
            for neighbor in locations[current]["connections"]:
                if neighbor in unvisited:
                    weight = get_weight(neighbor)
                    distance = distances[current] + weight

                    if distance < distances[neighbor]:
                        distances[neighbor] = distance
                        previous[neighbor] = current

        if previous[target] is None:
            return None

        path = []
        current = target
        while current is not None:
            path.append(current)
            current = previous[current]

        return list(reversed(path))

    def _handle_battle(self, attacking_army: int, attacking_faction: str,
                      defending_army: int, defending_faction: str,
                      location_type: Optional[str] = None) -> tuple[str, int, str]:
        """Handle battle between armies and return ``(result, remaining_army, new_faction)``.

        ``location_type`` lets the active map's rules modify the fight. For
        ``wall`` settlements on a map with ``wall_multiplier`` > 1 the defender's
        effective strength is scaled up — the physical garrison plays harder to
        dislodge, but the ``remaining_army`` reported back is converted back to
        physical units so DB rows stay honest.
        """
        # Same faction = reinforcement. Multiplier never applies.
        if attacking_faction == defending_faction:
            self.logger.info(f"Reinforcement battle between {attacking_faction} armies")
            self.telemetry.record_battle(attacking_faction, defending_faction, "reinforcement")
            return "reinforcement", attacking_army + defending_army, attacking_faction

        multiplier = 1.0
        if location_type == "wall":
            multiplier = float(self._current_rules().get("wall_multiplier", 1.0) or 1.0)
        effective_defender = int(defending_army * multiplier)

        if attacking_army > effective_defender:
            remaining = attacking_army - effective_defender
            self.logger.info(
                f"Attacker victory: {attacking_army} vs {defending_army} "
                f"(effective {effective_defender}, mult {multiplier}) -> {remaining}"
            )
            self.telemetry.record_battle(attacking_faction, defending_faction, "attacker_victory")
            return "attacker_victory", remaining, attacking_faction
        elif effective_defender > attacking_army:
            # Convert defender's surviving *effective* strength back to physical.
            effective_remaining = effective_defender - attacking_army
            remaining = max(1, int(effective_remaining / multiplier)) if multiplier > 0 else effective_remaining
            self.logger.info(
                f"Defender victory: {defending_army} vs {attacking_army} "
                f"(effective {effective_defender}, mult {multiplier}) -> {remaining}"
            )
            self.telemetry.record_battle(attacking_faction, defending_faction, "defender_victory")
            return "defender_victory", remaining, defending_faction
        else:
            self.logger.info(
                f"Stalemate: {attacking_army} vs {defending_army} "
                f"(effective {effective_defender}, mult {multiplier})"
            )
            self.telemetry.record_battle(attacking_faction, defending_faction, "stalemate")
            return "stalemate", 0, defending_faction

    def _continue_army_movement(self, army_size: int, faction: str, current_loc: str,
                              next_loc: str, remaining_path: List[str], is_attack_move: bool = False,
                              movement_id: Optional[str] = None) -> Dict:
        """Continue army movement to next location.

        The caller has already debited the source (debit-at-send), so while
        the thread sleeps the army exists only "in flight". If delivery
        fails at the transport level the army marches home (compensation);
        a *lost battle* is a game outcome, not a delivery failure — those
        troops are dead, not refunded.
        """
        # Capture the full context before spawning the thread
        ctx = get_current()

        def move():
            token = attach(ctx)
            refunded = False
            try:
                time.sleep(5)  # Wait 5 seconds before moving

                with self.tracer.start_as_current_span(
                        "army_movement",
                        kind=SpanKind.SERVER,
                        attributes={
                            "source_location": current_loc,
                            "target_location": next_loc,
                            "army_size": army_size,
                            "is_attack_move": is_attack_move,
                            "game.movement.id": movement_id or "",
                        }
                    ) as movement_span:
                        target_url = f"{self.get_location_url(next_loc)}/receive_army"
                        self.logger.info(f"Moving army from {current_loc} to {next_loc}")

                        try:
                            result = self._make_request_with_trace(
                                'post',
                                target_url,
                                {
                                    "army_size": army_size,
                                    "faction": faction,
                                    "source_location": current_loc,
                                    "remaining_path": remaining_path,
                                    "is_attack_move": is_attack_move,
                                    "movement_id": movement_id,
                                },
                                span_name="http_request.move_army"
                            )
                        except requests.RequestException as e:
                            # Transport failure (or downstream rejection) —
                            # the army never fought anywhere. March it home.
                            self._credit_army(current_loc, army_size)
                            refunded = True
                            movement_span.record_exception(e)
                            movement_span.add_event("army_returned", {
                                "army_size": army_size,
                                "returned_to": current_loc,
                                "reason": "delivery_failed",
                            })
                            movement_span.set_status(
                                trace.StatusCode.ERROR,
                                f"Delivery to {next_loc} failed; army returned to {current_loc}",
                            )
                            self.logger.error(
                                f"Army delivery to {next_loc} failed ({e}); "
                                f"{army_size} units returned to {current_loc}"
                            )
                            return

                        if not result.get("success", False):
                            # A lost battle is a game outcome, not a transport
                            # failure — those troops are dead, not refunded.
                            movement_span.set_status(trace.StatusCode.ERROR, "Army movement failed")
                            movement_span.set_attribute("error", result.get("message", "Unknown error"))
                            self.logger.error(f"Army movement failed: {result.get('message', 'Unknown error')}")
                        else:
                            # Force metric collection after successful army movement
                            self.telemetry.collect_metrics()

            except Exception as e:
                # Never let an unexpected error evaporate the army silently.
                if not refunded:
                    self._credit_army(current_loc, army_size)
                self.logger.error(f"Failed to move army to {next_loc}: {str(e)}; army returned")
            finally:
                detach(token)

        # Start movement in background thread
        Thread(target=move).start()

        # Force metric collection at the start of movement
        self.telemetry.collect_metrics()

        # Return immediate response indicating movement has started
        return {
            "success": True,
            "message": f"Army movement started from {current_loc} to {next_loc}",
            "is_attack_move": is_attack_move
        }

    def _forward_resources(self, amount: int, faction: str, next_loc: str,
                           payload_path: List[str]) -> None:
        """Deliver ``amount`` resources to ``next_loc`` after the 5 s march delay.

        Debit-at-send: the caller has already debited this location's row,
        so while the thread sleeps the resources exist only "in flight".
        Compensation rules:

        - transport failure / downstream rejection → refund here
          (``resources_returned`` span event);
        - caravan captured by another faction → the new owner keeps it,
          no refund (a game outcome, not a delivery failure).

        ``faction`` is captured at call time, *not* re-read after the delay —
        if this location changes hands mid-flight the caravan still belongs
        to whoever dispatched it.
        """
        # Capture the full context before spawning the thread
        ctx = get_current()

        def transfer():
            token = attach(ctx)
            refunded = False
            try:
                time.sleep(5)  # Wait before starting transfer

                with self.tracer.start_as_current_span(
                    "resource_movement",
                    kind=SpanKind.SERVER,
                    attributes={
                        "source_location": self.location_id,
                        "target_location": next_loc,
                        "resources_amount": amount,
                        "faction": faction,
                        "resource.movement": True,
                    }
                ) as movement_span:
                    target_url = f"{self.get_location_url(next_loc)}/receive_resources"
                    try:
                        result = self._make_request_with_trace(
                            'post',
                            target_url,
                            {
                                "resources": amount,
                                "source_location": self.location_id,
                                "remaining_path": payload_path,
                                "faction": faction,
                            },
                            span_name="http_request.transfer_resources"
                        )
                    except requests.RequestException as e:
                        self._credit_resources(self.location_id, amount)
                        refunded = True
                        movement_span.record_exception(e)
                        movement_span.add_event("resources_returned", {
                            "resources_amount": amount,
                            "reason": "delivery_failed",
                        })
                        movement_span.set_status(
                            trace.StatusCode.ERROR,
                            f"Delivery to {next_loc} failed; resources returned",
                        )
                        self.logger.error(
                            f"Resource delivery to {next_loc} failed ({e}); "
                            f"{amount} returned to {self.location_id}"
                        )
                        return

                    if result.get("captured"):
                        movement_span.set_status(
                            trace.StatusCode.ERROR,
                            f"Resources captured at {next_loc}",
                        )
                    elif not result.get("success", False):
                        self._credit_resources(self.location_id, amount)
                        refunded = True
                        movement_span.add_event("resources_returned", {
                            "resources_amount": amount,
                            "reason": result.get("message", "rejected"),
                        })
                        movement_span.set_status(trace.StatusCode.ERROR, "Resource transfer rejected")
                    else:
                        # Force metric collection after successful resource transfer
                        self.telemetry.collect_metrics()

            except Exception as e:
                if not refunded:
                    self._credit_resources(self.location_id, amount)
                self.logger.error(
                    f"Failed to send resources to {next_loc} from {self.location_id}: {str(e)}"
                )
            finally:
                detach(token)

        Thread(target=transfer).start()

    # (connect, read) timeouts for every outbound call: a hung peer must
    # never block a Flask worker thread indefinitely.
    REQUEST_TIMEOUT = (3, 10)

    def _make_request_with_trace(self, method: str, url: str, json_data: Optional[Dict] = None, span_name: str = "http_request") -> Dict:
        """Make HTTP request with trace context propagated in headers.

        Attribute names follow the OpenTelemetry HTTP semantic conventions
        (``url.full``, ``http.request.method``, ``http.response.status_code``)
        so tooling that understands the conventions — Tempo's service-graph
        details, Grafana drilldowns — works without custom mapping.

        Transport errors get exactly one retry after a 2 s backoff. Paired
        with the idempotent ``/receive_army`` (movement_id dedupe), a retry
        can never deliver the same army twice.
        """
        headers = {"Content-Type": "application/json"}

        with self.tracer.start_as_current_span(
            span_name,
            kind=SpanKind.CLIENT,
            attributes={
                "url.full": url,
                "http.request.method": method.upper(),
            }
        ) as request_span:
            inject(headers)  # This will now inject the current request_span's context

            last_exc = None
            for attempt in (1, 2):
                try:
                    if method.lower() == 'get':
                        response = requests.get(url, headers=headers, timeout=self.REQUEST_TIMEOUT)
                    elif method.lower() == 'post':
                        response = requests.post(url, json=json_data, headers=headers, timeout=self.REQUEST_TIMEOUT)
                    else:
                        raise ValueError(f"Unsupported method: {method}")

                    request_span.set_attribute("http.response.status_code", response.status_code)
                    response.raise_for_status()
                    return response.json()
                except (requests.ConnectionError, requests.Timeout) as e:
                    last_exc = e
                    if attempt == 1:
                        request_span.add_event("retry_attempted", {"error": str(e)})
                        self.logger.warning(f"Request to {url} failed ({e}); retrying once")
                        time.sleep(2)
                except requests.RequestException as e:
                    # HTTP-level errors (4xx/5xx): the peer answered, so a
                    # retry would not change the outcome. Fail fast.
                    request_span.record_exception(e)
                    request_span.set_status(trace.StatusCode.ERROR, str(e))
                    self.logger.error(f"Request failed: {str(e)}")
                    raise

            request_span.record_exception(last_exc)
            request_span.set_status(trace.StatusCode.ERROR, str(last_exc))
            self.logger.error(f"Request failed after retry: {str(last_exc)}")
            raise last_exc

    def _can_collect_resources(self) -> tuple[bool, Optional[str], Optional[int]]:
        """Check if location can collect resources.
        Returns:
            tuple: (can_collect, message, cooldown_seconds)
        """
        with self.lock:
            if self.location_info["type"] != "capital":
                return False, "Only capitals can manually collect resources", None
            
            now = datetime.now()
            
            # Check resource sending cooldown
            if self.location_id in self.resource_cooldown:
                cooldown_end = self.resource_cooldown[self.location_id]
                if now < cooldown_end:
                    remaining = (cooldown_end - now).seconds
                    return False, f"Resource generation on cooldown for {remaining} seconds", remaining
            
            # Check collection cooldown
            last_time = self.last_resource_collection.get(self.location_id, datetime.min)
            wait_time = timedelta(seconds=5)
            
            if now - last_time < wait_time:
                remaining = wait_time - (now - last_time)
                return False, f"Must wait {remaining.seconds} seconds to collect resources", remaining.seconds
            
            return True, None, None

    def _start_resource_cooldown(self):
        with self.lock:
            self.resource_cooldown[self.location_id] = datetime.now() + timedelta(seconds=5)

    # Sanity ceiling for any single army/resource delivery. Generous on
    # purpose (well above what honest play can produce) — it exists to stop
    # a stray, duplicated, or hand-crafted request from minting absurd
    # amounts, not to enforce game balance (the per-map caps do that).
    MAX_TRANSFER = 10_000

    def _validate_inbound_payload(self, data, amount_key: str) -> Optional[str]:
        """Validate a /receive_army or /receive_resources payload.

        Only sibling location services call these routes, but a replayed,
        duplicated, or buggy request must never inject units out of thin
        air. Returns an error message, or None if the payload is sound.
        """
        if not isinstance(data, dict):
            return "Invalid payload"

        amount = data.get(amount_key)
        # bool is an int subclass in Python — reject it explicitly.
        if not isinstance(amount, int) or isinstance(amount, bool):
            return f"Invalid {amount_key}: must be an integer"
        if amount <= 0 or amount > self.MAX_TRANSFER:
            return f"Invalid {amount_key}: {amount} out of range"

        faction = data.get('faction')
        valid_factions = set(MAPS[self.map_id]["factions"]) | {"neutral"}
        if faction not in valid_factions:
            return f"Unknown faction: {faction!r}"

        # Armies and caravans only ever arrive from adjacent locations.
        source = data.get('source_location')
        if source not in self.location_info["connections"]:
            return f"{source!r} is not adjacent to {self.location_id}"

        return None

    def _check_duplicate_movement(self, movement_id: Optional[str]) -> Optional[Dict]:
        """Return the cached response if this movement was already delivered.

        Pairs with the transport retry in ``_make_request_with_trace``: if
        the first delivery succeeded but its response was lost, the retry
        re-sends the same ``movement_id`` and gets the cached result back
        instead of fighting the battle twice.
        """
        if not movement_id:
            return None
        now = time.time()
        with self.lock:
            self._processed_movements = {
                k: v for k, v in self._processed_movements.items()
                if now - v[0] < 120
            }
            entry = self._processed_movements.get(movement_id)
            return dict(entry[1]) if entry else None

    def _record_movement_result(self, movement_id: Optional[str], response: Dict):
        if not movement_id:
            return
        with self.lock:
            self._processed_movements[movement_id] = (time.time(), dict(response))

    def get_location_url(self, location_id):
        """Return the HTTP base URL for reaching another location service.

        Uses the active map's port assignment; falls back to WoK's port for a
        legacy id if the location isn't on the current map (shouldn't happen
        during a coherent game but guards against transition races).
        """
        locations = self._current_locations()
        if location_id in locations:
            port = locations[location_id]["port"]
        else:
            port = MAPS[DEFAULT_MAP_ID]["locations"][location_id]["port"]
        if os.environ.get('IN_DOCKER') or os.environ.get('LOCATION_ID'):
            docker_service_name = self._container_for(location_id)
            return f"http://{docker_service_name}:{port}"
        return f"http://localhost:{port}"

    def _container_for(self, location_id: str) -> str:
        """Return the stable container hostname for another location id.

        Containers are named after their *slot* (slot_1 → southern-capital in
        docker-compose, which is slot_1's stable identity). We reverse-look up
        the slot that currently serves ``location_id`` on the active map, then
        translate that slot back to its container hostname using the WoK
        default slot assignments (which match docker-compose service names).
        """
        active = MAPS[self.map_id]["slot_assignments"]
        wok = MAPS[DEFAULT_MAP_ID]["slot_assignments"]
        for slot, active_loc in active.items():
            if active_loc == location_id:
                return wok[slot].replace('_', '-')
        # Unknown id — best-effort: use the hyphenated form.
        return location_id.replace('_', '-')

    def _start_passive_generation(self):
        def generate_resources():
            # The loop body is guarded so a transient failure (e.g. a SQLite
            # busy timeout) can't kill the thread — a dead economy loop would
            # silently starve this location for the rest of the game.
            while True:
                try:
                    time.sleep(15)
                    # Static identity guards against /reload moving this slot off
                    # of a village type entirely.
                    if self.location_info["type"] != "village":
                        continue
                    # Live-DB guard: gate on the *current* faction, not the
                    # boot-time identity, so a captured Free Folk camp starts
                    # producing for the new owner the moment its row flips. The
                    # static ``self.location_info["faction"]`` is set at boot
                    # from MAPS config and never updates on battle.
                    location_state = self._get_location_state(self.location_id)
                    if location_state is None:
                        continue
                    if location_state["faction"] == "barbarian":
                        continue
                    amount = self._current_rules()["resource_generation"]["village"]
                    with self.tracer.start_as_current_span(
                        "passive_resource_generation",
                        attributes={
                            "location.id": self.location_id,
                            "resources_gained": amount,
                            "game.map.id": self.map_id,
                            "owner.faction": location_state["faction"],
                        }
                    ):
                        new_resources = location_state["resources"] + amount
                        self._update_location_state(self.location_id, resources=new_resources)
                        self.telemetry.collect_metrics()
                except Exception as e:
                    self.logger.error(f"Passive generation tick failed: {e}")

        thread = Thread(target=generate_resources, daemon=True, name="passive_generation")
        thread.start()
        self._passive_threads["passive_generation"] = thread

    def _start_barbarian_growth(self, interval_s: int):
        """Barbarian villages grow +1 army every ``interval_s`` seconds.

        Barbarians never initiate combat; they exist to pressure the map and
        feed the White Walker corpse economy. The thread self-gates against
        identity changes so it becomes a no-op if /reload moves this slot off
        a barbarian role.
        """
        def grow():
            while True:
                try:
                    time.sleep(interval_s)
                    if self.location_info["faction"] != "barbarian":
                        continue
                    with self.tracer.start_as_current_span(
                        "barbarian_passive_growth",
                        attributes={
                            "location.id": self.location_id,
                            "game.map.id": self.map_id,
                            "army_gained": 1,
                        }
                    ):
                        state = self._get_location_state(self.location_id)
                        if state is None:
                            continue
                        # Only grow while still barbarian-controlled.
                        if state["faction"] != "barbarian":
                            continue
                        self._update_location_state(self.location_id, army=state["army"] + 1)
                        self.telemetry.collect_metrics()
                except Exception as e:
                    self.logger.error(f"Barbarian growth tick failed: {e}")

        thread = Thread(target=grow, daemon=True, name="barbarian_growth")
        thread.start()
        self._passive_threads["barbarian_growth"] = thread

    def _start_nights_watch_capital_resource_tick(self, interval_s: int, amount: int):
        """Passive resource generation at the Night's Watch capital (WWA only).

        WWA gives the player no friendly villages, so /collect_resources at
        Castle Black is the only income source — leading to click-spam UX. A
        slow passive tick supplements that without removing the incentive to
        actively collect (manual is +20 per 5 s; passive is +amount per
        interval_s, configured well below that).
        """
        def tick():
            while True:
                try:
                    time.sleep(interval_s)
                    if (self.location_info["faction"] != "nights_watch"
                        or self.location_info["type"] != "capital"):
                        continue
                    with self.tracer.start_as_current_span(
                        "nights_watch_passive_resource",
                        attributes={
                            "location.id": self.location_id,
                            "game.map.id": self.map_id,
                            "resources_gained": amount,
                        }
                    ):
                        state = self._get_location_state(self.location_id)
                        if state is None:
                            continue
                        if state["faction"] != "nights_watch":
                            continue
                        self._update_location_state(
                            self.location_id, resources=state["resources"] + amount
                        )
                        self.telemetry.collect_metrics()
                except Exception as e:
                    self.logger.error(f"Night's Watch resource tick failed: {e}")

        thread = Thread(target=tick, daemon=True, name="nights_watch_resource_tick")
        thread.start()
        self._passive_threads["nights_watch_resource_tick"] = thread

    def _start_white_walker_corpse_tick(self, interval_s: int):
        """Passive corpse generation at the White Walker fortress.

        Simulates the undead slowly rising — keeps the WW economy nonzero even
        when no battles are happening. Corpses accrue to the faction pool.
        """
        def tick():
            # Guarded loop: if this thread died, the White Walker AI could
            # never afford an army when no battles are happening.
            while True:
                try:
                    time.sleep(interval_s)
                    if self.location_info["faction"] != "white_walkers" or self.location_info["type"] != "capital":
                        continue
                    with self.tracer.start_as_current_span(
                        "white_walker_corpse_tick",
                        attributes={
                            "location.id": self.location_id,
                            "game.map.id": self.map_id,
                            "game.corpses.harvested": 1,
                            "corpse.source": "passive",
                        }
                    ):
                        self._add_corpses(1, "white_walkers")
                        self.telemetry.collect_metrics()
                except Exception as e:
                    self.logger.error(f"Corpse tick failed: {e}")

        thread = Thread(target=tick, daemon=True, name="white_walker_corpse_tick")
        thread.start()
        self._passive_threads["white_walker_corpse_tick"] = thread

    def reset_database(self):
        """Reset every location row + the corpse pool to the active map's initial state."""
        # Re-read the active map *first*: war_map writes the new
        # active_map_id before calling /reset, so resetting with this
        # process's in-memory map id would repopulate the table with the
        # previous map's rows.
        self._load_identity()

        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM locations")

        for loc_id, loc_info in self._current_locations().items():
            cursor.execute(
                "INSERT INTO locations VALUES (?, ?, ?, ?)",
                (
                    loc_id,
                    loc_info["initial_resources"],
                    loc_info["initial_army"],
                    loc_info["faction"],
                ),
            )

        cursor.execute("DELETE FROM faction_economy")

        # Seed corpse pools for corpse-currency factions so the AI's
        # /faction_economy reads and the corpse gauge have a row from t=0
        # instead of depending on the passive tick having fired first.
        for faction in MAPS[self.map_id]["factions"]:
            if get_army_currency(self.map_id, faction) == "corpses":
                cursor.execute(
                    "INSERT OR IGNORE INTO faction_economy (faction, corpses) VALUES (?, 0)",
                    (faction,),
                )

        conn.commit()
        conn.close()
        self.logger.info(f"Database reset to initial state for map {self.map_id}")

    def setup_routes(self):
        @self.app.before_request
        def _attach_incoming_context():
            # Attach the extracted W3C context (trace + baggage) as the
            # *current* context for the whole request. Handlers still pass
            # context=extract(...) explicitly when starting their span, but
            # that alone does not make the context current — and outbound
            # inject() calls plus get_current() captures in background
            # threads read the *current* context. Without this attach,
            # baggage (game.session.id, game.actor, …) would stop at this
            # service's handler span instead of flowing down the cascade.
            g._otel_ctx_token = attach(extract(request.headers))

        @self.app.teardown_request
        def _detach_incoming_context(exc):
            token = getattr(g, "_otel_ctx_token", None)
            if token is not None:
                detach(token)

        @self.app.route('/', methods=['GET'])
        def info():
            context = extract(request.headers)
            with self.tracer.start_as_current_span(
                "get_location_info",
                context=context,
                kind=SpanKind.SERVER,
                attributes={
                    "location.id": self.location_id,
                    "location.name": self.location_info["name"],
                    "location.type": self.location_info["type"]
                }
            ):
                location_state = self._get_location_state(self.location_id)

                cooldown_info = None
                with self.lock:
                    now = datetime.now()
                    last_time = self.last_resource_collection.get(self.location_id, datetime.min)
                    wait_time = timedelta(seconds=15 if self.location_info["type"] == "village" else 5)

                    if now - last_time < wait_time:
                        remaining = wait_time - (now - last_time)
                        cooldown_info = remaining.seconds

                return jsonify({
                    "location_id": self.location_id,
                    "name": self.location_info["name"],
                    "faction": location_state["faction"],
                    "connections": self.location_info["connections"],
                    "resources": location_state["resources"],
                    "army": location_state["army"],
                    "resource_cooldown": cooldown_info
                })

        @self.app.route('/health', methods=['GET'])
        def health():
            # Surface passive-thread liveness: the game can look healthy while
            # an economy loop is dead, so make that observable here (and in
            # `docker compose ps` once a healthcheck inspects the payload).
            threads = {name: t.is_alive() for name, t in self._passive_threads.items()}
            return jsonify({
                "status": "ok" if all(threads.values()) else "degraded",
                "threads": threads,
            })

        @self.app.route('/collect_resources', methods=['POST'])
        def collect_resources():
            """Collect resources from a location"""
            # Extract trace context from request headers
            context = extract(request.headers)
            
            with self.tracer.start_as_current_span(
                "collect_resources",
                context=context,
                kind=SpanKind.SERVER,
                attributes={
                    "location_name": self.location_info["name"],
                    "location_type": self.location_info["type"]
                }
            ) as span:
                can_collect, message, cooldown_seconds = self._can_collect_resources()
                if not can_collect:
                    span.set_status(trace.StatusCode.ERROR, message)
                    span.set_attribute("cooldown_seconds", cooldown_seconds or 0)
                    return jsonify({
                        "success": False,
                        "message": message,
                        "cooldown": True,
                        "cooldown_seconds": cooldown_seconds
                    }), 200  # Return 200 for cooldown, as it's an expected state
                
                location_type = self.location_info["type"]
                resources_gained = self._current_rules()["resource_generation"].get(location_type, 0)

                location_state = self._get_location_state(self.location_id)
                new_resources = location_state["resources"] + resources_gained
                self._update_location_state(self.location_id, resources=new_resources)
                
                span.set_attribute("resources_gained", resources_gained)
                span.set_attribute("new_resources_total", new_resources)
                
                with self.lock:
                    self.last_resource_collection[self.location_id] = datetime.now()
                
                # Force metric collection after resource update
                self.telemetry.collect_metrics()
                
                return jsonify({
                    "success": True,
                    "message": f"Collected {resources_gained} resources",
                    "current_resources": new_resources,
                    "cooldown": False
                })
        
        @self.app.route('/create_army', methods=['POST'])
        def create_army():
            # Extract trace context from request headers
            context = extract(request.headers)

            with self.tracer.start_as_current_span(
                "create_army",
                context=context,
                kind=SpanKind.SERVER,
                attributes={
                    "location_name": self.location_info["name"],
                    "location_type": self.location_info["type"],
                    "game.map.id": self.map_id,
                }
            ) as span:
                if self.location_info["type"] != "capital":
                    span.set_status(trace.StatusCode.ERROR, "Only capitals can create armies")
                    return jsonify({
                        "success": False,
                        "message": "Only capitals can create armies"
                    }), 403

                location_state = self._get_location_state(self.location_id)
                current_resources = location_state["resources"]
                current_army = location_state["army"]
                faction = location_state["faction"]
                currency = get_army_currency(self.map_id, faction)
                cost = get_army_cost(self.map_id, faction)

                span.set_attribute("current_resources", current_resources)
                span.set_attribute("current_army", current_army)
                span.set_attribute("army_cost", cost)
                span.set_attribute("army_currency", currency)
                span.set_attribute("faction", faction)

                if currency == "corpses":
                    # White Walkers spend corpses from the faction pool, not
                    # resources from the location.
                    if not self._spend_corpses(cost, faction):
                        available = self._get_corpses(faction)
                        span.set_status(trace.StatusCode.ERROR, "Insufficient corpses")
                        return jsonify({
                            "success": False,
                            "message": f"Not enough corpses. Need {cost}, have {available}"
                        }), 400
                    new_resources = current_resources
                    new_army = current_army + 1
                    self._update_location_state(self.location_id, army=new_army)
                    span.set_attribute("game.corpses.spent", cost)
                    span.set_attribute("corpses_remaining", self._get_corpses(faction))
                else:
                    if current_resources < cost:
                        span.set_status(trace.StatusCode.ERROR, "Insufficient resources")
                        return jsonify({
                            "success": False,
                            "message": f"Not enough resources. Need {cost}, have {current_resources}"
                        }), 400

                    new_resources = current_resources - cost
                    new_army = current_army + 1

                    self._update_location_state(
                        self.location_id,
                        resources=new_resources,
                        army=new_army
                    )

                span.set_attribute("new_resources", new_resources)
                span.set_attribute("new_army", new_army)

                self.telemetry.collect_metrics()

                return jsonify({
                    "success": True,
                    "message": "Army created",
                    "current_army": new_army,
                    "current_resources": new_resources,
                    "currency": currency,
                })
        
        @self.app.route('/move_army', methods=['POST'])
        def move_army():
            # Extract trace context from request headers
            context = extract(request.headers)
            
            with self.tracer.start_as_current_span(
                "move_army_request",
                context=context,
                kind=SpanKind.SERVER,
                attributes={
                    "location_name": self.location_info["name"],
                    "location_type": self.location_info["type"]
                }
            ) as move_span:
                data = request.get_json()
                if not data or 'target_location' not in data:
                    move_span.set_status(trace.StatusCode.ERROR, "Target location not specified")
                    return jsonify({"success": False, "message": "Target location not specified"}), 400
                
                target_location = data['target_location']
                remaining_path = data.get('remaining_path', [])
                is_attack_move = data.get('is_attack_move', False)
                
                move_span.set_attribute("target_location", target_location)
                move_span.set_attribute("is_attack_move", is_attack_move)
                
                if target_location not in self.location_info["connections"]:
                    move_span.set_status(trace.StatusCode.ERROR, f"Cannot move to {target_location}")
                    return jsonify({
                        "success": False,
                        "message": f"Cannot move to {target_location}. Not connected to {self.location_id}"
                    }), 400
                
                location_state = self._get_location_state(self.location_id)
                if location_state["army"] <= 0:
                    move_span.set_status(trace.StatusCode.ERROR, "No army to move")
                    return jsonify({
                        "success": False,
                        "message": "No army to move"
                    }), 400
                
                try:
                    army_size = location_state["army"]
                    current_faction = location_state["faction"]
                    movement_id = str(uuid.uuid4())

                    move_span.set_attribute("army_size", army_size)
                    move_span.set_attribute("faction", current_faction)
                    move_span.set_attribute("game.movement.id", movement_id)

                    # Optimistic-concurrency debit: only succeeds if the army
                    # count is still what we just read, so two simultaneous
                    # move requests can't march the same troops twice.
                    if not self._take_all_army(army_size):
                        move_span.set_status(trace.StatusCode.ERROR, "Army changed during request")
                        return jsonify({
                            "success": False,
                            "message": "Army changed while processing — try again"
                        }), 409

                    result = self._continue_army_movement(
                        army_size,
                        current_faction,
                        self.location_id,
                        target_location,
                        remaining_path,
                        is_attack_move,
                        movement_id=movement_id
                    )

                    if not result.get("success", True):
                        move_span.set_status(trace.StatusCode.ERROR, result.get("message", "Unknown error"))

                    return jsonify(result)
                except Exception as e:
                    move_span.record_exception(e)
                    move_span.set_status(trace.StatusCode.ERROR, str(e))
                    return jsonify({
                        "success": False,
                        "message": f"Failed to move army: {str(e)}"
                    }), 500
        
        @self.app.route('/all_out_attack', methods=['POST'])
        def all_out_attack():
            """Launch an all-out attack from a capital to the enemy capital"""
            context = extract(request.headers)
            
            with self.tracer.start_as_current_span(
                "all_out_attack",
                context=context,
                kind=SpanKind.SERVER,
                attributes={
                    "location_name": self.location_info["name"],
                    "location_type": self.location_info["type"]
                }
            ) as attack_span:
                try:
                    if self.location_info["type"] != "capital":
                        attack_span.set_status(trace.StatusCode.ERROR, "Only capitals can launch all-out attacks")
                        return jsonify({
                            "success": False,
                            "message": "Only capitals can launch all-out attacks"
                        }), 403
                    
                    location_state = self._get_location_state(self.location_id)
                    army_size = location_state["army"]
                    faction = location_state["faction"]
                    
                    if army_size <= 0:
                        attack_span.set_status(trace.StatusCode.ERROR, "No army available for attack")
                        return jsonify({
                            "success": False,
                            "message": "No army available for attack"
                        }), 400
                    
                    # Determine enemy capital based on the active map's config.
                    target_capital = self._find_enemy_capital(faction)
                    if not target_capital:
                        attack_span.set_status(trace.StatusCode.ERROR, "No enemy capital on this map")
                        return jsonify({
                            "success": False,
                            "message": "No enemy capital to attack on this map"
                        }), 400
                    attack_span.set_attribute("target_capital", target_capital)
                    
                    attack_path = self._find_path(target_capital, PathType.ATTACK)
                    
                    if not attack_path:
                        attack_span.set_status(trace.StatusCode.ERROR, "No valid path to enemy capital")
                        return jsonify({
                            "success": False,
                            "message": "No valid path to enemy capital"
                        }), 400
                    
                    movement_id = str(uuid.uuid4())
                    attack_span.set_attribute("attack_path", str(attack_path))
                    attack_span.set_attribute("initial_army_size", army_size)
                    attack_span.set_attribute("game.movement.id", movement_id)

                    if len(attack_path) > 1:
                        # Optimistic-concurrency debit (see /move_army). If a
                        # later hop fails at the transport level, the movement
                        # thread credits the army back — no restore needed here.
                        if not self._take_all_army(army_size):
                            attack_span.set_status(trace.StatusCode.ERROR, "Army changed during request")
                            return jsonify({
                                "success": False,
                                "message": "Army changed while processing — try again"
                            }), 409

                        next_loc = attack_path[1]
                        # remaining_path holds the hops *after* next_loc —
                        # the same convention /receive_army uses when it
                        # continues a movement (remaining_path[0] is always
                        # the hop after the receiver, never the receiver).
                        self._continue_army_movement(
                            army_size,
                            faction,
                            self.location_id,
                            next_loc,
                            attack_path[2:],
                            is_attack_move=True,
                            movement_id=movement_id
                        )

                        return jsonify({
                            "success": True,
                            "message": f"All-out attack started with {army_size} troops",
                            "path": attack_path,
                            "army_size": army_size
                        })

                    return jsonify({
                        "success": False,
                        "message": "Invalid attack path"
                    }), 400
                    
                except Exception as e:
                    attack_span.record_exception(e)
                    attack_span.set_status(trace.StatusCode.ERROR, str(e))
                    raise
        
        @self.app.route('/receive_army', methods=['POST'])
        def receive_army():
            try:
                data = request.get_json(silent=True)
                self.logger.info(f"Received army at {self.location_id}: {data}")

                context = extract(request.headers)

                with self.tracer.start_as_current_span(
                    "receive_army",
                    context=context,
                    kind=SpanKind.SERVER,
                    attributes={
                        "location_name": self.location_info["name"],
                        "location_type": self.location_info["type"]
                    }
                ) as battle_span:
                    # Harden the inbound payload before touching any state —
                    # see _validate_inbound_payload for what is rejected.
                    error = self._validate_inbound_payload(data, 'army_size')
                    if error:
                        battle_span.set_status(trace.StatusCode.ERROR, error)
                        return jsonify({"success": False, "message": error}), 400

                    movement_id = data.get('movement_id')
                    cached = self._check_duplicate_movement(movement_id)
                    if cached is not None:
                        # A transport retry re-delivered an army we already
                        # processed — return the original outcome instead of
                        # fighting the battle twice.
                        battle_span.set_attribute("game.movement.duplicate", True)
                        battle_span.set_attribute("game.movement.id", movement_id)
                        return jsonify(cached)

                    attacking_army = data['army_size']
                    attacking_faction = data['faction']
                    source_location = data['source_location']
                    remaining_path = data.get('remaining_path', [])
                    is_attack_move = data.get('is_attack_move', False)

                    location_state = self._get_location_state(self.location_id)
                    defending_army = location_state["army"]
                    defending_faction = location_state["faction"]

                    battle_span.set_attribute("source_location", source_location)
                    battle_span.set_attribute("attacking_army", attacking_army)
                    battle_span.set_attribute("defending_army", defending_army)
                    battle_span.set_attribute("remaining_path", str(remaining_path))
                    battle_span.set_attribute("is_attack_move", is_attack_move)
                    battle_span.set_attribute("game.movement.id", movement_id or "")

                    self.logger.info(f"Remaining path: {remaining_path}, is_attack_move: {is_attack_move}")
                    
                    if attacking_faction == defending_faction:
                        # For all-out attacks, combine armies with friendly villages
                        if is_attack_move and self.location_info["type"] == "village":
                            # Add village's army to the attacking force
                            attacking_army += defending_army
                            # Set village's army to 0
                            self._update_location_state(self.location_id, army=0)
                            battle_span.set_attribute("combined_army_size", attacking_army)
                            self.logger.info(f"Combined armies at {self.location_id}: {attacking_army} (village army was {defending_army})")

                        # Continue movement if there's a path remaining
                        if is_attack_move and remaining_path:
                            next_location = remaining_path[0]
                            new_remaining_path = remaining_path[1:]
                            self.logger.info(f"Continuing attack from {self.location_id} to {next_location}, new path: {new_remaining_path}")

                            result = self._continue_army_movement(
                                attacking_army,  # Use the potentially increased army size
                                attacking_faction,
                                self.location_id,
                                next_location,
                                new_remaining_path,
                                is_attack_move,
                                movement_id=movement_id
                            )
                            battle_span.set_attribute("result", "friendly_passage")
                            self.logger.info(f"Friendly passage result: {result}")
                            # Force metric collection after friendly passage
                            self.telemetry.collect_metrics()
                            self._record_movement_result(movement_id, result)
                            return jsonify(result)
                        elif not is_attack_move:
                            # Normal army movement - combine armies
                            new_army = defending_army + attacking_army
                            self._update_location_state(self.location_id, army=new_army)
                            battle_span.set_attribute("result", "armies_combined")
                            self.logger.info(f"Armies combined at {self.location_info['name']}: {new_army}")
                            # Force metric collection after combining armies
                            self.telemetry.collect_metrics()
                            response = {
                                "success": True,
                                "message": f"Armies combined at {self.location_info['name']}",
                                "current_army": new_army,
                                "faction": defending_faction
                            }
                            self._record_movement_result(movement_id, response)
                            return jsonify(response)
                        else:
                            # All-out attack reached a friendly location with no
                            # remaining path (e.g. the target flipped to our
                            # faction mid-flight). The army garrisons here —
                            # additively, never overwriting whoever already holds
                            # the location.
                            if self.location_info["type"] == "village":
                                # The village garrison was zeroed and merged into
                                # attacking_army above; write the merged stack back.
                                self._update_location_state(self.location_id, army=attacking_army)
                                battle_span.set_attribute("result", "attack_ended_at_village")
                                self.logger.warning(f"All-out attack ended at friendly village {self.location_id}; {attacking_army} units garrison")
                            else:
                                new_army = defending_army + attacking_army
                                self._update_location_state(self.location_id, army=new_army)
                                battle_span.set_attribute("result", "returned_to_capital")
                                self.logger.warning(f"All-out attack ended at {self.location_id} with {attacking_army} troops joining the garrison")

                            self.telemetry.collect_metrics()
                            response = {
                                "success": True,
                                "message": f"Army movement ended at {self.location_info['name']}",
                                "current_army": self._get_location_state(self.location_id)["army"],
                                "faction": defending_faction
                            }
                            self._record_movement_result(movement_id, response)
                            return jsonify(response)
                    
                    # ``battle.occurred`` feeds the dashboard TraceQL filter
                    # ({span.battle.occurred=true}); set it before resolution
                    # so even a crash mid-battle leaves a queryable span.
                    battle_span.set_attribute("battle.occurred", True)

                    # Span events mark *points in time* inside the span —
                    # unlike attributes (span-wide facts), each event carries
                    # its own timestamp and shows up on the trace timeline.
                    battle_span.add_event("battle_started", attributes={
                        "attacking_army": attacking_army,
                        "defending_army": defending_army,
                        "attacker_faction": attacking_faction,
                        "defender_faction": defending_faction,
                        "location_type": self.location_info["type"],
                    })

                    battle_result, remaining_army, new_faction = self._handle_battle(
                        attacking_army,
                        attacking_faction,
                        defending_army,
                        defending_faction,
                        location_type=self.location_info["type"],
                    )

                    total_casualties = max(0, attacking_army + defending_army - remaining_army)
                    battle_span.add_event("casualties_calculated", attributes={
                        "total_casualties": total_casualties,
                        "outcome": battle_result,
                        "remaining_army": remaining_army,
                    })

                    # Corpse harvesting: the White Walkers reap from any battle
                    # they win (either as attacker or defender). Corpses equal
                    # the total physical units that died on both sides.
                    if new_faction == "white_walkers":
                        if total_casualties > 0:
                            self._add_corpses(total_casualties, "white_walkers")
                            battle_span.set_attribute("game.corpses.harvested", total_casualties)
                            battle_span.set_attribute("corpse.source", "battle")

                    if new_faction != defending_faction:
                        battle_span.add_event("territory_captured", attributes={
                            "previous_faction": defending_faction,
                            "new_faction": new_faction,
                            "location.id": self.location_id,
                        })

                    self._update_location_state(
                        self.location_id,
                        army=remaining_army,
                        faction=new_faction
                    )

                    battle_span.set_attribute("result", battle_result)
                    battle_span.set_attribute("remaining_army", remaining_army)
                    battle_span.set_attribute("game.map.id", self.map_id)
                    if self.location_info["type"] == "wall":
                        battle_span.set_attribute("game.wall.held", new_faction != "neutral")
                        battle_span.set_attribute("wall.battle", True)

                    if battle_result == "attacker_victory" and is_attack_move and remaining_path:
                        self.logger.info(f"Continuing army movement at {self.location_id}: {remaining_army}")
                        self.logger.info(f"Battle victory - continuing to {remaining_path[0]}, path: {remaining_path[1:]}")
                        result = self._continue_army_movement(
                            remaining_army,
                            attacking_faction,
                            self.location_id,
                            remaining_path[0],
                            remaining_path[1:],
                            is_attack_move,
                            movement_id=movement_id
                        )
                        self._record_movement_result(movement_id, result)
                        return jsonify(result)

                    if battle_result != "attacker_victory":
                        self.logger.warning(f"Battle result: {battle_result}")
                        battle_span.add_event("battle_result", attributes={
                            "outcome": battle_result,
                            "attacker_faction": attacking_faction,
                            "defender_faction": defending_faction,
                            "remaining_army": remaining_army,
                        })

                    # Force metric collection after battle resolution
                    self.telemetry.collect_metrics()

                    response = {
                        "success": battle_result == "attacker_victory",
                        "message": f"Battle at {self.location_info['name']}: {battle_result}",
                        "current_army": remaining_army,
                        "faction": new_faction
                    }
                    self._record_movement_result(movement_id, response)
                    return jsonify(response)
                    
            except Exception as e:
                self.logger.error(f"Error in receive_army: {str(e)}")
                return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500
        
        @self.app.route('/reset', methods=['POST'])
        def reset():
            self.reset_database()
            return jsonify({"success": True, "message": "Game state reset to initial values"})

        @self.app.route('/reload', methods=['POST'])
        def reload_identity():
            """Re-read the active map from the DB and rebind this slot's identity.

            Called by ``war_map`` after ``/select_map``. The slot's port + the
            telemetry service name do not change — only the logical
            ``location_id``, ``name``, ``type``, ``faction``, connections, and
            rules-scoped behaviour.
            """
            self._load_identity()
            return jsonify({
                "success": True,
                "slot_id": self.slot_id,
                "map_id": self.map_id,
                "location_id": self.location_id,
                "faction": self.location_info["faction"],
                "type": self.location_info["type"],
            })

        @self.app.route('/faction_economy', methods=['GET'])
        def faction_economy():
            """Expose the corpse pool for a faction (used by the AI)."""
            faction = request.args.get('faction', 'white_walkers')
            return jsonify({
                "faction": faction,
                "corpses": self._get_corpses(faction),
            })
        
        @self.app.route('/send_resources_to_capital', methods=['POST'])
        def send_resources_to_capital():
            # Extract trace context from request headers
            context = extract(request.headers)
            
            with self.tracer.start_as_current_span(
                "send_resources_to_capital",
                context=context,  # Use the extracted context
                kind=SpanKind.SERVER,
                attributes={
                    "location_name": self.location_info["name"],
                    "location_type": self.location_info["type"]
                }
            ) as span:
                try:
                    location_state = self._get_location_state(self.location_id)
                    current_resources = location_state["resources"]
                    faction = location_state["faction"]
                    
                    span.set_attribute("resources_amount", current_resources)
                    span.set_attribute("faction", faction)
                    
                    if self.location_info["type"] != "village":
                        span.set_status(trace.StatusCode.ERROR, "Only villages can send resources")
                        self.logger.error(f"Only villages can send resources to capital")
                        return jsonify({
                            "success": False,
                            "message": "Only villages can send resources to capital"
                        }), 403
                    
                    resource_factions = {"southern", "northern", "nights_watch"}
                    if faction not in resource_factions:
                        span.set_status(trace.StatusCode.ERROR, "Faction has no resource economy")
                        self.logger.error(
                            f"Faction {faction!r} has no resource economy; cannot send to capital"
                        )
                        return jsonify({
                            "success": False,
                            "message": "This faction does not send resources",
                        }), 403

                    # Target this faction's capital on the active map.
                    target_capital = self._find_capital(faction)
                    if not target_capital:
                        span.set_status(trace.StatusCode.ERROR, "No friendly capital on this map")
                        return jsonify({
                            "success": False,
                            "message": "No friendly capital to send resources to"
                        }), 400
                    path = self._find_path(target_capital, PathType.RESOURCE)
                    if not path:
                        span.set_status(trace.StatusCode.ERROR, "No valid path to capital")
                        self.logger.error(f"No valid path to capital found")
                        return jsonify({
                            "success": False,
                            "message": "No valid path to capital found"
                        }), 400
                    
                    span.set_attribute("path_to_capital", str(path))
                    span.set_attribute("resource.movement", True)

                    if current_resources <= 0:
                        span.set_status(trace.StatusCode.ERROR, "No resources to send")
                        return jsonify({
                            "success": False,
                            "message": "No resources to send"
                        }), 400

                    if len(path) < 2:
                        span.set_status(trace.StatusCode.ERROR, "Path too short")
                        return jsonify({
                            "success": False,
                            "message": "Already at the capital"
                        }), 400

                    # Debit-at-send: guarded so a concurrent spend can't send
                    # resources this village no longer has. If delivery fails,
                    # _forward_resources credits the amount back.
                    if not self._debit_resources(self.location_id, current_resources):
                        span.set_status(trace.StatusCode.ERROR, "Resources changed during request")
                        return jsonify({
                            "success": False,
                            "message": "Resources changed while processing — try again"
                        }), 409

                    self._forward_resources(current_resources, faction, path[1], path[1:])
                    self._start_resource_cooldown()
                    self.logger.info(f"Resources sent to capital via {path}")
                    # Force metric collection after initiating resource transfer
                    self.telemetry.collect_metrics()
                    return jsonify({
                        "success": True,
                        "message": f"Sending {current_resources} resources to capital via {' -> '.join(path)}",
                        "path": path,
                        "amount": current_resources
                    })
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(trace.StatusCode.ERROR, str(e))
                    self.logger.error(f"Error in send_resources_to_capital: {str(e)}")
                    return jsonify({
                        "success": False,
                        "message": f"Error: {str(e)}"
                    }), 500
        
        @self.app.route('/receive_resources', methods=['POST'])
        def receive_resources():
            data = request.get_json(silent=True)

            context = extract(request.headers)

            with self.tracer.start_as_current_span(
                "receive_resources",
                context=context,
                kind=SpanKind.SERVER,
                attributes={
                    "location": self.location_id,
                    "location_type": self.location_info["type"],
                    "resource.movement": True,
                }
            ) as transfer_span:
                # Harden the inbound payload before touching any state.
                error = self._validate_inbound_payload(data, 'resources')
                if error:
                    transfer_span.set_status(trace.StatusCode.ERROR, error)
                    return jsonify({"success": False, "message": error}), 400

                incoming_resources = data['resources']
                source_location = data['source_location']
                remaining_path = data.get('remaining_path', [])
                faction = data['faction']

                location_state = self._get_location_state(self.location_id)
                current_resources = location_state["resources"]
                current_faction = location_state["faction"]

                transfer_span.set_attribute("source_location", source_location)
                transfer_span.set_attribute("sending_faction", faction)
                transfer_span.set_attribute("receiving_faction", current_faction)
                transfer_span.set_attribute("resources_amount", incoming_resources)

                if current_faction != faction:
                    # Captured: the holding faction keeps the caravan. The
                    # ``captured`` flag tells the sender this was a game
                    # outcome, not a delivery failure — so no refund there.
                    transfer_span.set_status(trace.Status(trace.StatusCode.ERROR, f"Resources captured by {current_faction}"))
                    self._credit_resources(self.location_id, incoming_resources)
                    self.logger.error(f"Resources captured by {current_faction}")
                    return jsonify({
                        "success": False,
                        "captured": True,
                        "message": f"Resources captured by {current_faction}!",
                        "current_resources": current_resources + incoming_resources
                    })

                if len(remaining_path) > 1:
                    # Intermediate friendly hop: relay onward without banking.
                    # The caravan was debited at its origin (debit-at-send),
                    # so crediting here and debiting again would create a
                    # window where the resources exist twice.
                    next_loc = remaining_path[1]
                    transfer_span.set_attribute("relay_to", next_loc)
                    self.logger.info(f"Relaying {incoming_resources} resources via {self.location_id} to {next_loc}")
                    self._forward_resources(incoming_resources, faction, next_loc, remaining_path[1:])
                    return jsonify({
                        "success": True,
                        "message": f"Resources relaying through {self.location_info['name']}",
                        "current_resources": current_resources
                    })

                # Final destination: bank the caravan.
                new_resources = current_resources + incoming_resources
                self._credit_resources(self.location_id, incoming_resources)
                self.logger.info(f"Resources updated to {new_resources}")

                transfer_span.set_attribute("final_resources", new_resources)
                if self.location_info["type"] == "capital":
                    transfer_span.set_attribute("resources_reached_capital", True)

                self.logger.info(f"Resources received at {self.location_info['name']}")
                return jsonify({
                    "success": True,
                    "message": f"Resources received at {self.location_info['name']}",
                    "current_resources": new_resources
                })
    
    def run(self):
        port = self.location_info["port"]
        self.app.run(host='0.0.0.0', port=port)
        self.logger.info(f"Location server running on port {port}")


if __name__ == '__main__':
    # Docker entrypoint: read SLOT_ID env var, resolve identity from the
    # shared active_map_id, and serve. SERVICE_NAME comes from LOCATION_NAME
    # (set per-container in docker-compose.yml) or is synthesised from slot.
    LocationServer().run()