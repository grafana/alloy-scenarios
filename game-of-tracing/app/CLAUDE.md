# app/ — Location Servers

> 8 Flask microservices representing map territories in the *War of Kingdoms* game. This doc is read by any AI coding agent (Claude, Cursor, Codex, Cline). For scenario-wide context read [`../AGENTS.md`](../AGENTS.md) first.

## Purpose

All 8 locations (2 capitals + 6 villages) run the same codebase — they differ only by `LOCATION_ID` and port. Each location:

- Owns a row in the shared `game_state.db` (resources, army, faction).
- Exposes an HTTP API for collecting resources, creating armies, moving armies, and launching attacks.
- Instruments every route with OpenTelemetry traces, logs, and five custom game metrics.
- Runs passive resource generation for villages (every 15 s) and handles cooldowns for capitals.

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
| `game_config.py` | ~3 KB | `LOCATIONS` dict: coordinates, connections, initial resources/army/faction, passive-rate, costs. |
| `telemetry.py` | ~11 KB | `GameTelemetry` class — traces, logs, metrics (5 observable gauges + 1 counter for game state), plus Pyroscope profiling with OTel span-profile linkage. |
| `location_server.py` | ~52 KB (~1200 lines) | `LocationServer` class — Flask app, routes, DB access, pathfinding, battle resolution, background-thread movement. |
| `run_game.py` | — | CLI to run all 8 services as separate local processes (non-Docker). |
| `Dockerfile` | small | `python:3.11-slim`, `pip install -r requirements.txt`, runs `python location_server.py`. |
| `requirements.txt` | small | Flask 3.1.3, requests 2.33.0, OpenTelemetry SDK/API + OTLP gRPC/HTTP exporters, `pyroscope-io` + `pyroscope-otel` for profiling. |

## Routes

| Method | Path | Handler span name | Purpose |
|---|---|---|---|
| `GET` | `/` | `get_location_info` | Location state + optional cooldown |
| `POST` | `/collect_resources` | `collect_resources` | Capital-only; 5 s cooldown; +20 resources |
| `POST` | `/create_army` | `create_army` | Capital-only; costs 30 resources → +1 army unit |
| `POST` | `/move_army` | `move_army_request` | Move army to adjacent location; spawns background movement thread |
| `POST` | `/all_out_attack` | `all_out_attack` | Capital-to-capital attack via `_find_path(target, ATTACK)` |
| `POST` | `/receive_army` | `receive_army` | Target of `_continue_army_movement`; resolves battle via `_handle_battle` |
| `POST` | `/receive_resources` | `receive_resources` | Target of `_transfer_resources_along_path` |
| `GET` | `/health` | — | Docker health check; returns `{"status":"ok"}` |
| `POST` | `/send_resources_to_capital` | — | Village → friendly capital resource forwarding (used by AI) |

## Key algorithms

### Dijkstra pathfinding — `_find_path()` at `location_server.py:128-182`

Faction-aware edge weights:

| Mode | Friendly | Neutral | Enemy |
|---|---|---|---|
| `PathType.RESOURCE` | 1 | 2 | ∞ (unreachable) |
| `PathType.ATTACK` | 1 | 2 | 3 |

Resource routing only returns a path if the source is a capital of a known faction. Attack routing allows crossing enemy terrain at a cost.

### Battle resolution — `_handle_battle()` at `location_server.py:184-207`

| Case | Outcome | New army | New faction |
|---|---|---|---|
| Same faction | `reinforcement` | `attacking + defending` | defender's |
| `attacking > defending` | `attacker_victory` | `attacking - defending` | attacker's |
| `defending > attacking` | `defender_victory` | `defending - attacking` | defender's |
| equal | `stalemate` | `0` | defender's (territory held by default) |

Every outcome calls `telemetry.record_battle(attacker_faction, defender_faction, result)`, which increments the `game.battles` counter and force-flushes metrics.

### Atomic state updates — `_update_location_state()`

Forces metric collection at `location_server.py:124` on important changes (`faction`, `resources`, or `army` mutated), so the dashboard reflects state within ~1 s of the mutating request instead of waiting for the 10 s `PeriodicExportingMetricReader` cycle.

## OpenTelemetry patterns specific to `app/`

### HTTP clients go through one helper

`_make_request_with_trace()` at `location_server.py:327-352` is the only place outbound HTTP happens. It wraps every call in a CLIENT span, sets `http.url` and `http.status_code` attributes, and calls `inject(headers)` to propagate W3C trace context downstream. If you add a new outbound call, use this helper — do not call `requests.post` directly.

### Background threads capture context explicitly

Two methods spawn background threads for delayed operations:

- `_continue_army_movement()` at `location_server.py:209-271` — 5 s delay before the army arrives at the next location.
- `_transfer_resources_along_path()` at `location_server.py:273-325` — 5 s delay before the resources arrive.

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

If you add a new background thread, replicate this pattern. Python threads will **not** inherit OTel context on their own — the span will be orphaned with a fresh trace_id.

### Span attributes that feed the Grafana dashboard

Preserve these when adding or modifying spans (the provisioned dashboard's TraceQL filters depend on them):

- `span.resource.movement = true` — any resource transfer span
- `span.battle.occurred = true` — any span that triggers `_handle_battle`
- `span.player.action = true` — any span caused by a human player action

## Custom metrics — `telemetry.py`

See `AGENTS.md` for the full cross-service metrics table. `app/`-specific:

| Metric | Type | Callback location in `telemetry.py` |
|---|---|---|
| `game.resources` | observable gauge | `_observe_resources` at `:176-193` |
| `game.army_size` | observable gauge | `_observe_army_size` at `:195-213` |
| `game.battles` | counter | `record_battle` at `:274-290` |
| `game.resource_transfer_cooldown` | observable gauge | `_observe_resource_cooldown` at `:215-233` |
| `game.location_control` | observable gauge | `_observe_location_control` at `:235-260` (values: `northern=1`, `southern=2`, `neutral=0`, unknown=`-1`) |

The gauge callbacks read from live server state via `_get_location_state()`, which the `LocationServer` registers on the telemetry instance at construction time.

## Environment

| Var | Default | Purpose |
|---|---|---|
| `LOCATION_ID` | — (required) | Which row in `LOCATIONS` this service is |
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
2. Add `"span.player.action": True` (if triggered by a player) so the dashboard picks it up.
3. If the route spawns a background thread, follow the `get_current()` / `attach` / `detach` pattern from `:209-271`.

## Keep this doc current

Per the sub-agent rule, any change to routes, metrics, span attributes, env vars, or the line-number anchors above must land in the same work unit. Before returning a response that touched `app/`, grep this file for references to anything you changed.

## Cross-references

- [`../AGENTS.md`](../AGENTS.md) — scenario-wide architecture and patterns
- [`../war_map/CLAUDE.md`](../war_map/CLAUDE.md) — the consumer of this service's HTTP API on behalf of the player
- [`../ai_opponent/CLAUDE.md`](../ai_opponent/CLAUDE.md) — the other consumer of this API (autonomous)
- [`../SPAN_LINKS.md`](../SPAN_LINKS.md) — how action spans chain across services
