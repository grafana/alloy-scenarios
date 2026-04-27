"""Game configuration for all maps in the game-of-tracing scenario.

Each entry in ``MAPS`` describes a playable map. A map has:

- ``display_name`` / ``description`` — surfaced by the map picker UI.
- ``single_player`` + ``player_faction`` / ``ai_faction`` — the map picker uses
  these to skip faction selection and auto-activate the AI when appropriate.
- ``factions`` — the valid faction strings for this map.
- ``slot_assignments`` — maps the fixed container slot ids (``slot_1`` …
  ``slot_8``) to the logical location id that slot serves on this map. The 8
  location containers carry only their ``SLOT_ID`` — their in-game identity
  is resolved at boot (and on ``/reload``) via this table.
- ``locations`` — per-location config (name, type, faction, connections,
  initial resources/army, port).
- ``rules`` — map-wide game rules (army costs and currency per faction, wall
  multiplier, tick interval, hold-to-win ticks, passive growth intervals).

The active map id is stored at runtime in the shared ``game_state.db`` in the
``game_config`` key-value table (written by ``war_map`` on ``/select_map``).
Both ``location_server`` and ``war_map`` read it to resolve per-service state.
"""

from __future__ import annotations

DATABASE_FILE = "game_state.db"
DEFAULT_MAP_ID = "war_of_kingdoms"

# Each of the 8 location containers has a fixed SLOT_ID env var
# (slot_1 .. slot_8). Its in-game identity is resolved through the active
# map's slot_assignments table, so the same container can serve "village_1" on
# War of Kingdoms and "wall_west" on White Walkers Attack.
SLOT_IDS = tuple(f"slot_{i}" for i in range(1, 9))


MAPS = {
    "war_of_kingdoms": {
        "display_name": "War of Kingdoms",
        "description": (
            "Northern and Southern kingdoms clash for dominance. "
            "Capture the enemy capital to win."
        ),
        "single_player": False,
        "factions": ["northern", "southern"],
        "slot_assignments": {
            "slot_1": "southern_capital",
            "slot_2": "northern_capital",
            "slot_3": "village_1",
            "slot_4": "village_2",
            "slot_5": "village_3",
            "slot_6": "village_4",
            "slot_7": "village_5",
            "slot_8": "village_6",
        },
        "locations": {
            "southern_capital": {
                "name": "Southern Capital",
                "type": "capital",
                "faction": "southern",
                "connections": ["village_1", "village_3"],
                "initial_resources": 100,
                "initial_army": 1,
                "port": 5001,
            },
            "northern_capital": {
                "name": "Northern Capital",
                "type": "capital",
                "faction": "northern",
                "connections": ["village_2", "village_6"],
                "initial_resources": 100,
                "initial_army": 1,
                "port": 5002,
            },
            "village_1": {
                "name": "Village 1",
                "type": "village",
                "faction": "neutral",
                "connections": ["southern_capital", "village_2", "village_4"],
                "initial_resources": 50,
                "initial_army": 2,
                "port": 5003,
            },
            "village_2": {
                "name": "Village 2",
                "type": "village",
                "faction": "neutral",
                "connections": ["northern_capital", "village_1", "village_5"],
                "initial_resources": 50,
                "initial_army": 3,
                "port": 5004,
            },
            "village_3": {
                "name": "Village 3",
                "type": "village",
                "faction": "neutral",
                "connections": ["southern_capital", "village_5", "village_6"],
                "initial_resources": 50,
                "initial_army": 2,
                "port": 5005,
            },
            "village_4": {
                "name": "Village 4",
                "type": "village",
                "faction": "neutral",
                "connections": ["village_1", "village_5"],
                "initial_resources": 50,
                "initial_army": 1,
                "port": 5006,
            },
            "village_5": {
                "name": "Village 5",
                "type": "village",
                "faction": "neutral",
                "connections": ["village_2", "village_3", "village_4", "village_6"],
                "initial_resources": 50,
                "initial_army": 4,
                "port": 5007,
            },
            "village_6": {
                "name": "Village 6",
                "type": "village",
                "faction": "neutral",
                "connections": ["northern_capital", "village_3", "village_5"],
                "initial_resources": 50,
                "initial_army": 2,
                "port": 5008,
            },
        },
        "rules": {
            "resource_generation": {"capital": 20, "village": 10},
            "army_cost": {"default": 30},
            "army_currency": {"default": "resources"},
            "wall_multiplier": 1.0,
            "barbarian_army_growth_interval_s": 0,
            "white_walker_passive_corpse_interval_s": 0,
            "tick_interval_s": 0,
            "win_hold_ticks": 0,
        },
    },
    "white_walkers_attack": {
        "display_name": "White Walkers Attack",
        "description": (
            "The Long Night has come. As the Night's Watch, hold every Wall "
            "keep for 5 ticks (150 s) before the White Walkers do. Single-player."
        ),
        "single_player": True,
        "player_faction": "nights_watch",
        "ai_faction": "white_walkers",
        "factions": ["nights_watch", "white_walkers", "barbarian"],
        "slot_assignments": {
            "slot_1": "nights_watch_fortress",
            "slot_2": "white_walker_fortress",
            "slot_3": "wall_west",
            "slot_4": "wall_center_west",
            "slot_5": "wall_center_east",
            "slot_6": "wall_east",
            "slot_7": "barbarian_village_west",
            "slot_8": "barbarian_village_east",
        },
        "locations": {
            "nights_watch_fortress": {
                "name": "Castle Black",
                "type": "capital",
                "faction": "nights_watch",
                "connections": [
                    "wall_west",
                    "wall_center_west",
                    "wall_center_east",
                    "wall_east",
                ],
                "initial_resources": 150,
                "initial_army": 3,
                "port": 5001,
            },
            "white_walker_fortress": {
                "name": "The Lands of Always Winter",
                "type": "capital",
                "faction": "white_walkers",
                "connections": [
                    "wall_west",
                    "wall_center_west",
                    "wall_center_east",
                    "wall_east",
                ],
                # White Walkers spend corpses, not resources. Keep the column
                # populated so the DB row shape stays uniform; the create_army
                # handler reads currency from the map rules.
                "initial_resources": 0,
                "initial_army": 2,
                "port": 5002,
            },
            "wall_west": {
                "name": "Westwatch",
                "type": "wall",
                "faction": "neutral",
                "connections": [
                    "nights_watch_fortress",
                    "white_walker_fortress",
                    "wall_center_west",
                    "barbarian_village_west",
                ],
                "initial_resources": 0,
                "initial_army": 1,
                "port": 5003,
            },
            "wall_center_west": {
                "name": "Queensgate",
                "type": "wall",
                "faction": "neutral",
                "connections": [
                    "nights_watch_fortress",
                    "white_walker_fortress",
                    "wall_west",
                    "wall_center_east",
                ],
                "initial_resources": 0,
                "initial_army": 1,
                "port": 5004,
            },
            "wall_center_east": {
                "name": "Deep Lake",
                "type": "wall",
                "faction": "neutral",
                "connections": [
                    "nights_watch_fortress",
                    "white_walker_fortress",
                    "wall_center_west",
                    "wall_east",
                ],
                "initial_resources": 0,
                "initial_army": 1,
                "port": 5005,
            },
            "wall_east": {
                "name": "Eastwatch-by-the-Sea",
                "type": "wall",
                "faction": "neutral",
                "connections": [
                    "nights_watch_fortress",
                    "white_walker_fortress",
                    "wall_center_east",
                    "barbarian_village_east",
                ],
                "initial_resources": 0,
                "initial_army": 1,
                "port": 5006,
            },
            "barbarian_village_west": {
                "name": "Free Folk Camp (West)",
                "type": "village",
                "faction": "barbarian",
                "connections": ["wall_west"],
                "initial_resources": 0,
                "initial_army": 2,
                "port": 5007,
            },
            "barbarian_village_east": {
                "name": "Free Folk Camp (East)",
                "type": "village",
                "faction": "barbarian",
                "connections": ["wall_east"],
                "initial_resources": 0,
                "initial_army": 2,
                "port": 5008,
            },
        },
        "rules": {
            # Night's Watch capital collects resources on the classic schedule.
            # White Walker fortress ignores resource_generation (uses corpses).
            "resource_generation": {"capital": 20, "village": 10},
            "army_cost": {
                "default": 30,
                "white_walkers": 5,
            },
            "army_currency": {
                "default": "resources",
                "white_walkers": "corpses",
            },
            "wall_multiplier": 2.0,
            "barbarian_army_growth_interval_s": 30,
            "white_walker_passive_corpse_interval_s": 15,
            # WWA gives the Night's Watch no friendly villages, so its only
            # income source is /collect_resources at Castle Black. Add a slow
            # passive trickle so the resource HUD ticks up without click-spam.
            # Keep it well below the click rate (+20 per 5 s) — passive should
            # supplement, not replace, active play.
            "nights_watch_capital_passive_amount": 5,
            "nights_watch_capital_passive_interval_s": 10,
            "tick_interval_s": 30,
            "win_hold_ticks": 5,
        },
    },
}

