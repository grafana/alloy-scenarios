# Game of Tracing — Agent Guide

> Canonical guide for any AI coding agent working inside this scenario. Tool-agnostic (Cursor, Codex, Cline, Aider, Claude Code). Claude-specific dispatch lives in `CLAUDE.md`.

## What this scenario is

**Game of Tracing** (titled *War of Kingdoms* in the UI) is a distributed-tracing tutorial game in the `alloy-scenarios` repository. It is substantially more elaborate than other scenarios in the repo: 10 Python/Flask services, two kingdoms competing over 8 territories, an algorithmic AI opponent, and the full LGMT stack (Loki, Grafana, Metrics/Prometheus, Tempo) sitting behind Grafana Alloy.

The **headline feature** is **span-link-driven game replay**: every player and AI action stores its `trace_id`/`span_id` in SQLite; the next action creates an OpenTelemetry `trace.Link` to the previous one, producing a causal chain of traces that can be replayed from Tempo. See `SPAN_LINKS.md` for the full spec and `README.md` for the player-facing tutorial narrative.

## Architecture at a glance

```
 Players ──► war-map (8080) ──┐
                              │
 AI Opponent (8081) ──────────┤──► 8 Location Services (5001-5008)
                              │       southern-capital, northern-capital,
                              │       village-1 … village-6
                              │
 All services ──OTLP──► Alloy (4317 gRPC / 4318 HTTP) ──► Tempo (3200)
                                                      ├─► Loki  (3100)
                                                      └─► Prom  (9090)
                                                          │
 Grafana (3000) ──datasources──► Tempo (default), Loki, Prometheus
```

All services push OTLP to Alloy; Alloy fans out by signal (traces→Tempo, logs→Loki, metrics→Prometheus). Grafana is auto-provisioned with all three datasources plus traces↔logs↔metrics correlation.

## Services and ports

| Service | Port(s) | Build context | Image version env | Purpose |
|---|---|---|---|---|
| `loki` | 3100 | — | `GRAFANA_LOKI_VERSION` (default 3.6.7) | Log storage |
| `prometheus` | 9090 | — | `PROMETHEUS_VERSION` (default v3.10.0) | Metrics storage + OTLP receiver |
| `tempo` | 3200 | — | `GRAFANA_TEMPO_VERSION` (default 2.10.1) | Trace storage + metrics generator |
| `grafana` | 3000 | — | `GRAFANA_VERSION` (default 12.4.0) | Visualization (anonymous admin) |
| `alloy` | 12345, 4317, 4318 | — | `GRAFANA_ALLOY_VERSION` (default v1.14.0) | Telemetry pipeline |
| `southern-capital` | 5001 | `./app` | — | Capital location service |
| `northern-capital` | 5002 | `./app` | — | Capital location service |
| `village-1` … `village-6` | 5003-5008 | `./app` | — | Village location services |
| `war-map` | 8080 | `./war_map` | — | Game UI + span-link broker |
| `ai-opponent` | 8081 | `./ai_opponent` | — | Algorithmic AI opponent |

Image versions are centralized at `/Users/jayclifford/Repos/alloy-scenarios/image-versions.env` — edit that file, not the compose files (they use `${VAR:-default}` syntax).

## Submodules (each has its own CLAUDE.md)

- **`app/`** — the 8 location Flask services. See [`app/CLAUDE.md`](app/CLAUDE.md).
- **`ai_opponent/`** — the algorithmic strategic AI (not LLM). See [`ai_opponent/CLAUDE.md`](ai_opponent/CLAUDE.md).
- **`war_map/`** — the Flask UI and the owner of span-link reconstruction logic. See [`war_map/CLAUDE.md`](war_map/CLAUDE.md).

## Shared state

One Docker volume, `game-data`, mounted at `/data`. **Two SQLite databases live under it, with different owners — do not confuse them:**

| File | Owner | Mode | Purpose |
|---|---|---|---|
| `game_state.db` | All 8 location services (shared) | WAL | Canonical game state: resources, armies, faction per location |
| `game_sessions.db` | `war_map/` only | default | `game_actions` table: per-action `trace_id`, `span_id`, `action_sequence`, `game_session_id` — drives span linking |

Overriding `DATABASE_FILE` (game_state) or `GAME_SESSIONS_DB` (game_sessions) env vars on `war_map` is supported.

## Two Alloy configurations

### Default — River (HCL)
```bash
cd game-of-tracing && docker compose up -d
```
Uses `config.alloy`. Alloy runs with `run /etc/alloy/config.alloy`.

### Alternate — OTel Collector YAML
```bash
cd game-of-tracing && docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d
```
Uses `config-otel.yaml`. Alloy runs with its OTel Engine mode: `otel --config=/etc/alloy/config-otel.yaml`. The pipeline is functionally identical; this variant demonstrates Alloy's ability to accept OTel Collector syntax.

