# ai_opponent/ — Strategic AI Decision Engine

> Algorithmic opponent (not LLM-based) that plays the faction not chosen by a human player. This doc is read by any AI coding agent. For scenario-wide context read [`../AGENTS.md`](../AGENTS.md) first.

## Purpose

`ai-opponent` is a Flask service on port **8081** that takes control of a faction and makes strategic decisions on a recurring loop. It is activated by `war_map` via `POST /activate` with JSON body `{"faction": ..., "map_id": ...}` — on the WoK map the player toggles it on manually; on WWA it auto-activates as `white_walkers` the moment the player picks the map.

Two AI variants dispatch off the `faction` field at activation time:

- **`StrategicAI`** — classic WoK opponent (southern / northern). 6-step priority cascade: capital defense → zero-risk captures → resource transfers → plan execution → plan creation → fallback.
- **`WhiteWalkerAI(StrategicAI)`** — single-player WWA opponent. Different cascade: defend fortress → capture unowned wall → reinforce weakest wall (non-capital neighbours preferred; capital is a fallback when no other source has spare army, since `move_army` empties the source) → raid barbarian village (for corpses) → raise army from corpses at the fortress (only requires the capital to still belong to the AI; no minimum garrison) → idle. Reads its corpse pool via `GET /faction_economy?faction=white_walkers` on any location service; spends 5 corpses per army unit instead of 30 resources.

Common to both: the AI:

- Fetches the state of all 8 locations.
- Runs a priority cascade of checks to decide the next action (defend, capture, transfer, plan, fallback).
- Executes the action via the same HTTP API the player uses (against the location services on 5001-5008).
- Emits fully-linked traces so the replay UI can narrate the AI's reasoning alongside the human player's.
- Adapts its loop cadence (2-15 s) to the current game phase.

**This is deterministic code, not an LLM.** No `anthropic`, `openai`, or other model SDKs are imported.

## File map

| File | Size | Purpose |
|---|---|---|
| `ai_server.py` | ~46 KB | Main decision engine: `StrategicAI`, `PhaseDetector`, `Planner`, `MapAnalyzer`, Flask routes, decision loop. |
| `telemetry.py` | ~7.7 KB | `GameTelemetry` class for `ai-opponent` with AI-specific metrics. |
| `README.md` | ~2.6 KB | Feature doc. |
| `Dockerfile` | small | `python:3.11-slim`, `pip install -r requirements.txt`, runs `python ai_server.py`. |
| `requirements.txt` | small | Flask 3.1.3, requests 2.33.0, OpenTelemetry SDK/API + exporters. |

## Decision model

### Priority cascade — `StrategicAI.decide()`

Executed every cycle; returns the first non-null action:

1. **Capital defense.** If the capital is under threat (enemy army adjacent with path-army-estimate exceeding capital garrison), react: build army, pull army back, or preempt.
2. **Zero-risk captures.** Grab any neutral village reachable with overwhelming numerical advantage.
3. **Resource transfers.** Move resources from villages to the capital when the capital is running low.
4. **Plan execution.** If a multi-step plan is active and valid, advance to the next step.
5. **Plan creation.** Propose a new plan targeting the most valuable enemy territory.
6. **Fallback.** Collect resources at the capital.

### Phase detection — `PhaseDetector.detect()` at `ai_server.py:195-212`

Five phases drive cadence and aggressiveness:

| Phase | Condition | Cadence (seconds) |
|---|---|---|
| `READY_TO_ATTACK` | `total_army >= 8` | 3-8 |
| `DESPERATE` | `my_count <= 1` | 2-5 |
| `DEFENSIVE` | `my_count < enemy_count` | medium |
| `DOMINATING` | `my_count > enemy_count + 1` | 5-15 |
| `BALANCED` | everything else | 5-15 |

Cadence is set by `StrategicAI.get_pause_time()`; faster in crisis, slower in stability.

### Supporting classes

- **`MapAnalyzer`** (`ai_server.py:64-135`) — precomputes BFS distances between all location pairs at startup. Used by `path_army_estimate()` to sum enemy armies along shortest path to a target — enabling threat assessment.
- **`Planner`** (`ai_server.py:216+`) — multi-step goal sequences like `[create_army, create_army, create_army, move_army(target)]`. Validated every cycle via `Planner.validate()`; abandoned if preconditions break (e.g., capital lost, source location flipped).
- **`GameMemory`** — tracks territory-loss history, failed attacks, enemy push directions; used by `territory_lost_recently()` etc. at `ai_server.py:180-191` to adjust reactive behavior.