# Backward-compat exports: unchanged shape for callers that don't know about
# maps yet. These always reflect the War of Kingdoms defaults.
LOCATIONS = MAPS[DEFAULT_MAP_ID]["locations"]
RESOURCE_GENERATION = MAPS[DEFAULT_MAP_ID]["rules"]["resource_generation"]
COSTS = {"create_army": MAPS[DEFAULT_MAP_ID]["rules"]["army_cost"]["default"]}


def get_map(map_id):
    """Return the full map-config dict for ``map_id``."""
    if map_id not in MAPS:
        raise KeyError(f"Unknown map_id: {map_id}")
    return MAPS[map_id]


def resolve_slot(map_id, slot_id):
    """Return the location_id the given slot serves on the given map."""
    return MAPS[map_id]["slot_assignments"][slot_id]


def get_location_config(map_id, location_id):
    """Return the per-location config dict for (map_id, location_id)."""
    return MAPS[map_id]["locations"][location_id]


def get_rules(map_id):
    """Return the ``rules`` dict for ``map_id``."""
    return MAPS[map_id]["rules"]


def get_army_cost(map_id, faction):
    """Return the army-creation cost for ``faction`` on ``map_id``."""
    costs = MAPS[map_id]["rules"]["army_cost"]
    return costs.get(faction, costs["default"])


def get_army_currency(map_id, faction):
    """Return ``"resources"`` or ``"corpses"`` for ``faction`` on ``map_id``."""
    currencies = MAPS[map_id]["rules"]["army_currency"]
    return currencies.get(faction, currencies["default"])


def locations_by_type(map_id, type_name):
    """Return the list of location_ids on ``map_id`` of the given ``type_name``."""
    return [
        lid
        for lid, cfg in MAPS[map_id]["locations"].items()
        if cfg["type"] == type_name
    ]