## OpenTelemetry patterns you must respect

Every service has its own `telemetry.py` exposing a `GameTelemetry` class that wires up all three signals.

- **Traces** — OTLP gRPC → `alloy:4317`, `BatchSpanProcessor(max_export_batch_size=1)`. The batch size of 1 is **intentional** for demo timing; do not tune it.
- **Logs** — OTLP HTTP → `alloy:4318/v1/logs`, `BatchLogRecordProcessor(max_queue_size=30, max_export_batch_size=5)`.
- **Metrics** — OTLP HTTP → `alloy:4318/v1/metrics`, `PeriodicExportingMetricReader(export_interval_millis=10000)`, `TraceBasedExemplarFilter` (so metric exemplars link to trace IDs).

### Context propagation is manual

Incoming requests extract W3C trace context from headers; outgoing requests inject it:

```python
# Incoming (every route handler):
ctx = extract(request.headers)
with tracer.start_as_current_span("name", context=ctx, ...) as span:

# Outgoing (canonical helper at app/location_server.py:327-352):
inject(headers)
requests.post(url, headers=headers, ...)
```

### Background threads MUST capture context explicitly

Python threads do not inherit OpenTelemetry context. The scenario's canonical pattern is to capture before spawning and attach inside the thread:

```python
# app/location_server.py:209-271 (_continue_army_movement) — canonical example:
ctx = get_current()

def move():
    token = attach(ctx)
    try:
        with self.tracer.start_as_current_span("army_movement", ...):
            ...
    finally:
        detach(token)

Thread(target=move).start()
```

The same pattern appears in `_transfer_resources_along_path` at `app/location_server.py:273-325`. If a background span shows up with a missing or different `trace_id`, the `get_current()` / `attach` / `detach` pair is the first thing to check.

## Span links — the headline feature

Span links are the mechanism that turns a sequence of discrete player actions into a replayable narrative. See `SPAN_LINKS.md` for the full design.

**Flow:**
1. Player selects a faction → `war_map/app.py` creates a `game_session_id` (UUID).
2. Every action handler (`/api/collect_resources`, `/api/create_army`, `/api/move_army`) does:
   - Looks up the previous action for this session via `get_previous_action_context()` at `war_map/app.py:130-170`. That function reads `trace_id` and `span_id` from the `game_actions` SQLite table and rebuilds a `trace.SpanContext(..., is_remote=True, trace_flags=TraceFlags.SAMPLED)`.
   - Wraps the context in a link via `create_span_link_from_context()` at `war_map/app.py:172-189`, attaching `link.type="game_sequence"`, `link.relation="follows"`, `game.sequence="true"`.
   - Starts its own action span with that link, then calls `store_game_action()` to record its own `trace_id`/`span_id` for the next action to link back to.
3. The AI opponent uses the same primitive with a different link type — `link.type="ai_decision_trigger"` — to link its decision span to the action execution span it spawns (see `ai_opponent/ai_server.py`).
4. The replay UI queries Tempo:
   - `GET /api/v2/search/tag/game.session.id/values` to enumerate sessions.
   - `GET /api/search?q={game.session.id="<id>"}` to pull every trace in a session.
   - SQLite `game_actions` is the fallback if Tempo is unavailable.

## Custom metrics reference

### From `app/telemetry.py`
| Metric | Type | Attributes | Notes |
|---|---|---|---|
| `game.resources` | observable gauge | `location`, `location_type` | Current resource pool per location |
| `game.army_size` | observable gauge | `location`, `location_type`, `faction` | Current army strength |
| `game.battles` | counter | `attacker_faction`, `defender_faction`, `result`, `location` | `result ∈ {attacker_victory, defender_victory, stalemate, reinforcement}` |
| `game.resource_transfer_cooldown` | observable gauge | `location` | Seconds remaining |
| `game.location_control` | observable gauge | `location`, `location_type`, `faction` | `northern=1, southern=2, neutral=0, unknown=-1` |

### From `ai_opponent/telemetry.py`
| Metric | Type | Attributes |
|---|---|---|
| `ai.decisions` | counter | `action_type`, `phase`, `reason` |
| `ai.plans_created` | counter | `goal` |
| `ai.plans_abandoned` | counter | `reason` |
| `ai.decision_cycle_duration_seconds` | histogram | `phase` |
| `ai.territory_count` | observable gauge | `faction` |
| `ai.total_army` | observable gauge | `faction` |

### Span attributes used by the provisioned Grafana dashboard
Preserve these when adding new spans — the dashboard's TraceQL filters depend on them:
- `span.resource.movement = true`
- `span.battle.occurred = true`
- `span.player.action = true`

## Common tasks

