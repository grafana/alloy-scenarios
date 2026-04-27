# CLAUDE.md — Game of Tracing (Claude Code)

> Claude-specific workflow for this scenario. For architecture, services, OpenTelemetry patterns, span-link mechanics, and gotchas, **read [`./AGENTS.md`](AGENTS.md) first**. This file only covers what's different when the agent is Claude Code.

## Start here

1. Read `./AGENTS.md` for the scenario overview — including the **Maps** and **Slot identity** sections.
2. Read the submodule `CLAUDE.md` matching the area you are touching: [`app/CLAUDE.md`](app/CLAUDE.md), [`ai_opponent/CLAUDE.md`](ai_opponent/CLAUDE.md), [`war_map/CLAUDE.md`](war_map/CLAUDE.md).
3. If the task involves span links, trace replay, cross-service context propagation, or AI decision logic — delegate to the sub-agent below.

### Two maps, one stack

The scenario ships **two maps** selected via an in-UI picker at game start: `war_of_kingdoms` (default 2-player) and `white_walkers_attack` (single-player Night's Watch vs AI White Walkers with `wall` keeps, corpse economy, and a 5-tick hold-to-win condition). Both reuse the same 8 location containers — each container has a constant `SLOT_ID` env and picks up its logical identity from `MAPS[active_map_id]["slot_assignments"][SLOT_ID]` in `app/game_config.py`. Changing maps writes a new `active_map_id` to the shared `game_config` table and POSTs `/reload` to every slot.

## Sub-agent dispatch

A specialized sub-agent lives at [`../.claude/agents/game-of-tracing-expert.md`](../.claude/agents/game-of-tracing-expert.md). Use it (via `Task` tool, `subagent_type: game-of-tracing-expert`) for any non-trivial question about:

- Reconstructing or debugging span contexts / span links
- Cross-service or cross-thread OpenTelemetry context propagation
- The `StrategicAI` priority cascade, game phases, or AI metric instrumentation
- Tempo TraceQL queries used by the replay UI
- Why a trace is orphaned, missing, or appears duplicated in Grafana

The sub-agent is read-only (no Write/Edit tools) — it reports; the parent agent does the writes. It **also owns keeping the docs in sync with the code** — see "Keep docs current" below.

## Tool preferences

- **Use `Read`, not `cat`**, for the large files in this scenario. Use `offset` / `limit` to target line ranges rather than reading the whole file:
  - `app/location_server.py` (~52 KB, ~1200 lines)
  - `ai_opponent/ai_server.py` (~46 KB)
  - `war_map/app.py` (~64 KB)
  - `war_map/templates/map.html` (~50 KB)
  - `war_map/templates/replay_session.html` (~28 KB)
  - `SPAN_LINKS.md` (~17 KB)
- **Use `Grep`, not `grep | head`** for pattern search across the scenario.
- For the Alloy pipeline debug UI (`http://localhost:12345`), the stack has to be running — either ask the user to `docker compose up -d` or check `docker compose ps` first.

## Read-before-edit checklist

Before editing any service, open these files to ground yourself:

| Change area | Open first |
|---|---|
| Location server behavior | `app/telemetry.py`, relevant route handler in `app/location_server.py`, `app/game_config.py`, the service block in `docker-compose.yml` |
| AI decision logic | `ai_opponent/telemetry.py`, `ai_opponent/ai_server.py`, `ai_opponent/README.md` |
| UI, sessions, or replay | `war_map/telemetry.py`, `war_map/app.py` (especially `:130-189` for span-link plumbing), relevant template under `war_map/templates/` |
| Telemetry pipeline | `config.alloy` (default) or `config-otel.yaml` (OTel variant), `tempo-config.yaml`, `loki-config.yaml`, `prom-config.yaml` |
| Datasources / dashboards | `grafana/datasources/defaults.yml`, `grafana/dashboards/*.json` |
| Image versions | `../image-versions.env` |

## Keep docs current

**Whenever a change to this scenario ships, the matching docs must ship in the same change.** The sub-agent (`game-of-tracing-expert`) enforces this during its work; Claude Code in the main loop is responsible whenever the sub-agent is not invoked.

Triggers that require a doc update in the same commit:

- New service, renamed function, relocated symbol (line-number anchors shift)
- New, removed, or renamed span attribute — especially the ones that feed the Grafana dashboard TraceQL (`span.resource.movement`, `span.battle.occurred`, `span.player.action`)
- New or removed env var
- New or removed metric
- Port change
- Dependency version bump (update `image-versions.env` *and* any docs that quote a version)
- New action type in the span-link chain (both `war_map/app.py` handler and `replay_session.html` renderer)

Files to sweep on every scenario change:

1. `game-of-tracing/AGENTS.md`
2. `game-of-tracing/CLAUDE.md` (this file)
3. `game-of-tracing/app/CLAUDE.md`
4. `game-of-tracing/ai_opponent/CLAUDE.md`
5. `game-of-tracing/war_map/CLAUDE.md`
6. `.claude/agents/game-of-tracing-expert.md`

Stale line-number anchors are treated as regressions, not cleanup tasks. If a cited `file:line` range no longer resolves to the referenced symbol, fix it.

## Relationship to the repo root

- `/Users/jayclifford/Repos/alloy-scenarios/CLAUDE.md` covers the generic multi-scenario conventions (run commands, scenario directory layout, Alloy pipeline shape).
- This file overrides nothing; it extends the root with the patterns that are unique to this scenario (manual context propagation, background-thread context capture, span-link-driven replay, AI instrumentation).
