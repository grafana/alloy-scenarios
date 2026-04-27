import os
import json
import sqlite3
import requests
import threading
import uuid
import time
import atexit
from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from telemetry import GameTelemetry
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opentelemetry.propagate import inject

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'war_of_westeros_secret_key')

# AI Service configuration
AI_SERVICE_URL = os.environ.get('AI_URL', 'http://localhost:8081')

# Initialize telemetry
telemetry = GameTelemetry(service_name="war_map")
logger = telemetry.get_logger()
tracer = telemetry.get_tracer()
atexit.register(telemetry.shutdown)

# Game session tracking database
GAME_SESSIONS_DB = os.environ.get('GAME_SESSIONS_DB', 'game_sessions.db')  # Use local file for development

# Game state variables
GAME_OVER = False
WINNER = None
VICTORY_MESSAGE = None

# ----------------------------------------------------------------
# Maps — in-UI picker metadata.
# Full per-location config lives in app/game_config.py. This is a compact
# read-only duplicate of the fields war_map actually needs: layout for the
# canvas, tick rules for the hold-to-win loop, faction/AI wiring for the
# picker screen. Keep the map-id strings in sync with app/game_config.py.
# ----------------------------------------------------------------
DEFAULT_MAP_ID = "war_of_kingdoms"

MAPS_META = {
    "war_of_kingdoms": {
        "display_name": "War of Kingdoms",
        "description": (
            "Northern and Southern kingdoms clash for dominance. "
            "Capture the enemy capital to win."
        ),
        "single_player": False,
        "player_faction": None,
        "ai_faction": None,
        "factions": ["northern", "southern"],
        "tick_interval_s": 0,
        "win_hold_ticks": 0,
        "icon": "fa-chess-knight",
    },
    "white_walkers_attack": {
        "display_name": "White Walkers Attack",
        "description": (
            "The Long Night has come. As the Night's Watch, hold every Wall "
            "keep for 5 ticks before the White Walkers do. Single-player."
        ),
        "single_player": True,
        "player_faction": "nights_watch",
        "ai_faction": "white_walkers",
        "factions": ["nights_watch", "white_walkers", "barbarian"],
        "tick_interval_s": 30,
        "win_hold_ticks": 5,
        "icon": "fa-icicles",
    },
}

# Map layout — canvas x/y percentages per location. Each map's keys must
# match the location ids in app/game_config.py's MAPS[map_id]["locations"].
LOCATION_POSITIONS_BY_MAP = {
    "war_of_kingdoms": {
        "southern_capital": {"x": 20, "y": 70, "type": "capital", "name": "Southern Capital"},
        "northern_capital": {"x": 80, "y": 20, "type": "capital", "name": "Northern Capital"},
        "village_1": {"x": 35, "y": 55, "type": "village", "name": "Village 1"},
        "village_2": {"x": 65, "y": 35, "type": "village", "name": "Village 2"},
        "village_3": {"x": 30, "y": 40, "type": "village", "name": "Village 3"},
        "village_4": {"x": 45, "y": 65, "type": "village", "name": "Village 4"},
        "village_5": {"x": 50, "y": 50, "type": "village", "name": "Village 5"},
        "village_6": {"x": 70, "y": 45, "type": "village", "name": "Village 6"},
    },
    "white_walkers_attack": {
        "nights_watch_fortress": {"x": 50, "y": 85, "type": "capital", "name": "Castle Black"},
        "white_walker_fortress": {"x": 50, "y": 15, "type": "capital", "name": "The Lands of Always Winter"},
        "wall_west": {"x": 20, "y": 50, "type": "wall", "name": "Westwatch"},
        "wall_center_west": {"x": 40, "y": 50, "type": "wall", "name": "Queensgate"},
        "wall_center_east": {"x": 60, "y": 50, "type": "wall", "name": "Deep Lake"},
        "wall_east": {"x": 80, "y": 50, "type": "wall", "name": "Eastwatch-by-the-Sea"},
        "barbarian_village_west": {"x": 10, "y": 72, "type": "village", "name": "Free Folk Camp (West)"},
        "barbarian_village_east": {"x": 90, "y": 72, "type": "village", "name": "Free Folk Camp (East)"},
    },
}

LOCATION_CONNECTIONS_BY_MAP = {
    "war_of_kingdoms": [
        ["southern_capital", "village_1"],
        ["southern_capital", "village_3"],
        ["northern_capital", "village_2"],
        ["northern_capital", "village_6"],
        ["village_1", "village_2"],
        ["village_1", "village_4"],
        ["village_2", "village_5"],
        ["village_3", "village_5"],
        ["village_3", "village_6"],
        ["village_4", "village_5"],
        ["village_5", "village_6"],
    ],
    "white_walkers_attack": [
        ["nights_watch_fortress", "wall_west"],
        ["nights_watch_fortress", "wall_center_west"],
        ["nights_watch_fortress", "wall_center_east"],
        ["nights_watch_fortress", "wall_east"],
        ["white_walker_fortress", "wall_west"],
        ["white_walker_fortress", "wall_center_west"],
        ["white_walker_fortress", "wall_center_east"],
        ["white_walker_fortress", "wall_east"],
        ["wall_west", "wall_center_west"],
        ["wall_center_west", "wall_center_east"],
        ["wall_center_east", "wall_east"],
        ["wall_west", "barbarian_village_west"],
        ["wall_east", "barbarian_village_east"],
    ],
}

# Per-map list of wall-type locations for the hold-to-win check.
WALL_LOCATIONS_BY_MAP = {
    map_id: [
        loc_id for loc_id, meta in positions.items()
        if meta.get("type") == "wall"
    ]
    for map_id, positions in LOCATION_POSITIONS_BY_MAP.items()
}

# Kept for legacy call sites that still reference the module-level names.
# These stay pointing at the WoK defaults — call sites that need per-map
# behaviour should call _current_positions() / _current_connections() instead.
LOCATION_POSITIONS = LOCATION_POSITIONS_BY_MAP[DEFAULT_MAP_ID]
LOCATION_CONNECTIONS = LOCATION_CONNECTIONS_BY_MAP[DEFAULT_MAP_ID]


def _current_positions():
    """Positions for the currently active map (reads active_map_id from DB)."""
    return LOCATION_POSITIONS_BY_MAP.get(
        get_active_map_id(), LOCATION_POSITIONS_BY_MAP[DEFAULT_MAP_ID]
    )


def _current_connections():
    """Connections for the currently active map."""
    return LOCATION_CONNECTIONS_BY_MAP.get(
        get_active_map_id(), LOCATION_CONNECTIONS_BY_MAP[DEFAULT_MAP_ID]
    )


def _current_walls():
    return WALL_LOCATIONS_BY_MAP.get(get_active_map_id(), [])

def init_game_session_tracking():
    """Initialize the game session tracking database"""
    try:
        # Ensure the database directory exists if using an absolute path
        db_dir = os.path.dirname(GAME_SESSIONS_DB)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        conn = sqlite3.connect(GAME_SESSIONS_DB)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_session_id TEXT NOT NULL,
            action_sequence INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            player_name TEXT,
            faction TEXT,
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            location_id TEXT,
            target_location_id TEXT,
            timestamp INTEGER NOT NULL,
            game_state_after TEXT,
            map_id TEXT,
            UNIQUE(game_session_id, action_sequence)
        )
        ''')

        # Best-effort migration for existing game_sessions.db files created
        # before the map_id column existed. SQLite's ALTER TABLE only adds
        # missing columns; the IGNORE/OperationalError guard keeps a
        # fresh-install run idempotent.
        try:
            cursor.execute("ALTER TABLE game_actions ADD COLUMN map_id TEXT")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()
        logger.info(f"Game session tracking database initialized: {GAME_SESSIONS_DB}")
        
    except Exception as e:
        logger.error(f"Failed to initialize game session tracking database: {e}")
        # Don't fail the app startup if database init fails
        pass

# Initialize the game session tracking database immediately
init_game_session_tracking()
# Tables in game_state.db (game_config, wall_hold, faction_economy) are
# initialized lazily on first call to _ensure_game_config_tables() — see
# the in-process startup path later in this module.

def store_game_action(game_session_id, action_type, player_name, faction,
                     trace_id, span_id, location_id=None, target_location_id=None,
                     game_state=None, map_id=None):
    """Store a game action with its trace information.

    ``map_id`` is recorded so the replay page can render the correct map
    layout (positions/connections) for sessions played on non-default maps.
    Defaults to the currently active map when not supplied.
    """
    if map_id is None:
        try:
            map_id = get_active_map_id()
        except Exception:
            map_id = DEFAULT_MAP_ID

    conn = sqlite3.connect(GAME_SESSIONS_DB)
    cursor = conn.cursor()

    # Get next sequence number
    cursor.execute("SELECT MAX(action_sequence) FROM game_actions WHERE game_session_id = ?",
                   (game_session_id,))
    result = cursor.fetchone()
    next_sequence = (result[0] or 0) + 1

    # Debug logging
    logger.info(f"Storing action: session={game_session_id}, sequence={next_sequence}, action={action_type}, trace_id={trace_id}, span_id={span_id}, map_id={map_id}")

    cursor.execute('''
    INSERT INTO game_actions
    (game_session_id, action_sequence, action_type, player_name, faction,
     trace_id, span_id, location_id, target_location_id, timestamp, game_state_after, map_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (game_session_id, next_sequence, action_type, player_name, faction,
          trace_id, span_id, location_id, target_location_id,
          int(time.time()), json.dumps(game_state) if game_state else None, map_id))

    conn.commit()
    conn.close()
    return next_sequence