```bash
# Start everything
cd game-of-tracing && docker compose up -d

# Stop (preserves volume)
docker compose down

# Stop and wipe game state
docker compose down -v

# Rebuild only one service after code change
docker compose up -d --build war-map

# Switch to the OTel Engine variant
docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d

# Tail a trace end-to-end
# 1. Game UI:      http://localhost:8080
# 2. Grafana:      http://localhost:3000 (anonymous admin)
# 3. Alloy debug:  http://localhost:12345/debug/livedebugging
# 4. Tempo API:    http://localhost:3200
```

## Gotchas

- **Hyphens vs underscores.** Service names are hyphenated (`southern-capital`, set via `SERVICE_NAME` resource attribute); location IDs in game_config.py and DB rows are underscored (`southern_capital`). Code that bridges them uses `location_id.replace('_', '-')`. Do not cross them.
- **Two compose files — `docker-compose.yml` and `docker-compose.coda.yml`.** The coda variant redefines the same 10 app-layer services already defined in the main compose file, for use with the `coda` CLI. When editing app services, update both.
- **Image versions.** Live in `/Users/jayclifford/Repos/alloy-scenarios/image-versions.env`. Compose files use `${VAR:-default}` — edit the env file, not the compose.
- **Grafana is auto-provisioned** via `grafana/datasources/defaults.yml`. Tempo is the default datasource; service map, traces-to-logs (Loki `trace_id` label), traces-to-metrics, and exemplars are pre-wired. Do not add datasources via UI — edit the YAML.
- **Tempo metrics generator is enabled** in `tempo-config.yaml` with processors `service-graphs`, `span-metrics`, `local-blocks`, writing to `prometheus:9090/api/v1/write`. Ingester `max_block_duration: 5m` and 720h compactor retention are demo-tuned, not production values.
- **`grafana-traces-app` plugin** is installed via `GF_INSTALL_PLUGINS` at container start. If Grafana is slow on first boot, that is why.
- **`war-map` strips `X-Frame-Options`** in an `@app.after_request` hook (`war_map/app.py:191-194`) so the UI can be embedded in Grafana iframes. Intentional — do not remove.

## Keep docs current

**Any change to this scenario must land in the same work unit as a doc update.** Stale line-number anchors, removed symbols, or new services that nobody documents are treated as regressions, not cleanup tasks.

Files that must be checked whenever the scenario changes:
- `game-of-tracing/AGENTS.md` (this file)
- `game-of-tracing/CLAUDE.md`
- `game-of-tracing/app/CLAUDE.md`
- `game-of-tracing/ai_opponent/CLAUDE.md`
- `game-of-tracing/war_map/CLAUDE.md`
- `.claude/agents/game-of-tracing-expert.md` (cheat-sheet references)

Triggers that require a doc update: new service, renamed function, new/changed span attribute, new env var, added/removed metric, port change, dependency bump, new action type in the span-link chain, change to any cited line-number anchor.

The Claude sub-agent at `.claude/agents/game-of-tracing-expert.md` owns this responsibility end-to-end for Claude Code sessions. For non-Claude agents: before returning a response that involved a code edit, grep the six files above for any outdated references and update them.

## Verification

After any meaningful change, run through this sequence:

1. **Smoke the scenario.** `cd game-of-tracing && docker compose up -d`; wait ~20s for all 10 services to be healthy (`docker compose ps` — all should be `(healthy)` or `Up`).
2. **Confirm Alloy ingest.** Open `http://localhost:12345/debug/livedebugging`. Select the `otelcol.receiver.otlp.default` component and confirm non-zero signal counts for traces/logs/metrics.
3. **Trigger a player action.** Open `http://localhost:8080`, pick a faction, collect resources, create an army, move it to a neutral village.
4. **Inspect the resulting trace.** Grafana at `http://localhost:3000` → Explore → Tempo → Search by `game.session.id` tag. Verify:
   - Parent player-action span in `war-map`.
   - Child CLIENT span with propagated trace context.
   - SERVER span in the target location (`village-X` etc.).
   - Background `army_movement` span sharing the same `trace_id` (confirms `get_current()`/`attach` worked).
   - A span link back to the previous action span (the headline feature).
5. **Dashboard check.** Open the provisioned *War of Kingdoms* dashboard; TraceQL filters like `{span.resource.movement = true}` should return traces.
6. **Shutdown.** `docker compose down` (add `-v` to wipe volumes).

## Cross-references

- Full span-link design: [`SPAN_LINKS.md`](SPAN_LINKS.md)
- Player-facing tutorial: [`README.md`](README.md)
- Generic scenario conventions: [`../CLAUDE.md`](../CLAUDE.md)
- Submodule guides: [`app/CLAUDE.md`](app/CLAUDE.md), [`ai_opponent/CLAUDE.md`](ai_opponent/CLAUDE.md), [`war_map/CLAUDE.md`](war_map/CLAUDE.md)
