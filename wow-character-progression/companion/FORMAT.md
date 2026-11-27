# Alloy Route v2 recording format

The addon saves one string per character in `AlloyRouteRecording`, in the client's per-character SavedVariables file:

```text
WTF/Account/<account>/<realm>/<character>/SavedVariables/AlloyRoute.lua
```

The string holds one or more **sessions**. Each session is a header row, its data rows and a footer row. Rows are separated by `;` and fields by `|`. Text fields are UTF-8, percent-encoded except for `A-Z a-z 0-9 _ . -`, so the string never contains quotes, backslashes or delimiters. Numbers are base-10 integers. **An empty field means the value was unavailable or restricted in game.** A real zero is written as `0`.

[`fixtures/undead_warrior.lua`](fixtures/undead_warrior.lua) and [`fixtures/night_elf_druid.lua`](fixtures/night_elf_druid.lua) are complete examples. The matching `.jsonl` files show what `read_recording.py` emits for them. Both were written by the real addon running in `tests/harness.lua`. The characters, realms and GUIDs are synthetic.

## Session header

```text
v2|session_id|started|client_build|region|realm|character|player_guid|race|race_id|class|class_id|faction
```

| Field | Example | Notes |
| --- | --- | --- |
| `session_id` | `6ab13b80d716` | Hex server time, then four random hex digits |
| `started` | `1790000000` | `GetServerTime()`, Unix seconds |
| `client_build` | `1.60.1.71139` | `GetBuildInfo()` version and build |
| `region` | `eu` | `us`, `eu`, `kr`, `tw` or `cn` |
| `realm` | `Stonewake` | `GetNormalizedRealmName()` |
| `character`, `player_guid` | `Morrow`, `Player-1001-0A1B2C3D` | The GUID is unique across realms |
| `race`, `race_id` | `Scourge`, `5` | Locale-independent file token from `UnitRace` |
| `class`, `class_id` | `WARRIOR`, `1` | From `UnitClass` |
| `faction` | `Horde` | From `UnitFactionGroup` |

## Data rows

Every data row starts with `type|time|seq`. `time` is `GetServerTime()` in Unix seconds. `seq` starts at 1 in each session and increases by one per row, which orders rows that share a second.

| Type | Fields after `type\|time\|seq` | Written |
| --- | --- | --- |
| `s` snapshot | `level\|xp\|xp_max\|health\|health_max\|power_type_id\|power_type\|power\|power_max\|money_copper\|map_id\|zone\|x\|y` | At start, every 10 s when any value changed, after zone and level changes, at Save & Reload and `stop`, and at logout when a value changed |
| `b` starting gear | `slot\|item_id\|item_name` | Once for each of the 19 equipment slots at session start |
| `c` gear swap | `slot\|previous_item_id\|previous_item_name\|item_id\|item_name` | On a changed equipment slot, including removal |
| `a` armour | `armor` | Effective character-sheet armour at session boundaries and on observed changes |
| `z` zone change | `map_id\|zone` | When the map ID or zone text changes, followed by a snapshot. Kept when coordinates are unavailable, for example in an instance |
| `l` level up | `level` | On `PLAYER_LEVEL_UP`, followed by a snapshot using the event's level and a second snapshot 2 s later |
| `n` interaction | `interaction\|npc_unit_type\|npc_id\|npc_name` | Once per NPC window. `interaction` is the `Enum.PlayerInteractionType` name, such as `Gossip`, `QuestGiver`, `Merchant` or `Trainer` |
| `q` quest | `action\|quest_id\|quest_title\|reward_xp\|reward_copper\|npc_unit_type\|npc_id\|npc_name` | `action` is `accepted` or `turned_in`. Rewards come from `QUEST_TURNED_IN` and stay separate from measured XP and money |

Addon 2.1 adds these three row types to v2. Item ID 0 means Empty. An unreadable slot is marked Unavailable with no ID. A readable ID without a cached name appears as `Item #<id>`. A restricted armour value produces no armour row. A change in buffs can affect armour without a gear swap.

Snapshot units:

- `power_type_id` and `power_type` are read on every snapshot from `UnitPowerType`, so a form change from `MANA` to `ENERGY` or `RAGE` shows up immediately.
- `money_copper` is `GetMoney()`.
- `map_id` is `C_Map.GetBestMapForUnit("player")`. `x` and `y` are map-local positions from `0` to `10000`, in hundredths of a map percent, the same scale as v1.
- Health is often secret during combat on this client. It is then left empty, not written as zero.

`npc_unit_type` and `npc_id` come from the NPC's GUID, for example `Creature` and `1570`. The interaction rows are deduplicated: `PLAYER_INTERACTION_MANAGER_FRAME_SHOW`, `GOSSIP_SHOW` and the quest-frame events for one opening produce a single row. Repeated `QUEST_ACCEPTED` or `QUEST_TURNED_IN` events for the same quest within 10 s are dropped.

## Session footer

```text
e|ended|rows
```

`rows` counts the session's data rows. The footer is written by `PLAYER_LOGOUT`, which fires on Save & Reload, `/reload` and a normal logout, and by `/alloyroute stop`. The client writes SavedVariables only after `PLAYER_LOGOUT`. A crash or force-quit leaves the previous save unchanged.

## Limits

The whole string holds at most 4,096 data rows and 1,000,000 bytes. Before appending a row the addon checks that the row and a 32-byte footer reserve still fit, so a full recording always ends with a valid footer. The panel reminds you once at 500 rows or 100 kB, warns at 80% and stops recording when full. A three-hour session with constant movement is about 1,080 rows and 92 kB.

`/alloyroute start` on a character that already has a saved recording appends a new session; it never overwrites one. `/alloyroute clear` asks for `/alloyroute clear confirm` before deleting.

## Reader output

`read_recording.py` emits one JSON object per line: a `session` object for each session, then the events in order. Every event repeats `session_id`, `region`, `realm`, `character` and `player_guid`. Each object has `time` (UTC, ISO 8601), `ts` (Unix seconds) and `ts_ns`, a nanosecond timestamp that adds `seq` so Loki keeps rows in recorded order. Event types are `snapshot`, `zone_change`, `level_up`, `interaction`, `quest_accepted`, `quest_turned_in`, `gear_start`, `gear_swap` and `armor`. Empty fields are omitted.

The reader refuses the whole file, writes nothing to stdout or the output path, and exits with status 2 when:

- The Lua is malformed or cut short.
- A session has no footer.
- The footer's row count doesn't match.
- A row is missing or out of order.
- A field is malformed.
- The file holds a v1 route.

Import a v1 route from the tracker's **My map routes** page.