## Custom metrics

| Metric | Type | Attributes | Emitter |
|---|---|---|---|
| `ai.decisions` | counter | `action_type`, `phase`, `reason` | `decide()` / `execute_strategic_action()` |
| `ai.plans_created` | counter | `goal` | `Planner.set_plan` |
| `ai.plans_abandoned` | counter | `reason` | `Planner.abandon` |
| `ai.decision_cycle_duration_seconds` | histogram | `phase` | Each decision cycle |
| `ai.territory_count` | observable gauge | `faction` | Callback into live state |
| `ai.total_army` | observable gauge | `faction` | Callback into live state |

## Span events

Significant state transitions are emitted as events on the active decision span (rather than as standalone spans):

- `phase_transition` — with `from_phase`, `to_phase` attributes
- `territory_change` — with `gained` / `lost` territory lists
- `plan_abandoned` — with `reason` and `original_goal`
- `threat_detected` — with `threat_source`, `threat_army`, `target`

Locations: `ai_server.py:299-327`.

## Span links unique to `ai_opponent/`

The AI opponent instruments its own causal chain **inside a single decision cycle**:

- `ai_decision_cycle` span (SpanKind.INTERNAL) wraps the whole cycle.
- `ai_decision` span (child, INTERNAL) captures the cascade evaluation and chosen action.
- `execute_ai_action` span (INTERNAL) is the action execution — it starts with a `Link` back to the `ai_decision` span's context, with `link.type="ai_decision_trigger"`. This allows the replay UI to jump from the executed action back to the reasoning that produced it.

The linking logic lives around `ai_server.py:888-901`. The AI does **not** participate in the cross-session `game_sequence` chain that `war_map` builds — that is player-only.

## Environment

| Var | Default | Purpose |
|---|---|---|
| `PORT` | `8081` | Flask listen port |
| `IN_DOCKER` | unset | When set, location URLs resolve via container DNS (`southern-capital:5001`) instead of `localhost:5001` |

Telemetry endpoints are hard-coded in `telemetry.py` to `alloy:4317` (gRPC traces) and `alloy:4318` (HTTP logs + metrics). The service resource is registered with `SERVICE_NAME="ai-opponent"`.

## Activation flow

1. `war_map` calls `POST http://ai-opponent:8081/activate` with JSON body `{"faction": "northern"}`.
2. The handler constructs a `StrategicAI(faction)` instance and starts `ai_decision_loop()` in a daemon thread.
3. The loop runs until `/deactivate` is called or the game is marked over.
4. Each cycle captures a span, logs, and increments the appropriate metrics.

## Common edits

**Tune aggressiveness.**
Adjust thresholds in `PhaseDetector.detect()` at `ai_server.py:195-212`, or the cadence ranges in `get_pause_time()`.

**Change the priority cascade.**
Edit `StrategicAI.decide()`. Each priority is its own helper (`_check_capital_defense`, `_find_zero_risk_captures`, `_do_resource_transfers`, plan steps). Reorder by reshuffling the cascade.

**Add a new AI metric.**
Mirror the observable-gauge pattern in `telemetry.py` and wire a callback that reads from `StrategicAI` live state (via a registered state accessor, same pattern as `app/telemetry.py`).

**Add a new span event.**
Call `span.add_event("event_name", attributes={...})` inside the decision span. Keep the existing four event names stable — they feed replay UI rendering.

## Keep this doc current

Per the sub-agent rule, any change to the priority cascade, phase thresholds, metric set, env vars, or the line-number anchors above must land in the same work unit. Before returning a response that touched `ai_opponent/`, grep this file for references to anything you changed.

## Cross-references

- [`../AGENTS.md`](../AGENTS.md) — scenario-wide architecture and patterns
- [`../app/CLAUDE.md`](../app/CLAUDE.md) — the location-server HTTP API this AI calls
- [`../war_map/CLAUDE.md`](../war_map/CLAUDE.md) — the orchestrator that activates/deactivates this service
- [`../SPAN_LINKS.md`](../SPAN_LINKS.md) — span-link design, including the `ai_decision_trigger` link type
