# app/ — Location Servers

> 8 Flask microservices representing map territories in the *War of Kingdoms* game. This doc is read by any AI coding agent (Claude, Cursor, Codex, Cline). For scenario-wide context read [`../AGENTS.md`](../AGENTS.md) first.

## Purpose

All 8 locations run the same codebase. A container's **slot** (set via `SLOT_ID` env var, `slot_1` … `slot_8`) is fixed at build time; the **logical identity** it serves (`southern_capital`, `wall_west`, `barbarian_village_east`, …) is resolved at boot and on `/reload` from the active map in `game_state.db`. Each location:

- Owns a row in the shared `game_state.db` (resources, army, faction).
- Exposes an HTTP API for collecting resources, creating armies, moving armies, and launching attacks.
- Instruments every route with OpenTelemetry traces, logs, and five custom game metrics.
- Runs passive resource generation for villages (every 15 s) and handles cooldowns for capitals.
- On the White Walkers Attack map, also runs: passive barbarian army growth (every 30 s at barbarian villages), passive corpse generation (every 15 s at the White Walker fortress), passive resource generation at the Night's Watch capital (+5 every 10 s — WWA has no friendly villages, so this replaces the click-only economy), and the wall multiplier (defenders count 2× at `wall`-type locations).

Ports 5001-5008:

| Location ID | Service name | Port | Type |
|---|---|---|---|
| `southern_capital` | `southern-capital` | 5001 | capital |
| `northern_capital` | `northern-capital` | 5002 | capital |
| `village_1` | `village-1` | 5003 | village |
| `village_2` | `village-2` | 5004 | village |
| `village_3` | `village-3` | 5005 | village |
| `village_4` | `village-4` | 5006 | village |
| `village_5` | `village-5` | 5007 | village |
| `village_6` | `village-6` | 5008 | village |

Service names (hyphenated) match the `SERVICE_NAME` resource attribute used in traces. Location IDs (underscored) are what DB rows and `game_config.py` use. Bridge: `location_id.replace('_', '-')`.

## File map

| File | Size | Purpose |
|---|---|---|
| `game_config.py` | ~12 KB | `MAPS` dict: coordinates, connections, initial resources/army/faction, passive-rate, costs, economy caps (`max_resources`/`max_army`/`max_corpses`). |
| `telemetry.py` | ~13 KB | `GameTelemetry` class — traces, logs, metrics (5 observable gauges + 1 counter for game state), `BaggageSpanProcessor` (stamps allow-listed baggage keys onto every span), plus Pyroscope profiling with OTel span-profile linkage. |
| `location_server.py` | ~80 KB (~1950 lines) | `LocationServer` class — Flask app, routes, DB access, pathfinding, battle resolution, background-thread movement with debit-at-send + compensation semantics. |
| `run_game.py` | — | CLI to run all 8 services as separate local processes (non-Docker). |
| `Dockerfile` | small | `python:3.11-slim`, `pip install -r requirements.txt`, runs `python location_server.py`. |
| `requirements.txt` | small | Flask 3.1.3, requests 2.33.1, OpenTelemetry SDK/API + OTLP gRPC/HTTP exporters, `pyroscope-io` + `pyroscope-otel` for profiling. |

## Routes

| Method | Path | Handler span name | Purpose |
|---|---|---|---|
| `GET` | `/` | `get_location_info` | Location state + optional cooldown |
| `POST` | `/collect_resources` | `collect_resources` | Capital-only; 5 s cooldown; +20 resources |
| `POST` | `/create_army` | `create_army` | Capital-only; costs 30 resources → +1 army unit |
| `POST` | `/move_army` | `move_army_request` | Atomic army debit (409 on conflict); spawns background movement thread with a fresh `movement_id` |
| `POST` | `/all_out_attack` | `all_out_attack` | Capital-to-capital attack via `_find_path(target, ATTACK)`; same atomic debit + `movement_id` |
| `POST` | `/receive_army` | `receive_army` | Target of `_continue_army_movement`; validates payload, dedupes by `movement_id`, resolves battle via `_handle_battle` with span events |
| `POST` | `/receive_resources` | `receive_resources` | Target of `_forward_resources`; validates payload; banks at destination, relays at intermediate hops (no banking), `captured: true` on faction mismatch |
| `GET` | `/health` | — | Docker health check; returns `{"status": "ok"\|"degraded", "threads": {name: alive}}` with passive-thread liveness |
| `POST` | `/send_resources_to_capital` | — | Village → friendly capital; guarded debit-at-send, then `_forward_resources` |
| `POST` | `/reload` | — | Re-read `active_map_id` + rebind slot identity in place (war_map calls this after `/select_map`) |
| `GET` | `/faction_economy?faction=...` | — | Read a faction's corpse pool (AI uses it) |