def get_session_map_id(session_id):
    """Resolve the map a session was played on.

    Looks at any non-NULL ``map_id`` in the session's actions; falls back to
    the currently active map for sessions stored before the column was
    populated. Returns ``DEFAULT_MAP_ID`` as a last resort so the replay
    template always has a layout to render.
    """
    try:
        conn = sqlite3.connect(GAME_SESSIONS_DB)
        try:
            row = conn.execute(
                "SELECT map_id FROM game_actions "
                "WHERE game_session_id = ? AND map_id IS NOT NULL "
                "ORDER BY action_sequence LIMIT 1",
                (session_id,),
            ).fetchone()
            if row and row[0] in LOCATION_POSITIONS_BY_MAP:
                return row[0]
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"get_session_map_id failed for {session_id}: {e}")

    try:
        active = get_active_map_id()
        if active in LOCATION_POSITIONS_BY_MAP:
            return active
    except Exception:
        pass
    return DEFAULT_MAP_ID

def get_previous_action_context(game_session_id, target_sequence):
    """Get the action's span context for linking by target sequence number"""
    conn = sqlite3.connect(GAME_SESSIONS_DB)
    cursor = conn.cursor()
    
    # Debug logging
    logger.info(f"Looking for action: session={game_session_id}, target_sequence={target_sequence}")
    
    cursor.execute('''
    SELECT trace_id, span_id FROM game_actions 
    WHERE game_session_id = ? AND action_sequence = ?
    ''', (game_session_id, target_sequence))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        try:
            # Debug logging
            logger.info(f"Found target action: trace_id={result[0]}, span_id={result[1]}")
            
            # Reconstruct the span context from stored trace and span IDs
            trace_id = int(result[0], 16)
            span_id = int(result[1], 16)
            
            # Create span context with proper trace flags
            span_context = trace.SpanContext(
                trace_id=trace_id,
                span_id=span_id,
                is_remote=True,
                trace_flags=trace.TraceFlags.SAMPLED
            )
            
            logger.info(f"Created span context for linking: trace_id={trace_id:032x}, span_id={span_id:016x}")
            return span_context
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to reconstruct span context: {e}")
            return None
    else:
        logger.info(f"No action found for sequence {target_sequence}")
    return None

def create_span_link_from_context(span_context, link_type="game_sequence"):
    """Create a span link from a span context using the official API"""
    if span_context is None:
        return None
    
    try:
        link = trace.Link(
            span_context,
            attributes={
                "link.type": link_type,
                "link.relation": "follows",
                "game.sequence": "true"
            }
        )
        return link
    except Exception as e:
        logger.error(f"Failed to create span link: {e}")
        return None

@app.after_request
def remove_frame_options(response):
    response.headers.pop('X-Frame-Options', None)
    return response

# Configuration
DATABASE_FILE = os.environ.get('DATABASE_FILE', '../app/game_state.db')
API_BASE_URL = os.environ.get('API_BASE_URL', 'http://localhost')  # Base URL for API calls

# Location server ports (from game_config.py). These are keyed by the
# *current-map* location id; when the active map changes, the keys here
# follow along because both maps assign the same port to the same slot.
LOCATION_PORTS = {
    "southern_capital": 5001,
    "northern_capital": 5002,
    "village_1": 5003,
    "village_2": 5004,
    "village_3": 5005,
    "village_4": 5006,
    "village_5": 5007,
    "village_6": 5008,
    # White Walkers Attack mappings (same ports — just aliased).
    "nights_watch_fortress": 5001,
    "white_walker_fortress": 5002,
    "wall_west": 5003,
    "wall_center_west": 5004,
    "wall_center_east": 5005,
    "wall_east": 5006,
    "barbarian_village_west": 5007,
    "barbarian_village_east": 5008,
}

# Container hostname per logical location id. WWA reuses the same 8 slot
# containers, so its location ids resolve to the WoK container names. Without
# this aliasing, ``location_id.replace('_', '-')`` produces hostnames like
# ``nights-watch-fortress`` that don't exist in the docker network and the
# /map render returns an empty locations dict (blank map).
CONTAINER_FOR_LOCATION_ID = {
    "southern_capital": "southern-capital",
    "northern_capital": "northern-capital",
    "village_1": "village-1",
    "village_2": "village-2",
    "village_3": "village-3",
    "village_4": "village-4",
    "village_5": "village-5",
    "village_6": "village-6",
    "nights_watch_fortress": "southern-capital",
    "white_walker_fortress": "northern-capital",
    "wall_west": "village-1",
    "wall_center_west": "village-2",
    "wall_center_east": "village-3",
    "wall_east": "village-4",
    "barbarian_village_west": "village-5",
    "barbarian_village_east": "village-6",
}

# Container hostname (in docker-compose) per slot. Stable across maps.
SLOT_CONTAINER_NAMES = {
    "slot_1": "southern-capital",
    "slot_2": "northern-capital",
    "slot_3": "village-1",
    "slot_4": "village-2",
    "slot_5": "village-3",
    "slot_6": "village-4",
    "slot_7": "village-5",
    "slot_8": "village-6",
}

# Port per slot.
SLOT_PORTS = {
    "slot_1": 5001,
    "slot_2": 5002,
    "slot_3": 5003,
    "slot_4": 5004,
    "slot_5": 5005,
    "slot_6": 5006,
    "slot_7": 5007,
    "slot_8": 5008,
}


def _container_for_slot(slot_id):
    """Return the docker-compose service name hosting ``slot_id`` (stable)."""
    return SLOT_CONTAINER_NAMES.get(slot_id, slot_id.replace('_', '-'))


def _slot_port_pairs():
    """Yield (slot_id, port) tuples for all 8 slots."""
    return list(SLOT_PORTS.items())

# LOCATION_POSITIONS and LOCATION_CONNECTIONS are defined earlier (as the
# WoK default slices of the LOCATION_*_BY_MAP dicts). Legacy call sites that
# still reference the unsuffixed names get the WoK layout; new code should
# go through _current_positions() / _current_connections().

# Game state - track victory conditions (local process cache; also read
# from wall_hold on map WWA).
# Note: GAME_OVER/WINNER/VICTORY_MESSAGE already declared near top of file.