## Key algorithms

### Dijkstra pathfinding — `_find_path()` at `location_server.py:454`

Faction-aware edge weights:

| Mode | Friendly | Neutral | Enemy |
|---|---|---|---|
| `PathType.RESOURCE` | 1 | 2 | ∞ (unreachable) |
| `PathType.ATTACK` | 1 | 2 | 3 |

Resource routing only returns a path for factions with a resource economy. Attack routing allows crossing enemy terrain at a cost.

**Path convention:** every payload's `remaining_path` holds the hops *after* the receiving location for armies (`remaining_path[0]` is the hop after the receiver), and the receiver-first slice for resources (`remaining_path[0]` is the receiver itself). Both `/all_out_attack` and the `/receive_army` continuation use the army convention — keep them in sync or hops will self-deliver.

### Battle resolution — `_handle_battle()` at `location_server.py:514`

| Case | Outcome | New army | New faction |
|---|---|---|---|
| Same faction | `reinforcement` | `attacking + defending` | defender's |
| `attacking > defending` | `attacker_victory` | `attacking - defending` | attacker's |
| `defending > attacking` | `defender_victory` | `defending - attacking` | defender's |
| equal | `stalemate` | `0` | defender's (territory held by default) |

Every outcome calls `telemetry.record_battle(attacker_faction, defender_faction, result)`, which increments the `game.battles` counter and force-flushes metrics. The `/receive_army` battle span sets `battle.occurred=true` and emits `battle_started` / `casualties_calculated` / `territory_captured` span events around the resolution.

### State updates, caps, and guarded debits

- `_update_location_state()` (`location_server.py:339`) is the central write path: it clamps `resources`/`army` to the per-map caps (`rules["max_resources"]`, `rules["max_army"]`) and forces metric collection on every mutation, so the dashboard reflects state within ~1 s instead of waiting for the 10 s `PeriodicExportingMetricReader` cycle.
- `_take_all_army()` (`:384`) — optimistic-concurrency debit (`UPDATE ... WHERE army = ?`); the loser of a race gets a 409.
- `_credit_army()` / `_credit_resources()` (`:405` / `:440`) — *additive*, capped credits used by delivery and compensation paths, so refunds compose with reinforcements that arrived in the meantime.
- `_debit_resources()` (`:423`) — guarded debit (`WHERE resources >= ?`) for debit-at-send transfers.

### Movement integrity — debit-at-send, compensation, idempotency

Armies and resources are debited from the source *before* the 5 s in-flight delay. If delivery fails at the transport level, the background thread credits them back (`army_returned` / `resources_returned` span events + span status ERROR). A lost battle or a captured caravan is a **game outcome** — no refund (`/receive_resources` returns `captured: true` so the sender can tell the difference). Every movement carries a `movement_id` (UUID, stamped as `game.movement.id` on every hop's spans); `/receive_army` keeps a 120 s in-memory dedupe cache (`_check_duplicate_movement` at `:885`) so the transport retry in `_make_request_with_trace` can never fight the same battle twice. Inbound payloads are validated by `_validate_inbound_payload` (`:856`): integer bounds, known faction, and `source_location` adjacent to this location.

## OpenTelemetry patterns specific to `app/`

### HTTP clients go through one helper

`_make_request_with_trace()` at `location_server.py:762-820` is the only place outbound HTTP happens. It wraps every call in a CLIENT span with **OTel HTTP semantic-convention** attribute names (`url.full`, `http.request.method`, `http.response.status_code`), calls `inject(headers)` to propagate W3C trace context (and baggage) downstream, applies a `(3, 10)` connect/read timeout, and retries transport errors exactly once (2 s backoff, `retry_attempted` span event — safe because `/receive_army` is idempotent on `movement_id`). HTTP 4xx/5xx are not retried. If you add a new outbound call, use this helper — do not call `requests.post` directly.

### Background threads capture context explicitly

Two methods spawn background threads for delayed operations:

- `_continue_army_movement()` at `location_server.py:562-660` — 5 s delay before the army arrives; credits the army back to the source on transport failure.
- `_forward_resources()` at `location_server.py:662-760` — 5 s delay before the resources arrive; credits back on transport failure, but **not** when the response says `captured` (the capturing faction keeps the caravan).

Both follow the canonical pattern:

```python
ctx = get_current()              # capture before Thread().start()

def work():
    token = attach(ctx)          # re-attach inside the thread
    try:
        with tracer.start_as_current_span("..."):
            ...                  # span now belongs to the captured trace
    finally:
        detach(token)

Thread(target=work).start()
```

If you add a new background thread, replicate this pattern. Python threads will **not** inherit OTel context on their own — the span will be orphaned with a fresh trace_id. Note that `get_current()` captures *baggage* too, which is why delayed movement spans still carry `game.session.id`.

### Baggage → span attributes

`telemetry.py` registers a `BaggageSpanProcessor` (`telemetry.py:31`) that copies the allow-listed baggage keys (`game.session.id`, `player.faction`, `game.actor`) onto every span at start. war_map and the AI set the baggage; this service only needs the processor — propagation is automatic via `extract`/`inject`.

### Span attributes that feed TraceQL queries

Preserve these when adding or modifying spans (dashboards and the README's example queries depend on them; the Python code sets the un-prefixed name, TraceQL adds the `span.` prefix):

- `resource.movement = true` — any resource transfer span (`resource_movement`, `/receive_resources`, `/send_resources_to_capital`)
- `battle.occurred = true` — any span that triggers `_handle_battle`
- `player.action = true` — set by war_map on player-action spans (not by this service)
- `game.movement.id` — every hop/battle span of one army's journey
- `wall.battle = true` — battles at `wall`-type locations (WWA)

## Custom metrics — `telemetry.py`

See `AGENTS.md` for the full cross-service metrics table. `app/`-specific:

| Metric | Type | Callback location in `telemetry.py` |
|---|---|---|
| `game.resources` | observable gauge | `_observe_resources` at `:236` |
| `game.army_size` | observable gauge | `_observe_army_size` at `:254` |
| `game.battles` | counter | `record_battle` at `:327` |
| `game.resource_transfer_cooldown` | observable gauge | `_observe_resource_cooldown` at `:273` |
| `game.location_control` | observable gauge | `_observe_location_control` at `:293` (values: `northern=1`, `southern=2`, `neutral=0`, unknown=`-1`) |

The gauge callbacks read from live server state via `_get_location_state()`, which the `LocationServer` registers on the telemetry instance at construction time.

## New mechanics (White Walkers Attack)

All defined in `app/game_config.py`'s `MAPS["white_walkers_attack"]["rules"]`. All behave as no-ops on `war_of_kingdoms`.

- **Wall defender multiplier** — `_handle_battle` accepts a `location_type` argument and scales `defending_army` by `rules["wall_multiplier"]` (2.0 on WWA, 1.0 on WoK) when the location type is `wall`. Remaining defender count is converted back to physical units after the fight.
- **Corpse economy** — when the battle winner is `white_walkers`, the post-battle hook in `receive_army` calls `self._add_corpses(attacking + defending - remaining, "white_walkers")`. `create_army` reads `get_army_currency(map_id, faction)` and, for `currency == "corpses"`, atomically decrements via `_spend_corpses` instead of touching `resources`. The corpse pool lives in `faction_economy` (persistent) so a `/reload` doesn't wipe it.
- **Barbarian passive growth** — `_start_barbarian_growth(interval_s)` runs when `faction == "barbarian"`; adds +1 army every `rules["barbarian_army_growth_interval_s"]` (30 s). Guards each iteration against identity changes via `/reload`.
- **Captured-camp resource generation** — `_start_passive_generation()` is launched for *every* `type == "village"` slot at boot (including barbarian Free Folk camps). The per-iteration `faction != "barbarian"` guard keeps it a no-op while the camp is still barbarian, then it starts producing the standard village amount the moment the player captures it. Without this fallthrough, captured camps stayed unproductive because the thread was never started on barbarian slots.
- **White Walker passive corpses** — `_start_white_walker_corpse_tick(interval_s)` runs at the WW fortress, +1 corpse every `rules["white_walker_passive_corpse_interval_s"]` (15 s).
- **Night's Watch passive resources** — `_start_nights_watch_capital_resource_tick(interval_s, amount)` runs at Castle Black on WWA (`faction == "nights_watch"`, `loc_type == "capital"`), adding `rules["nights_watch_capital_passive_amount"]` resources every `rules["nights_watch_capital_passive_interval_s"]` (5 per 10 s). Manual `/collect_resources` (+20, 5 s cooldown) still works alongside.
- **Economy caps** — `rules["max_resources"]` (1000), `rules["max_army"]` (50), `rules["max_corpses"]` (200) on *both* maps; clamped centrally in `_update_location_state` / `_credit_*` / `_add_corpses` so AFK passive income can't break the late game.
- **Thread resilience** — every passive loop wraps its iteration in try/except (a transient SQLite busy error must not kill the economy permanently), registers itself in `self._passive_threads`, and is surfaced via `/health`'s `threads` map.
- **Corpse pool seeding** — `reset_database()` (`location_server.py:1095`) re-reads the active map *before* repopulating (war_map writes the new `active_map_id` first, then calls `/reset`) and seeds a zero-corpse `faction_economy` row for every corpse-currency faction, so the AI's `/faction_economy` reads work from t=0.

## DB additions (live in `game_state.db`)

- **`game_config`** — `(key, value)` key/value store. The `active_map_id` row is authoritative; containers re-read it on boot and on `/reload`.
- **`faction_economy`** — `(faction, corpses)`. Updated by `_add_corpses` / `_spend_corpses`. Read by the AI via `/faction_economy?faction=white_walkers`.

## Environment

| Var | Default | Purpose |
|---|---|---|
| `SLOT_ID` | — (required, `slot_1` … `slot_8`) | Fixed physical slot this container occupies |
| `LOCATION_ID` | — (legacy; no longer authoritative) | Kept for backward-compat with `run_game.py` local dev |
| `PORT` | derived from `LOCATION_ID` | HTTP listen port |
| `IN_DOCKER` | unset | When set, location URLs resolve via container DNS (`village-2:5004`) instead of `localhost:5004` |
| `DATABASE_FILE` | `/data/game_state.db` (Docker) / `./game_state.db` (local) | SQLite WAL-mode DB |

## Common edits

**Add a new location.**
1. Add an entry to `LOCATIONS` in `game_config.py` (connections list, initial resources/army/faction, port).
2. Add a `village-N` service in both `docker-compose.yml` and `docker-compose.coda.yml`.
3. Add to the `LOCATION_PORTS` dict in `war_map/app.py` and `ai_opponent/ai_server.py`.
4. Update the services-and-ports table in `../AGENTS.md` and the location table at the top of this file.

**Add a new metric.**
1. Add an observable gauge (or counter) in `telemetry.py` next to the existing ones.
2. If it reads from location state, register a callback that calls `self._get_location_state(...)`.
3. Add a row to the metrics table in this doc and in `../AGENTS.md`.

**Add a new route.**
1. Wrap the handler in `tracer.start_as_current_span(..., context=extract(request.headers), ...)`.
2. Add the relevant TraceQL attribute (`battle.occurred`, `resource.movement`, …) so dashboards pick it up; `player.action` is set by war_map, not here.
3. If the route spawns a background thread, follow the `get_current()` / `attach` / `detach` pattern from `:562-660`.
4. If the route accepts state-changing input from a peer, validate it with `_validate_inbound_payload` (or equivalent bounds/faction/adjacency checks).

## Keep this doc current

Per the sub-agent rule, any change to routes, metrics, span attributes, env vars, or the line-number anchors above must land in the same work unit. Before returning a response that touched `app/`, grep this file for references to anything you changed.

## Cross-references

- [`../AGENTS.md`](../AGENTS.md) — scenario-wide architecture and patterns
- [`../war_map/CLAUDE.md`](../war_map/CLAUDE.md) — the consumer of this service's HTTP API on behalf of the player
- [`../ai_opponent/CLAUDE.md`](../ai_opponent/CLAUDE.md) — the other consumer of this API (autonomous)
- [`../SPAN_LINKS.md`](../SPAN_LINKS.md) — how action spans chain across services