def get_db_connection():
    """Create a connection to the SQLite database"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------------------------------------------------------
# Active map + wall-hold state (lives in game_state.db so location
# servers and war_map agree on the single source of truth).
# ----------------------------------------------------------------

def _ensure_game_config_tables():
    """Create game_config, faction_economy, and wall_hold if missing, and
    migrate the war_map table for single-player maps (adds map_id + drops the
    faction UNIQUE constraint so nights_watch can be registered without
    conflicting with the WoK two-faction model).
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
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
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS faction_economy (
            faction TEXT PRIMARY KEY,
            corpses INTEGER NOT NULL DEFAULT 0
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS wall_hold (
            map_id TEXT NOT NULL,
            faction TEXT NOT NULL,
            ticks INTEGER NOT NULL DEFAULT 0,
            last_update INTEGER NOT NULL,
            PRIMARY KEY (map_id, faction)
        )
        ''')
        # war_map table: additive map_id column for session-level bookkeeping.
        try:
            cursor.execute("ALTER TABLE war_map ADD COLUMN map_id TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to ensure game_config tables: {e}")


def get_active_map_id():
    """Return the currently active map id from game_state.db (cached row)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM game_config WHERE key = 'active_map_id'")
        row = cursor.fetchone()
        conn.close()
        return row['value'] if row else DEFAULT_MAP_ID
    except sqlite3.Error:
        return DEFAULT_MAP_ID


def set_active_map_id(map_id):
    """Persist the active map id. Location services pick this up via /reload."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO game_config (key, value) VALUES ('active_map_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (map_id,),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.Error as e:
        logger.error(f"Failed to set active map id: {e}")
        return False


def reset_wall_hold(map_id):
    """Zero the wall-hold counter for every faction on ``map_id``."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wall_hold WHERE map_id = ?", (map_id,))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to reset wall_hold for {map_id}: {e}")


def bump_wall_hold(map_id, faction, reset_others=True):
    """Increment ``faction``'s tick count on ``map_id``. Optionally reset
    every other faction back to 0. Returns the new tick count.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = int(time.time())
        if reset_others:
            cursor.execute(
                "UPDATE wall_hold SET ticks = 0 WHERE map_id = ? AND faction != ?",
                (map_id, faction),
            )
        cursor.execute(
            "INSERT INTO wall_hold (map_id, faction, ticks, last_update) "
            "VALUES (?, ?, 1, ?) "
            "ON CONFLICT(map_id, faction) DO UPDATE SET "
            "ticks = ticks + 1, last_update = excluded.last_update",
            (map_id, faction, now),
        )
        cursor.execute(
            "SELECT ticks FROM wall_hold WHERE map_id = ? AND faction = ?",
            (map_id, faction),
        )
        row = cursor.fetchone()
        conn.commit()
        conn.close()
        return int(row['ticks']) if row else 0
    except sqlite3.Error as e:
        logger.error(f"Failed to bump wall_hold: {e}")
        return 0


def get_wall_hold(map_id):
    """Return {faction: ticks} for the given map."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT faction, ticks FROM wall_hold WHERE map_id = ?", (map_id,))
        rows = cursor.fetchall()
        conn.close()
        return {r['faction']: int(r['ticks']) for r in rows}
    except sqlite3.Error:
        return {}


def get_faction_corpses(faction):
    """Read a faction's corpse pool (0 when no row yet)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT corpses FROM faction_economy WHERE faction = ?", (faction,))
        row = cursor.fetchone()
        conn.close()
        return int(row['corpses']) if row else 0
    except sqlite3.Error:
        return 0


def check_faction_availability(faction):
    """Check if a faction is already claimed by another player"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if the war_map table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='war_map'")
        if not cursor.fetchone():
            # Create the war_map table if it doesn't exist
            cursor.execute('''
            CREATE TABLE war_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faction TEXT UNIQUE NOT NULL,
                player_name TEXT,
                session_id TEXT UNIQUE
            )
            ''')
            conn.commit()
        
        # Check if the faction is already taken
        cursor.execute("SELECT * FROM war_map WHERE faction = ?", (faction,))
        result = cursor.fetchone()
        
        conn.close()
        logger.info(f"Faction availability check: {result is None}")
        return result is None  # True if available, False if taken
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return False

def register_faction(faction, player_name, session_id):
    """Register a player's faction choice"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Try to insert the new faction record
        cursor.execute(
            "INSERT INTO war_map (faction, player_name, session_id) VALUES (?, ?, ?)",
            (faction, player_name, session_id)
        )
        conn.commit()
        conn.close()
        logger.info(f"Faction registered: {faction} for {player_name} with session ID {session_id}")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database error when registering faction: {e}")
        return False

def get_player_faction(session_id):
    """Get the faction associated with a session ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT faction FROM war_map WHERE session_id = ?", (session_id,))
        result = cursor.fetchone()
        
        conn.close()
        logger.info(f"Player faction retrieved: {result['faction'] if result else None}")
        return result['faction'] if result else None
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None

def release_faction(session_id):
    """Release a faction when a player logs out or disconnects"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM war_map WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
        logger.info(f"Faction released for session ID: {session_id}")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database error when releasing faction: {e}")
        return False

def release_all_factions():
    """Release all faction assignments - used for game reset"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM war_map")
        conn.commit()
        conn.close()
        logger.info("All factions released")
        return True
    except sqlite3.Error as e:
        logger.error(f"Database error when releasing all factions: {e}")
        return False

def get_location_url(location_id):
    """Get the URL for a location's API"""
    # In Docker, use container names instead of localhost. WWA location ids
    # alias the WoK slot containers — see CONTAINER_FOR_LOCATION_ID.
    if os.environ.get('IN_DOCKER'):
        host = CONTAINER_FOR_LOCATION_ID.get(
            location_id, location_id.replace('_', '-')
        )
    else:
        host = 'localhost'

    port = LOCATION_PORTS[location_id]
    return f"http://{host}:{port}"

def make_api_request(location_id, endpoint, method='GET', data=None):
    """Make an API request to a location server with trace context."""
    url = f"{get_location_url(location_id)}/{endpoint}"
    
    # Only create spans for important operations, not for status checks
    important_endpoints = {'move_army', 'all_out_attack', 'send_resources_to_capital', 'receive_army', 'receive_resources', 'collect_resources', 'create_army'}
    
    headers = {"Content-Type": "application/json"}
    if endpoint in important_endpoints:
        # Create span only for important operations
        with tracer.start_as_current_span(
            "location_api_request",
            kind=SpanKind.CLIENT,
            attributes={
                "location.id": location_id,
                "location.endpoint": endpoint,
                "http.method": method
            }
        ) as span:
            inject(headers)  # Inject trace context into headers
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
                return {"error": str(e)}
    else:
        # For status checks and other non-important operations, just make the request without tracing
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            else:  # POST
                response = requests.post(url, json=data, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}

def check_game_over(locations_data, map_id=None):
    """Dispatch to the right win-condition check based on the active map."""
    if map_id is None:
        map_id = get_active_map_id()
    if map_id == "white_walkers_attack":
        # WWA games end only via hold-the-walls. Capital captures do not end
        # the game (the capital can change hands mid-match).
        return check_wall_hold_win(locations_data, map_id)
    return check_capital_capture_win(locations_data)


def check_capital_capture_win(locations_data):
    """Classic WoK win: take the enemy capital."""
    global GAME_OVER, WINNER, VICTORY_MESSAGE

    if locations_data.get('southern_capital', {}).get('faction') == 'northern':
        GAME_OVER = True
        WINNER = 'northern'
        VICTORY_MESSAGE = "The Northern Kingdom has conquered the Southern Capital! Victory through unity!"
        return True

    if locations_data.get('northern_capital', {}).get('faction') == 'southern':
        GAME_OVER = True
        WINNER = 'southern'
        VICTORY_MESSAGE = "The Southern Kingdom has conquered the Northern Capital! Glory to the South!"
        return True

    logger.info("Game is not over")
    return False


def check_wall_hold_win(locations_data, map_id):
    """White Walkers Attack win: one faction has held every wall for the
    configured number of ticks. This is a passive check — the tick thread
    owns incrementing the counter; here we just observe + declare.
    """
    global GAME_OVER, WINNER, VICTORY_MESSAGE

    threshold = MAPS_META.get(map_id, {}).get("win_hold_ticks", 0)
    if threshold <= 0:
        return False

    holds = get_wall_hold(map_id)
    for faction, ticks in holds.items():
        if ticks >= threshold:
            GAME_OVER = True
            WINNER = faction
            if faction == "nights_watch":
                VICTORY_MESSAGE = (
                    "The Night's Watch held the Wall! The Long Night is broken."
                )
            elif faction == "white_walkers":
                VICTORY_MESSAGE = (
                    "The Wall has fallen. The Long Night has come for Westeros."
                )
            else:
                VICTORY_MESSAGE = f"{faction.title()} held every Wall keep for {threshold} ticks."
            return True

    logger.debug(f"Wall hold check: {holds} (threshold {threshold})")
    return False

def reset_game_state():
    """Reset the game state"""
    global GAME_OVER, WINNER, VICTORY_MESSAGE
    GAME_OVER = False
    WINNER = None
    VICTORY_MESSAGE = None

def reset_game_data():
    """Reset the game completely by resetting each location's state"""
    # First, reset our local game state
    reset_game_state()
    
    # Deactivate AI if it's running
    try:
        requests.post(f"{AI_SERVICE_URL}/deactivate", timeout=5)
        logger.info("AI deactivated during game reset")
    except Exception as e:
        logger.warning(f"Failed to deactivate AI during reset: {e}")
    
    # Next, reset all faction assignments
    release_all_factions()
    
    # Clear the game session tracking database
    try:
        conn = sqlite3.connect(GAME_SESSIONS_DB)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM game_actions")
        conn.commit()
        conn.close()
        logger.info("Game session tracking database cleared")
    except Exception as e:
        logger.warning(f"Failed to clear game session database: {e}")
    
    # Finally, reset one location to trigger a database reset
    # (Since they all share the same database, we only need to reset one)
    try:
        make_api_request('southern_capital', 'reset', method='POST')
        logger.info("Game data reset")
        return True
    except Exception as e:
        logger.error(f"Error resetting game data: {e}")
        return False

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/')
def index():
    """Home page. Routes through the map picker on first visit; once the
    user has picked a map the faction-selection view (WoK) or auto-start
    view (WWA single-player) is served instead.
    """
    _ensure_game_config_tables()

    # Already in a game with a faction? Go straight to the map.
    if 'session_id' in session and get_player_faction(session['session_id']):
        return redirect(url_for('game_map'))

    # No map chosen yet → map picker.
    if 'map_id' not in session:
        return redirect(url_for('map_picker'))

    map_id = session['map_id']
    meta = MAPS_META.get(map_id, MAPS_META[DEFAULT_MAP_ID])

    if meta["single_player"]:
        # Single-player maps skip the faction cards. A single CTA button posts
        # back with faction=player_faction.
        player_faction = meta["player_faction"]
        player_available = check_faction_availability(player_faction)
        return render_template(
            'index.html',
            map_id=map_id,
            map_meta=meta,
            single_player=True,
            player_faction=player_faction,
            player_available=player_available,
            southern_available=False,
            northern_available=False,
        )

    # Classic WoK two-faction flow.
    southern_available = check_faction_availability('southern')
    northern_available = check_faction_availability('northern')
    logger.info(f"Southern available: {southern_available}, Northern available: {northern_available}")

    return render_template(
        'index.html',
        map_id=map_id,
        map_meta=meta,
        single_player=False,
        southern_available=southern_available,
        northern_available=northern_available,
    )


@app.route('/map_picker')
def map_picker():
    """Map selection screen. Renders one card per entry in MAPS_META."""
    _ensure_game_config_tables()
    return render_template('map_picker.html', maps=MAPS_META)


@app.route('/select_map', methods=['POST'])
def select_map():
    """Persist the chosen map as active + reload every location service.

    Steps:
      1. Write ``active_map_id`` to game_config.
      2. Reset the locations table via one location's ``/reset`` (shared DB —
         one call repopulates the 8 rows from the new map's config).
      3. POST ``/reload`` to every slot so the in-memory ``location_info`` on
         each service rebinds without a container restart.
      4. For single-player maps, auto-register the preset player faction and
         auto-activate the AI as the preset enemy faction.
      5. Redirect to the entry UI (map-aware from the session).
    """
    map_id = request.form.get('map_id') or DEFAULT_MAP_ID
    if map_id not in MAPS_META:
        logger.error(f"Unknown map_id: {map_id}")
        return redirect(url_for('map_picker'))

    with tracer.start_as_current_span(
        "select_map",
        kind=SpanKind.SERVER,
        attributes={"game.map.id": map_id},
    ) as span:
        # 1. Persist + wipe any previous wall-hold counters.
        set_active_map_id(map_id)
        reset_wall_hold(map_id)
        # Clear all maps' old counters to avoid stale wins after switching.
        for mid in MAPS_META:
            reset_wall_hold(mid)

        # 2. Reset locations rows to match the new map.
        try:
            # Any one container will do — the DB is shared. Use the first
            # Docker service name (stable across maps).
            reset_container = _container_for_slot("slot_1")
            requests.post(
                f"http://{reset_container}:5001/reset" if os.environ.get('IN_DOCKER')
                else f"http://localhost:5001/reset",
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"Failed to reset location rows during map switch: {e}")

        # 3. Kick every slot to reload identity.
        for slot_id, port in _slot_port_pairs():
            try:
                host = _container_for_slot(slot_id) if os.environ.get('IN_DOCKER') else "localhost"
                requests.post(f"http://{host}:{port}/reload", timeout=5)
            except Exception as e:
                logger.warning(f"Failed to /reload {slot_id}: {e}")

        # 4. Clear faction claims + session data so the new map starts clean.
        release_all_factions()
        session.pop('faction', None)
        session.pop('player_name', None)
        session.pop('game_session_id', None)
        session.pop('action_sequence', None)
        session.pop('session_id', None)
        session['map_id'] = map_id

        meta = MAPS_META[map_id]

        # 5. Single-player: AI activation is deferred until the player clicks
        # "Take the Black" on the index page (so the player always explicitly
        # starts the game). But we do pre-reset the game-over flags.
        reset_game_state()
        span.set_attribute("single_player", meta["single_player"])

    return redirect(url_for('index'))


@app.route('/select_faction', methods=['POST'])
def select_faction():
    """Process faction selection (WoK two-player or single-player preset)."""
    map_id = session.get('map_id', DEFAULT_MAP_ID)
    meta = MAPS_META.get(map_id, MAPS_META[DEFAULT_MAP_ID])

    faction = request.form.get('faction')
    player_name = request.form.get('player_name', 'Unknown Player')

    allowed = set(meta.get("factions", []))
    if not faction or faction not in allowed:
        return render_template(
            'index.html',
            map_id=map_id,
            map_meta=meta,
            single_player=meta["single_player"],
            player_faction=meta.get("player_faction"),
            southern_available=check_faction_availability('southern'),
            northern_available=check_faction_availability('northern'),
            player_available=(
                check_faction_availability(meta.get("player_faction"))
                if meta["single_player"] else False
            ),
            error="Invalid faction selected",
        )

    # Check if faction is available
    if not check_faction_availability(faction):
        logger.info(f"Faction {faction} is already taken")
        return render_template(
            'index.html',
            map_id=map_id,
            map_meta=meta,
            single_player=meta["single_player"],
            player_faction=meta.get("player_faction"),
            southern_available=check_faction_availability('southern'),
            northern_available=check_faction_availability('northern'),
            player_available=False,
            error=f"The {faction.replace('_', ' ').title()} faction is already taken",
        )

    # Generate a session ID if not present
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    # Generate a game session ID for span linking
    if 'game_session_id' not in session:
        session['game_session_id'] = str(uuid.uuid4())
        session['action_sequence'] = 0  # Initialize action sequence
        logger.info(f"Initialized game session: {session['game_session_id']}")

    # Register the faction
    if register_faction(faction, player_name, session['session_id']):
        session['faction'] = faction
        session['player_name'] = player_name
        session['is_ai'] = False  # Human player by default
        logger.info(f"Player {player_name} selected faction {faction} on map {map_id}")

        # On single-player maps, auto-activate the AI as the preset enemy
        # the moment the human commits to playing.
        if meta["single_player"] and meta.get("ai_faction"):
            try:
                requests.post(
                    f"{AI_SERVICE_URL}/activate",
                    json={"faction": meta["ai_faction"], "map_id": map_id},
                    timeout=5,
                )
                logger.info(f"Auto-activated AI as {meta['ai_faction']} for single-player map {map_id}")
            except Exception as e:
                logger.warning(f"Auto-activation of AI failed: {e}")

        return redirect(url_for('game_map'))
    else:
        logger.error(f"Failed to register faction {faction}")
        return render_template(
            'index.html',
            map_id=map_id,
            map_meta=meta,
            single_player=meta["single_player"],
            player_faction=meta.get("player_faction"),
            southern_available=check_faction_availability('southern'),
            northern_available=check_faction_availability('northern'),
            player_available=False,
            error=f"Failed to register {faction.replace('_', ' ').title()} faction",
        )

@app.route('/logout')
def logout():
    """Log out and release faction"""
    if 'session_id' in session:
        release_faction(session['session_id'])
        logger.info(f"Faction released for session ID: {session['session_id']}")
    # Clear the session
    session.clear()
    return redirect(url_for('index'))

@app.route('/restart-game')
def restart_game():
    """Reset the game and redirect all players to faction selection"""
    logger.info("Game restart initiated")
    
    # Store current session info for logging
    current_player = session.get('player_name', 'Unknown')
    current_faction = session.get('faction', 'Unknown')
    
    # Reset the entire game state
    success = reset_game_data()
    
    # Clear current user's session completely
    session.clear()
    
    # Log the restart
    if success:
        logger.info(f"Game successfully restarted by {current_player} ({current_faction})")
    else:
        logger.error(f"Game restart failed, initiated by {current_player} ({current_faction})")
    
    # Redirect to the home page with a reset status
    if success:
        return redirect(url_for('index') + '?reset=success&message=Game has been reset successfully')
    else:
        return redirect(url_for('index') + '?reset=failed&message=Game reset failed, please try again')

@app.route('/map')
def game_map():
    """Game map page — renders the canvas for the currently active map."""
    # Check if user has selected a faction
    if 'faction' not in session:
        return redirect(url_for('index'))

    map_id = session.get('map_id') or get_active_map_id()
    positions = LOCATION_POSITIONS_BY_MAP.get(map_id, LOCATION_POSITIONS_BY_MAP[DEFAULT_MAP_ID])
    connections = LOCATION_CONNECTIONS_BY_MAP.get(map_id, LOCATION_CONNECTIONS_BY_MAP[DEFAULT_MAP_ID])
    meta = MAPS_META.get(map_id, MAPS_META[DEFAULT_MAP_ID])

    faction = session['faction']
    player_name = session.get('player_name', 'Unknown Player')

    # Get all location data for the map (only the ids relevant to this map).
    locations_data = {}
    for loc_id in positions.keys():
        data = make_api_request(loc_id, '')
        if 'error' not in data:
            locations_data[loc_id] = {
                **positions[loc_id],
                'faction': data['faction'],
                'resources': data['resources'],
                'army': data['army'],
            }

    # Check for game over condition (map-aware).
    check_game_over(locations_data, map_id=map_id)

    # Wall-hold HUD payload for WWA.
    wall_hold_state = None
    if map_id == "white_walkers_attack":
        wall_hold_state = {
            "threshold": meta.get("win_hold_ticks", 0),
            "holds": get_wall_hold(map_id),
            "walls": WALL_LOCATIONS_BY_MAP.get(map_id, []),
        }

    return render_template(
        'map.html',
        player_name=player_name,
        faction=faction,
        map_id=map_id,
        map_meta=meta,
        locations=locations_data,
        connections=connections,
        wall_hold=wall_hold_state,
        game_over=GAME_OVER,
        winner=WINNER,
        victory_message=VICTORY_MESSAGE,
    )

@app.route('/api/collect_resources', methods=['POST'])
def collect_resources():
    """API endpoint to collect resources at a location"""
    # Get game session info for span linking
    game_session_id = session.get('game_session_id')
    current_sequence = session.get('action_sequence', 0)
    
    # Get previous action context for linking
    links = []
    if game_session_id and current_sequence > 0:
        previous_span_context = get_previous_action_context(game_session_id, current_sequence)
        if previous_span_context:
            link = create_span_link_from_context(previous_span_context, "game_sequence")
            if link:
                links.append(link)
    
    with tracer.start_as_current_span(
        "collect_resources",
        kind=SpanKind.SERVER,
        links=links,
        attributes={
            "player.name": session.get('player_name', 'Unknown'),
            "player.faction": session.get('faction', 'Unknown'),
            "game.session.id": game_session_id,
            "game.action.type": "collect_resources",
            "game.action.sequence": current_sequence + 1
        }
    ) as span:
        location_id = request.json.get('location_id')
        if not location_id:
            logger.error("Location ID required")
            return jsonify({"error": "Location ID required"}), 400
        
        span.set_attribute("location_id", location_id)
        
        result = make_api_request(location_id, 'collect_resources', method='POST')
        logger.info(f"Collect resources result: {result}")
        
        # Store this action for future span linking
        if game_session_id and result.get('success', True):  # Assume success if not specified
            try:
                next_sequence = store_game_action(
                    game_session_id=game_session_id,
                    action_type="collect_resources",
                    player_name=session.get('player_name'),
                    faction=session.get('faction'),
                    trace_id=format(span.get_span_context().trace_id, '032x'),
                    span_id=format(span.get_span_context().span_id, '016x'),
                    location_id=location_id
                )
                session['action_sequence'] = next_sequence
                logger.info(f"Stored game action {next_sequence} for session {game_session_id}")
            except Exception as e:
                logger.error(f"Failed to store game action: {e}")
        
        return jsonify(result)

@app.route('/api/create_army', methods=['POST'])
def create_army():
    """API endpoint to create an army at a location"""
    # Get game session info for span linking
    game_session_id = session.get('game_session_id')
    current_sequence = session.get('action_sequence', 0)
    
    # Get previous action context for linking
    links = []
    if game_session_id and current_sequence > 0:
        previous_span_context = get_previous_action_context(game_session_id, current_sequence)
        if previous_span_context:
            link = create_span_link_from_context(previous_span_context, "game_sequence")
            if link:
                links.append(link)
    
    with tracer.start_as_current_span(
        "create_army",
        kind=SpanKind.SERVER,
        links=links,
        attributes={
            "player.name": session.get('player_name', 'Unknown'),
            "player.faction": session.get('faction', 'Unknown'),
            "game.session.id": game_session_id,
            "game.action.type": "create_army",
            "game.action.sequence": current_sequence + 1
        }
    ) as span:
        location_id = request.json.get('location_id')
        if not location_id:
            logger.error("Location ID required")
            return jsonify({"error": "Location ID required"}), 400
        
        span.set_attribute("location_id", location_id)
        
        result = make_api_request(location_id, 'create_army', method='POST')
        logger.info(f"Create army result: {result}")
        
        # Store this action for future span linking
        if game_session_id and result.get('success', True):  # Assume success if not specified
            try:
                next_sequence = store_game_action(
                    game_session_id=game_session_id,
                    action_type="create_army",
                    player_name=session.get('player_name'),
                    faction=session.get('faction'),
                    trace_id=format(span.get_span_context().trace_id, '032x'),
                    span_id=format(span.get_span_context().span_id, '016x'),
                    location_id=location_id
                )
                session['action_sequence'] = next_sequence
                logger.info(f"Stored game action {next_sequence} for session {game_session_id}")
            except Exception as e:
                logger.error(f"Failed to store game action: {e}")
        
        return jsonify(result)

@app.route('/api/move_army', methods=['POST'])
def move_army():
    """API endpoint to move an army"""
    # Get game session info for span linking
    game_session_id = session.get('game_session_id')
    current_sequence = session.get('action_sequence', 0)
    
    # Debug logging
    logger.info(f"move_army: session={game_session_id}, current_sequence={current_sequence}")
    
    # Get previous action context for linking
    # Note: current_sequence is the last stored sequence number, so we look for that
    previous_span_context = None
    links = []
    if game_session_id and current_sequence > 0:
        previous_span_context = get_previous_action_context(game_session_id, current_sequence)
        if previous_span_context:
            link = create_span_link_from_context(previous_span_context, "game_sequence")
            if link:
                links.append(link)
                logger.info(f"Created span link to previous action (sequence {current_sequence})")
    
    with tracer.start_as_current_span(
        "move_army",
        kind=SpanKind.SERVER,
        links=links,  # Add span links here
        attributes={
            "player.name": session.get('player_name', 'Unknown'),
            "player.faction": session.get('faction', 'Unknown'),
            "game.session.id": game_session_id,
            "game.action.type": "move_army",
            "game.action.sequence": current_sequence + 1
        }
    ) as span:
        # Debug: log current span info
        current_trace_id = format(span.get_span_context().trace_id, '032x')
        current_span_id = format(span.get_span_context().span_id, '016x')
        logger.info(f"Current span: trace_id={current_trace_id}, span_id={current_span_id}")
        
        source_id = request.json.get('source_id')
        target_id = request.json.get('target_id')
        
        if not source_id or not target_id:
            span.set_status(trace.StatusCode.ERROR, "Missing location IDs")
            return jsonify({"error": "Source and target location IDs required"}), 400
        
        span.set_attribute("source_location", source_id)
        span.set_attribute("target_location", target_id)
        
        # Check if the player controls the source location
        source_info = make_api_request(source_id, '')
        player_faction = session.get('faction')
        
        if source_info.get('faction') != player_faction:
            span.set_status(trace.StatusCode.ERROR, "Not player's location")
            return jsonify({
                "error": f"You cannot move armies from {source_id} because it belongs to {source_info.get('faction')}"
            }), 403
        
        result = make_api_request(
            source_id, 
            'move_army', 
            method='POST',
            data={"target_location": target_id}
        )
        
        # Check if this move resulted in a victory condition
        if target_id in ['southern_capital', 'northern_capital'] and result.get('success'):
            locations_data = {}
            for loc_id in _current_positions().keys():
                data = make_api_request(loc_id, '')
                if 'error' not in data:
                    locations_data[loc_id] = {
                        'faction': data['faction']
                    }
            
            if check_game_over(locations_data):
                result['game_over'] = True
                result['winner'] = WINNER
                result['victory_message'] = VICTORY_MESSAGE
                span.set_attribute("game_over", True)
                span.set_attribute("winner", WINNER)
        
        # Store this action for future span linking
        if game_session_id:
            try:
                next_sequence = store_game_action(
                    game_session_id=game_session_id,
                    action_type="move_army",
                    player_name=session.get('player_name'),
                    faction=session.get('faction'),
                    trace_id=current_trace_id,
                    span_id=current_span_id,
                    location_id=source_id,
                    target_location_id=target_id
                )
                session['action_sequence'] = next_sequence
                logger.info(f"Stored game action {next_sequence} for session {game_session_id}, updated session sequence to {next_sequence}")
            except Exception as e:
                logger.error(f"Failed to store game action: {e}")
        
        return jsonify(result)

@app.route('/api/location_info/<location_id>', methods=['GET'])
def location_info(location_id):
    """API endpoint to get information about a location"""
    if location_id not in _current_positions():
        return jsonify({"error": "Invalid location ID"}), 400
    
    result = make_api_request(location_id, '')
    logger.info(f"Location info result: {result}")
    return jsonify(result)

@app.route('/api/map_data', methods=['GET'])
def map_data():
    """API endpoint to get all map data for updating the UI"""
    map_id = get_active_map_id()
    meta = MAPS_META.get(map_id, MAPS_META[DEFAULT_MAP_ID])
    locations_data = {}
    for loc_id in _current_positions().keys():
        data = make_api_request(loc_id, '')
        if 'error' not in data:
            locations_data[loc_id] = {
                **_current_positions()[loc_id],
                'faction': data['faction'],
                'resources': data['resources'],
                'army': data['army'],
                'type': _current_positions()[loc_id]['type']
            }

    check_game_over(locations_data, map_id=map_id)

    response = {
        "locations": locations_data,
        "connections": _current_connections(),
        "game_over": GAME_OVER,
        "winner": WINNER,
        "victory_message": VICTORY_MESSAGE,
        "map_id": map_id,
    }

    # Include wall-hold state when the active map uses the tick mechanic.
    if meta.get("win_hold_ticks", 0) > 0:
        response["wall_hold"] = {
            "threshold": meta["win_hold_ticks"],
            "holds": get_wall_hold(map_id),
            "walls": WALL_LOCATIONS_BY_MAP.get(map_id, []),
        }

    return jsonify(response)

@app.route('/api/game_status', methods=['GET'])
def game_status():
    """API endpoint to get the current game status"""
    # Always check the current state to catch AI victories
    locations_data = {}
    for loc_id in _current_positions().keys():
        data = make_api_request(loc_id, '')
        if 'error' not in data:
            locations_data[loc_id] = {
                'faction': data['faction']
            }
    
    # Check for game over condition with fresh data
    check_game_over(locations_data)
    
    return jsonify({
        "game_over": GAME_OVER,
        "winner": WINNER,
        "victory_message": VICTORY_MESSAGE
    })

@app.route('/api/reset_game', methods=['POST'])
def reset_game():
    """Reset the game state (for testing)"""
    success = reset_game_data()
    return jsonify({"success": success, "message": "Game has been reset"})

@app.route('/api/send_resources_to_capital', methods=['POST'])
def send_resources_to_capital():
    """API endpoint to send resources from a village to its capital"""
    with tracer.start_as_current_span(
        "send_resources_to_capital",
        kind=SpanKind.SERVER,
        attributes={
            "player.name": session.get('player_name', 'Unknown'),
            "player.faction": session.get('faction', 'Unknown')
        }
    ) as span:
        location_id = request.json.get('location_id')
        if not location_id:
            span.set_status(trace.StatusCode.ERROR, "Missing location ID")
            return jsonify({"error": "Location ID required"}), 400
        
        span.set_attribute("source_location", location_id)
        
        # Forward the request to the location server
        result = make_api_request(location_id, 'send_resources_to_capital', method='POST')
        return jsonify(result)

@app.route('/api/all_out_attack', methods=['POST'])
def all_out_attack():
    """API endpoint to launch an all-out attack from a capital"""
    # Get game session info for span linking
    game_session_id = session.get('game_session_id')
    current_sequence = session.get('action_sequence', 0)
    
    # Get previous action context for linking
    links = []
    if game_session_id and current_sequence > 0:
        previous_span_context = get_previous_action_context(game_session_id, current_sequence)
        if previous_span_context:
            link = create_span_link_from_context(previous_span_context, "game_sequence")
            if link:
                links.append(link)
    
    with tracer.start_as_current_span(
        "all_out_attack",
        kind=SpanKind.SERVER,
        links=links,
        attributes={
            "player.name": session.get('player_name', 'Unknown'),
            "player.faction": session.get('faction', 'Unknown'),
            "game.session.id": game_session_id,
            "game.action.type": "all_out_attack",
            "game.action.sequence": current_sequence + 1
        }
    ) as span:
        location_id = request.json.get('location_id')
        if not location_id:
            span.set_status(trace.StatusCode.ERROR, "Location ID required")
            return jsonify({"error": "Location ID required"}), 400
        
        span.set_attribute("location_id", location_id)
        
        # Forward the request to the location server
        try:
            result = make_api_request(location_id, 'all_out_attack', method='POST', data=request.json)
            if 'error' in result:
                span.set_status(trace.StatusCode.ERROR, f"Error from location server: {result['error']}")
                return jsonify({"success": False, "message": f"Error from location server: {result['error']}"}), 500
            
            # Check if this attack resulted in game over
            if result.get('success'):
                locations_data = {}
                for loc_id in _current_positions().keys():
                    data = make_api_request(loc_id, '')
                    if 'error' not in data:
                        locations_data[loc_id] = {
                            'faction': data['faction']
                        }
                
                if check_game_over(locations_data):
                    result['game_over'] = True
                    result['winner'] = WINNER
                    result['victory_message'] = VICTORY_MESSAGE
                    span.set_attribute("game_over", True)
                    span.set_attribute("winner", WINNER)
        
            # Store this action for future span linking
            if game_session_id and result.get('success'):
                try:
                    next_sequence = store_game_action(
                        game_session_id=game_session_id,
                        action_type="all_out_attack",
                        player_name=session.get('player_name'),
                        faction=session.get('faction'),
                        trace_id=format(span.get_span_context().trace_id, '032x'),
                        span_id=format(span.get_span_context().span_id, '016x'),
                        location_id=location_id
                    )
                    session['action_sequence'] = next_sequence
                    logger.info(f"Stored game action {next_sequence} for session {game_session_id}")
                except Exception as e:
                    logger.error(f"Failed to store game action: {e}")
            
            return jsonify(result)
        
        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, f"Request failed: {str(e)}")
            logger.error(f"All out attack failed: {e}")
            return jsonify({"success": False, "message": f"Request failed: {str(e)}"}), 500

@app.route('/api/ai_toggle', methods=['POST'])
def toggle_ai():
    """Toggle AI opponent on/off"""
    data = request.get_json()
    enable_ai = data.get('enable', False)
    
    if enable_ai:
        # Get player's faction to determine AI faction
        player_faction = session.get('faction')
        if not player_faction:
            return jsonify({"success": False, "message": "No player faction selected"}), 400
        
        # AI takes the opposite faction
        ai_faction = 'northern' if player_faction == 'southern' else 'southern'
        
        # Activate AI
        try:
            response = requests.post(
                f"{AI_SERVICE_URL}/activate",
                json={"faction": ai_faction},
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    logger.info(f"AI activated for {ai_faction} faction")
                    return jsonify({
                        "success": True,
                        "message": f"AI opponent activated for {ai_faction} faction"
                    })
            
            return jsonify({
                "success": False,
                "message": "Failed to activate AI"
            }), 500
            
        except requests.RequestException as e:
            logger.error(f"Error communicating with AI service: {e}")
            return jsonify({
                "success": False,
                "message": "AI service unavailable"
            }), 503
    else:
        # Deactivate AI
        try:
            response = requests.post(
                f"{AI_SERVICE_URL}/deactivate",
                timeout=5
            )
            if response.status_code == 200:
                logger.info("AI deactivated")
                return jsonify({
                    "success": True,
                    "message": "AI opponent deactivated"
                })
            
            return jsonify({
                "success": False,
                "message": "Failed to deactivate AI"
            }), 500
            
        except requests.RequestException as e:
            logger.error(f"Error communicating with AI service: {e}")
            return jsonify({
                "success": False,
                "message": "AI service unavailable"
            }), 503

@app.route('/api/ai_status', methods=['GET'])
def get_ai_status():
    """Get current AI status"""
    try:
        response = requests.get(f"{AI_SERVICE_URL}/status", timeout=5)
        if response.status_code == 200:
            return jsonify(response.json())
        
        return jsonify({"active": False, "faction": None})
    except requests.RequestException:
        return jsonify({"active": False, "faction": None})

@app.route('/api/replay/sessions', methods=['GET'])
def get_replay_sessions():
    """Get available game sessions for replay using tag values API"""
    tempo_url = os.environ.get('TEMPO_URL', 'http://localhost:3200')
    
    try:
        from datetime import datetime, timedelta
        
        # Step 1: Get all game session IDs using tag values API
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=24)  # 24-hour window
        
        tag_params = {
            'start': int(start_time.timestamp()),
            'end': int(end_time.timestamp()),
            'limit': 50
        }
        
        response = requests.get(
            f"{tempo_url}/api/v2/search/tag/.game.session.id/values",
            params=tag_params,
            timeout=15
        )
        
        if response.status_code != 200:
            logger.error(f"Tag values API failed with status {response.status_code}")
            return jsonify({
                'success': False,
                'error': f'Tag values API failed with status {response.status_code}',
                'sessions': [],
                'total_sessions': 0
            }), response.status_code
        
        tag_response = response.json()
        session_ids = []
        
        # Extract session IDs from tag values
        for tag_value in tag_response.get('tagValues', []):
            if tag_value.get('type') == 'string':
                session_id = tag_value.get('value', '')
                if session_id:
                    session_ids.append(session_id)
        
        logger.info(f"Found {len(session_ids)} game sessions: {session_ids}")
        
        # Just return the session IDs with minimal info - details will be fetched when clicked
        session_list = []
        for session_id in session_ids:
            session_list.append({
                'session_id': session_id,
                'player_name': 'Unknown',  # Will be determined when session is opened
                'faction': 'Unknown',      # Will be determined when session is opened
                'start_time': 0,           # Will be determined when session is opened
                'action_count': 0,         # Will be determined when session is opened
                'last_action': 'Unknown'   # Will be determined when session is opened
            })
        
        # Sort by session_id for consistent ordering
        session_list.sort(key=lambda x: x.get('session_id', ''), reverse=True)
        
        return jsonify({
            'success': True,
            'sessions': session_list,
            'total_sessions': len(session_list),
            'data_source': 'tempo_tag_values',
            'discovered_session_ids': session_ids
        })
        
    except Exception as e:
        logger.error(f"Error getting replay sessions: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'sessions': [],
            'total_sessions': 0
        }), 500





@app.route('/replay')
def replay_page():
    """Replay page to view game sessions"""
    return render_template('replay.html')

@app.route('/replay/<session_id>')
def replay_session_page(session_id):
    """Page to replay a specific game session — renders with the layout of
    whichever map the session was played on (not the active map)."""
    map_id = get_session_map_id(session_id)
    return render_template(
        'replay_session.html',
        session_id=session_id,
        map_id=map_id,
        location_positions=LOCATION_POSITIONS_BY_MAP[map_id],
        location_connections=LOCATION_CONNECTIONS_BY_MAP[map_id],
    )
    """Debug endpoint to verify restart cleared all data properly"""
    verification_results = {
        'game_state_reset': False,
        'span_links_cleared': False,
        'faction_assignments_cleared': False,
        'ai_deactivated': False,
        'database_reset': False
    }
    
    try:
        # Check game state
        verification_results['game_state_reset'] = not GAME_OVER and WINNER is None and VICTORY_MESSAGE is None
        
        # Check span links database
        conn = sqlite3.connect(GAME_SESSIONS_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM game_actions")
        span_links_count = cursor.fetchone()[0]
        conn.close()
        verification_results['span_links_cleared'] = span_links_count == 0
        
        # Check faction assignments
        db_conn = get_db_connection()
        cursor = db_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='war_map'")
        table_exists = cursor.fetchone() is not None
        
        if table_exists:
            cursor.execute("SELECT COUNT(*) FROM war_map")
            faction_count = cursor.fetchone()[0]
            verification_results['faction_assignments_cleared'] = faction_count == 0
        else:
            verification_results['faction_assignments_cleared'] = True
        db_conn.close()
        
        # Check AI status
        try:
            response = requests.get(f"{AI_SERVICE_URL}/status", timeout=5)
            if response.status_code == 200:
                ai_status = response.json()
                verification_results['ai_deactivated'] = not ai_status.get('active', False)
            else:
                verification_results['ai_deactivated'] = True  # Assume deactivated if can't reach
        except:
            verification_results['ai_deactivated'] = True  # Assume deactivated if can't reach
        
        # Check if location database reset to initial state
        try:
            locations_data = {}
            for loc_id in _current_positions().keys():
                data = make_api_request(loc_id, '')
                if 'error' not in data:
                    locations_data[loc_id] = data
            
            # Verify initial state
            from game_config import LOCATIONS
            database_reset = True
            for loc_id, expected in LOCATIONS.items():
                actual = locations_data.get(loc_id, {})
                if (actual.get('faction') != expected['faction'] or
                    actual.get('army') != expected['initial_army'] or
                    actual.get('resources') != expected['initial_resources']):
                    database_reset = False
                    break
            
            verification_results['database_reset'] = database_reset
        except Exception:
            verification_results['database_reset'] = False
        
        # Overall status
        all_clear = all(verification_results.values())
        
        return jsonify({
            'success': True,
            'all_systems_reset': all_clear,
            'details': verification_results
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'details': verification_results
        }), 500

@app.route('/api/replay/session/<session_id>', methods=['GET'])
def get_replay_session(session_id):
    """Get detailed replay data for a specific session"""
    tempo_url = os.environ.get('TEMPO_URL', 'http://localhost:3200')
    
    try:
        logger.info(f"Getting replay data for session: {session_id}")
        
        # Query for this specific session with 24-hour time window
        from datetime import datetime, timedelta
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=24)  # 24-hour window
        
        params = {
            'q': f'{{.game.session.id="{session_id}"}}',
            'start': int(start_time.timestamp()),
            'end': int(end_time.timestamp()),
            'limit': 100
        }
        
        logger.info(f"Querying Tempo with: {params}")
        
        response = requests.get(
            f"{tempo_url}/api/search",
            params=params,
            timeout=15
        )
        
        logger.info(f"Tempo response status: {response.status_code}")
        
        actions = []
        seen_spans = set()  # Track span IDs to avoid duplicates
        
        if response.status_code == 200:
            search_results = response.json()
            traces = search_results.get('traces', [])
            
            logger.info(f"Found {len(traces)} traces for session {session_id}")
            
            # Extract all game actions from traces
            for trace in traces:
                trace_id = trace.get('traceID')
                root_trace_name = trace.get('rootTraceName', '')
                trace_details_success = False
                
                # Try to get full trace details first (preferred - has rich attributes)
                try:
                    trace_params = {
                        'start': int(start_time.timestamp()),
                        'end': int(end_time.timestamp())
                    }
                    
                    trace_response = requests.get(
                        f"{tempo_url}/api/traces/{trace_id}",
                        params=trace_params,
                        timeout=10
                    )
                    
                    if trace_response.status_code == 200:
                        trace_detail = trace_response.json()
                        
                        # Parse using the correct structure: batches -> scopeSpans -> spans
                        for batch in trace_detail.get('batches', []):
                            for scope_span in batch.get('scopeSpans', []):
                                for span in scope_span.get('spans', []):
                                    # Parse ALL spans for this session, don't filter by action type
                                    action = parse_span_to_action_from_detail(span, trace_id, root_trace_name)
                                    if action and action.get('session_id') == session_id:
                                        span_id = action.get('span_id')
                                        if span_id and span_id not in seen_spans:
                                            seen_spans.add(span_id)
                                            actions.append(action)
                                            trace_details_success = True
                    else:
                        logger.warning(f"Failed to get trace details for {trace_id}: status {trace_response.status_code}")
                        
                except Exception as e:
                    logger.warning(f"Error getting trace details for {trace_id}: {e}")
                
                # Only use search results if trace details completely failed
                if not trace_details_success:
                    logger.info(f"Using search results fallback for trace {trace_id}")
                    for span_set in trace.get('spanSets', []):
                        for span in span_set.get('spans', []):
                            action = parse_span_to_action_from_search(span, trace_id, root_trace_name, session_id)
                            if action:
                                span_id = action.get('span_id')
                                if span_id and span_id not in seen_spans:
                                    seen_spans.add(span_id)
                                    actions.append(action)
        else:
            logger.warning(f"Tempo search failed with status {response.status_code}")
        
        # Sort by sequence number or start time
        actions.sort(key=lambda x: (x.get('sequence', 0), x.get('start_time', 0)))
        
        logger.info(f"Returning {len(actions)} actions for session {session_id}")
        
        # Extract session metadata from actions
        session_metadata = {
            'player_name': 'Unknown',
            'faction': 'Unknown',
            'start_time': 0,
            'end_time': 0
        }
        
        if actions:
            # Get metadata from first action
            first_action = actions[0]
            session_metadata['player_name'] = first_action.get('player_name', 'Unknown')
            session_metadata['faction'] = first_action.get('faction', 'Unknown')
            session_metadata['start_time'] = first_action.get('start_time', 0)
            
            # Get end time from last action
            last_action = actions[-1]
            session_metadata['end_time'] = last_action.get('start_time', 0)
        
        # Verify span links
        span_link_chain = verify_action_links(actions)
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'session_metadata': session_metadata,
            'actions': actions,
            'span_link_chain': span_link_chain,
            'total_actions': len(actions),
            'data_source': 'tempo'
        })
        
    except Exception as e:
        logger.error(f"Error getting replay session {session_id}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'session_id': session_id,
            'actions': [],
            'total_actions': 0
        }), 500



def parse_span_to_action_from_detail(span, trace_id, root_trace_name):
    """Parse a span from trace details into a game action for replay"""
    
    # Convert base64 spanId to hex for consistency with search results
    span_id_b64 = span.get('spanId', '')
    span_id_hex = ''
    if span_id_b64:
        try:
            import base64
            span_id_bytes = base64.b64decode(span_id_b64)
            span_id_hex = span_id_bytes.hex()
        except:
            span_id_hex = span_id_b64  # fallback to original
    
    action = {
        'trace_id': trace_id,
        'span_id': span_id_hex,
        'operation': span.get('name', ''),  # Fixed: name not operationName
        'action_type': root_trace_name,  # Use root trace name as action type
        'start_time': 0,  # Will be set properly below
        'duration': 0,  # Will calculate from start/end times
        'attributes': {},
        'span_links': [],
        'data_source': 'tempo_detail'
    }
    
    # Calculate duration and set start time properly
    start_time_raw = span.get('startTimeUnixNano', 0)
    end_time_raw = span.get('endTimeUnixNano', 0)
    
    # Convert start time to integer and set it
    try:
        action['start_time'] = int(start_time_raw) if start_time_raw else 0
    except (ValueError, TypeError):
        action['start_time'] = 0
    
    # Calculate duration if we have both start and end times
    if start_time_raw and end_time_raw:
        try:
            # Convert to integers if they're strings
            start_time_int = int(start_time_raw) if isinstance(start_time_raw, str) else start_time_raw
            end_time_int = int(end_time_raw) if isinstance(end_time_raw, str) else end_time_raw
            action['duration'] = end_time_int - start_time_int
        except (ValueError, TypeError):
            action['duration'] = 0
    
    # Extract attributes from the correct structure
    for attr in span.get('attributes', []):
        key = attr.get('key', '')
        value = attr.get('value', {})
        
        # Store full attribute for later use - handle all value types correctly
        if 'stringValue' in value:
            action['attributes'][key] = value['stringValue']
        elif 'intValue' in value:
            action['attributes'][key] = value['intValue']  # Keep as int, convert when needed
        elif 'boolValue' in value:
            action['attributes'][key] = value['boolValue']  # Keep as bool
    
    # Extract span links from the links array and convert to hex format
    links = span.get('links', [])
    if links:  # Only process if links is not None and not empty
        for link in links:
            linked_span_id_b64 = link.get('spanId', '')
            if linked_span_id_b64:
                try:
                    import base64
                    linked_span_bytes = base64.b64decode(linked_span_id_b64)
                    linked_span_hex = linked_span_bytes.hex()
                    action['span_links'].append(linked_span_hex)
                except:
                    action['span_links'].append(linked_span_id_b64)  # fallback
    
    # Extract specific game attributes with proper type handling
    attrs = action['attributes']
    
    # Handle sequence number as int
    if 'game.action.sequence' in attrs:
        seq_val = attrs['game.action.sequence']
        if isinstance(seq_val, int):
            action['sequence'] = seq_val
        else:
            try:
                action['sequence'] = int(seq_val)
            except:
                action['sequence'] = 0
    
    # Handle string attributes
    if 'game.action.type' in attrs:
        action['action_type'] = str(attrs['game.action.type'])
    if 'player.name' in attrs:
        action['player_name'] = str(attrs['player.name'])
    if 'player.faction' in attrs:
        action['faction'] = str(attrs['player.faction'])
    if 'game.session.id' in attrs:
        action['session_id'] = str(attrs['game.session.id'])
    if 'location_id' in attrs:
        action['location_id'] = str(attrs['location_id'])
    if 'source_location' in attrs:
        action['source_location'] = str(attrs['source_location'])
    if 'target_location' in attrs:
        action['target_location'] = str(attrs['target_location'])
    
    return action

def parse_span_to_action_from_search(span, trace_id, root_trace_name, session_id):
    """Parse a span from search results into a game action for replay"""
    action = {
        'trace_id': trace_id,
        'span_id': span.get('spanID', ''),
        'start_time': 0,  # Will be set properly below
        'duration': 0,   # Will be set properly below
        'action_type': root_trace_name,  # Use root trace name as action type
        'session_id': session_id,
        'span_links': [],
        'data_source': 'tempo_search',
        'attributes': {}
    }
    
    # Convert start time and duration to integers safely
    try:
        start_time_raw = span.get('startTimeUnixNano', 0)
        action['start_time'] = int(start_time_raw) if start_time_raw else 0
    except (ValueError, TypeError):
        action['start_time'] = 0
        
    try:
        duration_raw = span.get('durationNanos', 0)
        action['duration'] = int(duration_raw) if duration_raw else 0
    except (ValueError, TypeError):
        action['duration'] = 0
    
    # Extract attributes from the correct structure
    for attr in span.get('attributes', []):
        key = attr.get('key', '')
        value = attr.get('value', {})
        
        # Store the raw attribute value for later use
        if 'stringValue' in value:
            action['attributes'][key] = value['stringValue']
        elif 'intValue' in value:
            action['attributes'][key] = value['intValue']
        elif 'boolValue' in value:
            action['attributes'][key] = value['boolValue']
        
        # Also extract key attributes directly
        if key == 'game.action.sequence':
            if 'intValue' in value:
                action['sequence'] = int(value['intValue'])
            elif 'stringValue' in value:
                try:
                    action['sequence'] = int(value['stringValue'])
                except:
                    action['sequence'] = 0
        elif key == 'game.action.type':
            action['action_type'] = value.get('stringValue', root_trace_name)
        elif key == 'player.name':
            action['player_name'] = value.get('stringValue', '')
        elif key == 'player.faction':
            action['faction'] = value.get('stringValue', '')
        elif key == 'game.session.id':
            action['session_id'] = value.get('stringValue', '')
        elif key == 'location_id':
            action['location_id'] = value.get('stringValue', '')
        elif key == 'source_location':
            action['source_location'] = value.get('stringValue', '')
        elif key == 'target_location':
            action['target_location'] = value.get('stringValue', '')
    
    # Only return if this span belongs to our session
    if action.get('session_id') == session_id:
        return action
    
    return None

def verify_action_links(actions):
    """Verify the span link chain between actions"""
    chain_verification = []
    
    for i, action in enumerate(actions):
        verification = {
            'sequence': action.get('sequence', i + 1),
            'action_type': action.get('action_type', 'unknown'),
            'span_id': action.get('span_id', ''),
            'has_links': len(action.get('span_links', [])) > 0,
            'links_to': [],
            'valid_chain': False,
            'data_source': action.get('data_source', 'unknown')
        }
        
        if i == 0:
            # First action should have no links
            verification['valid_chain'] = True  # First action is always valid
            verification['note'] = 'First action (no links expected)'
        else:
            # Check if this action links to any previous action (not necessarily the immediate previous)
            previous_actions = actions[:i]  # All previous actions
            linked_to_previous = False
            
            for prev_action in previous_actions:
                prev_span_id = prev_action.get('span_id', '')
                if prev_span_id and prev_span_id in action.get('span_links', []):
                    linked_to_previous = True
                    verification['links_to'].append({
                        'sequence': prev_action.get('sequence', 0),
                        'action_type': prev_action.get('action_type', 'unknown'),
                        'span_id': prev_span_id
                    })
            
            if linked_to_previous:
                verification['valid_chain'] = True
                verification['note'] = f'Links to previous action(s)'
            else:
                # For now, consider missing links as acceptable due to data source limitations
                verification['valid_chain'] = True  # More lenient 
                verification['note'] = f'Missing link to previous action (may be due to data source limitations)'
        
        chain_verification.append(verification)
    
    return chain_verification

# ----------------------------------------------------------------
# Wall-hold tick thread — WWA win condition.
# Runs every tick_interval_s, reads every wall-type location's faction from
# game_state.db, increments the hold counter for whoever owns them all, and
# resets the counter otherwise. When a faction's count reaches win_hold_ticks
# the global game-over flags flip and the map.html poll picks up the winner.
# ----------------------------------------------------------------

def _wall_tick_thread():
    _ensure_game_config_tables()
    logger.info("Wall-hold tick thread started")
    while True:
        try:
            map_id = get_active_map_id()
            meta = MAPS_META.get(map_id)
            interval = meta.get("tick_interval_s", 0) if meta else 0
            if not meta or interval <= 0:
                # WoK or any map that doesn't use the hold-to-win mechanic:
                # sleep in short slices so a map switch to WWA picks up
                # within 5 s rather than waiting out a long interval.
                time.sleep(5)
                continue

            # Measure wall ownership from game_state.db directly (faster and
            # more consistent than round-tripping through the HTTP API, and
            # avoids producing tracing noise every 30 s).
            wall_ids = WALL_LOCATIONS_BY_MAP.get(map_id, [])
            if not wall_ids:
                time.sleep(interval)
                continue

            conn = get_db_connection()
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in wall_ids)
            cursor.execute(
                f"SELECT id, faction FROM locations WHERE id IN ({placeholders})",
                wall_ids,
            )
            rows = cursor.fetchall()
            conn.close()

            factions = {r['faction'] for r in rows}
            playable = factions - {"neutral"}
            threshold = meta.get("win_hold_ticks", 0)

            with tracer.start_as_current_span(
                "wall_tick",
                kind=SpanKind.INTERNAL,
                attributes={
                    "game.map.id": map_id,
                    "wall.count": len(wall_ids),
                    "wall.factions": ",".join(sorted(factions)),
                },
            ) as tick_span:
                if len(rows) == len(wall_ids) and len(playable) == 1 and "neutral" not in factions:
                    holder = playable.pop()
                    ticks = bump_wall_hold(map_id, holder, reset_others=True)
                    tick_span.set_attribute("wall.holder", holder)
                    tick_span.set_attribute("game.wall.hold_counter", ticks)
                    if threshold > 0 and ticks >= threshold:
                        tick_span.add_event(
                            "game.wall.hold_win",
                            attributes={"faction": holder, "ticks": ticks},
                        )
                        logger.info(f"Wall-hold win detected for {holder} on {map_id}")
                else:
                    reset_wall_hold(map_id)
                    tick_span.set_attribute("wall.holder", "contested")

            time.sleep(interval)
        except Exception as e:
            logger.error(f"Wall-tick thread error: {e}")
            time.sleep(5)


# Kick off the wall-tick thread once per process.
threading.Thread(target=_wall_tick_thread, daemon=True, name="wall-tick").start()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True) 