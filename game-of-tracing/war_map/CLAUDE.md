# war_map/ — UI + Span-Link Broker

> Flask web UI on port 8080, game session orchestrator, and **owner of the span-link reconstruction logic that drives game replay**. This doc is read by any AI coding agent. For scenario-wide context read [`../AGENTS.md`](../AGENTS.md) first.

## Purpose

`war-map` is the human-facing surface of the game and the coordination point for everything the player touches:

- Hosts the **map picker** (`/map_picker` + `/select_map`) that lets the user choose between `war_of_kingdoms` and `white_walkers_attack`, then renders the faction selection (or single-player auto-start) for the chosen map.
- Renders the interactive game map (territory ownership, army sizes, supply routes, wall-hold HUD for WWA).
- Manages faction selection, sessions, and the human player's identity.
- Is the **sole writer** of the `game_actions` SQLite table — the record of every action's trace/span IDs that makes span-link replay possible (rows carry a `map_id` column).
- Activates / deactivates the AI opponent on behalf of the player (auto-activates as `white_walkers` when the chosen map is WWA).
- Proxies trace-replay queries to Tempo and falls back to local SQLite when Tempo is unavailable.
- Instruments player actions as `SERVER` spans with `trace.Link`s chaining each action to the previous one in the session, with `player.action=true` and W3C Baggage (`game.session.id`, `player.faction`, `game.actor`) attached via the `game_baggage()` context manager (`app.py:45`).
- Runs the **wall-hold tick thread** (`_wall_tick_thread`, 30 s cadence) that increments `wall_hold` when one faction owns every wall keep, and declares the WWA winner at 5 consecutive ticks (flipping the game-over flags directly, not just on the next poll).
- **Declares the winner**: `check_game_over()` runs the capital-capture check on *every* map (driven by `CAPITALS_BY_MAP` — a capital held by anyone but its original owner ends the game), plus the wall-hold check on WWA. So on WWA either side can win fast by storming the enemy fortress or slow by holding the Wall.
- **Enforces game over**: once a winner is declared, the five player-action endpoints return 409 via `_reject_if_game_over()` (`app.py:850`) and the AI is deactivated exactly once via `_deactivate_ai_once()` (`app.py:832`). Location servers stay permissive by design — in-flight movements should still resolve.

## File map

| File | Size | Purpose |
|---|---|---|
| `app.py` | ~90 KB | Flask app, session/player management, span-link broker, Tempo proxy for replay, AI activation control, game-over enforcement. |
| `telemetry.py` | ~5 KB | `GameTelemetry` — traces + logs (no custom metrics), `BaggageSpanProcessor` (stamps allow-listed baggage onto spans), plus Pyroscope profiling with OTel span-profile linkage. |
| `templates/index.html` | ~7 KB | Faction selection screen. |
| `templates/map.html` | ~50 KB | Main SVG-based game map with real-time updates. |
| `templates/layout.html` | ~4 KB | Shared layout chrome. |
| `templates/replay.html` | ~6 KB | Replay session picker. |
| `templates/replay_session.html` | ~28 KB | Per-session trace-replay UI — the consumer of the span-link chain. |
| `static/css/style.css` | — | UI styling. |
| `Dockerfile` | small | `python:3.11-slim`, runs `python app.py`. |
| `requirements.txt` | small | Flask 3.1.3, requests 2.33.1, python-dotenv 1.2.2, OpenTelemetry SDK/API + exporters, `pyroscope-io` + `pyroscope-otel` for profiling. |

## The span-link broker (the critical bit)

### Two SQLite databases — do not confuse

| File | Owner | Purpose |
|---|---|---|
| `game_state.db` | All 8 location services (WAL mode, shared) | Canonical game state |
| `game_sessions.db` | `war_map` **only** | `game_actions` table: `(game_session_id, action_sequence, action_type, player_name, faction, trace_id, span_id, location_id, target_location_id, timestamp, game_state_after, map_id)` |

`game_actions` schema is defined in `init_game_session_tracking()` at `app.py:201`. It carries a `UNIQUE(game_session_id, action_sequence)` constraint — the sequence is what lets "next action" look up "previous action" deterministically.

### Storing an action — `store_game_action()` at `app.py:258`

Called at the tail of every action handler. Reads the current max `action_sequence` for the session, inserts a new row with `next_sequence = max + 1`, returns the sequence number. The MAX+INSERT pair is serialised under a module lock and retried once on `sqlite3.IntegrityError` — a silently dropped row would break the replay chain for the whole session. Persists the active `map_id` (defaults to `get_active_map_id()` when callers don't pass one) so the replay UI can render the correct map layout for each session.

### Resolving a session's map — `get_session_map_id()`

Used by `replay_session_page` to pick the right layout. Reads the first non-NULL `map_id` from the session's actions (cheap — sessions don't switch maps mid-play), falls back to the active map, then to `DEFAULT_MAP_ID`. Without this, the replay template renders the WoK layout regardless of which map was actually played.

### Reconstructing a previous span context — `get_previous_action_context()` at `app.py:343`

Looks up `(trace_id, span_id)` for `(game_session_id, target_sequence)` in SQLite. Converts the hex strings to integers with `int(result[0], 16)` / `int(result[1], 16)` (this step has bitten agents in the past — the IDs are stored as hex strings, not raw bytes). Constructs a `trace.SpanContext(trace_id=..., span_id=..., is_remote=True, trace_flags=trace.TraceFlags.SAMPLED)` and returns it. The `SAMPLED` flag is required — without it, downstream processors may drop the link.

### Creating a link — `create_span_link_from_context()` at `app.py:385`

Wraps the reconstructed context in a `trace.Link(span_context, attributes={...})` with:

- `link.type` — caller-supplied (default `"game_sequence"`; AI opponent uses `"ai_decision_trigger"` in its own code).
- `link.relation` — always `"follows"`.
- `game.sequence` — always `"true"` (enables Tempo tag search).

### Per-action flow inside a player-action handler

```python
rejection = _reject_if_game_over()           # 409 once a winner is declared
if rejection:
    return rejection

previous_span_context = get_previous_action_context(game_session_id, current_sequence)
links = [create_span_link_from_context(previous_span_context, "game_sequence")] if previous_span_context else []

# game_baggage() attaches game.session.id / player.faction / game.actor as
# W3C Baggage *before* the span starts, so the BaggageSpanProcessor stamps
# them onto this span and inject() carries them to every downstream service.
with game_baggage(game_session_id, session.get('faction')), tracer.start_as_current_span(
    "move_army",
    kind=SpanKind.SERVER,
    links=links,
    attributes={
        "game.session.id": game_session_id,
        "game.action.sequence": current_sequence + 1,
        "player.action": True,            # TraceQL: {span.player.action=true}
        "player.name": ...,
        "player.faction": ...,
    },
) as span:
    # ... do the work, call make_api_request, etc.
    store_game_action(
        game_session_id, "move_army", ...,
        trace_id=format(span.get_span_context().trace_id, '032x'),
        span_id=format(span.get_span_context().span_id, '016x'),
        ...
    )
```

The `format(..., '032x')` / `'016x'` pair is the inverse of the `int(..., 16)` step in `get_previous_action_context()` — always keep the two in sync.

## Replay endpoints

The replay UI (`replay_session.html`) is backed by Tempo. `app.py` serves as the proxy and cleans up the responses.

**Primary (Tempo):**
- Discover sessions — `GET {TEMPO_URL}/api/v2/search/tag/game.session.id/values`
- Pull a session's traces — `GET {TEMPO_URL}/api/search?q={game.session.id="<id>"}&limit=100`
- Pull a specific trace — `GET {TEMPO_URL}/api/traces/<trace_id>`

**Fallback (SQLite):** If Tempo returns an error or is unreachable, read the `game_actions` table directly. Replay renders a reduced view (without span payloads) but the session narrative is preserved.

## Environment

| Var | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `war_of_westeros_secret_key` | Flask session secret |
| `AI_URL` / `AI_SERVICE_URL` | `http://localhost:8081` | AI opponent base URL. Docker sets `http://ai-opponent:8081` |
| `DATABASE_FILE` | `../app/game_state.db` | Shared game-state DB (read-only access from war_map) |
| `GAME_SESSIONS_DB` | `game_sessions.db` | `game_actions` DB. Docker sets `/data/game_sessions.db` |
| `API_BASE_URL` | `http://localhost` | Base URL for location server calls (host portion only; port comes from `LOCATION_PORTS`) |
| `TEMPO_URL` | `http://tempo:3200` | Replay-query target |
| `IN_DOCKER` | unset | Switches location URLs between `localhost:500X` and container DNS |

Location ports are hard-coded in `LOCATION_PORTS` at `app.py:416`; mirror any change here in `app/game_config.py`.

All outbound HTTP uses a `(3, 10)` connect/read timeout (`REQUEST_TIMEOUT`), and `get_db_connection()` (`app.py:503`) sets `timeout=15` + `busy_timeout=5000` because `game_state.db` is shared with 8 WAL-mode writers. `map.html` polls `/api/map_data` + `/api/game_status` on a self-scheduling 5 s loop that backs off to 10 s/30 s on consecutive failures behind a "connection lost" banner.

### UI animations are clocked to the server

The location servers deliver every army/resource hop after exactly 5 s (`time.sleep(5)`). `map.html` mirrors this with `SERVER_HOP_MS = 5000`: every `animateTravelingUnit` march lasts exactly one server hop (with a live ETA countdown badge), multi-hop paths chain back-to-back like the server's relays, and each arrival callback triggers `refreshAtArrival()` (refresh at +300 ms and +2 s) so the clash effect and the state flip land together. Map rebuilds are **not** deferred during animations — traveling units are separate DOM elements that survive a marker rebuild, and the source showing `army=0` mid-flight is accurate (debit-at-send). Each poll also diffs faction ownership against the previous poll and fires a clash + event-feed entry for territory flips caused by the AI or the other player. If you change the server's march delay, change `SERVER_HOP_MS` in the same commit.

## `X-Frame-Options` stripped — intentional

`@app.after_request` at `app.py:404-407` removes `X-Frame-Options` from every response:

```python
@app.after_request
def remove_frame_options(response):
    response.headers.pop('X-Frame-Options', None)
    return response
```

This is deliberate — it lets the UI be embedded in Grafana iframes for the replay experience. Grafana's `GF_SECURITY_ALLOW_EMBEDDING=true` is the other half of this configuration. **Do not remove** unless you are also disabling Grafana embedding.

## Common edits

**Add a new action type to the span-link chain.**
1. Add the Flask handler in `app.py`, following the `move_army` / `create_army` pattern: game-over guard, look up previous context, build link, start a SERVER span (wrapped in `game_baggage()`) with link + attributes including `player.action: True`, call `store_game_action()` at the tail.
2. Add a renderer case in `templates/replay_session.html` so the replay UI can visualize the new action.
3. Update the action-types table in [`../SPAN_LINKS.md`](../SPAN_LINKS.md).
4. Update this doc and [`../AGENTS.md`](../AGENTS.md) if the new action surfaces new span attributes.

**Tune the replay query.**
Edit the TraceQL strings in the replay endpoints (`app.py`). The `game.session.id` tag is required — Tempo uses it to group the session's traces.

**Add attributes to every player-action link.**
Edit `create_span_link_from_context()` at `app.py:385`. The current three (`link.type`, `link.relation`, `game.sequence`) are load-bearing — the replay UI reads them.

**Change session-tracking schema.**
Edit `init_game_session_tracking()` at `app.py:201`. Because the DB lives on a persistent Docker volume, a schema change requires either `docker compose down -v` before restart **or** a migration script. Flag to the user which one you recommend before changing columns.

## Keep this doc current

Per the sub-agent rule, any change to span-link fields, replay endpoints, env vars, action types, or the line-number anchors above must land in the same work unit. Before returning a response that touched `war_map/`, grep this file for references to anything you changed.

Particularly sensitive references:
- `app.py:45` — `game_baggage` context manager
- `app.py:201` — `init_game_session_tracking`
- `app.py:258` — `store_game_action`
- `app.py:343` — `get_previous_action_context`
- `app.py:385` — `create_span_link_from_context`
- `app.py:404-407` — `X-Frame-Options` strip
- `app.py:416` — `LOCATION_PORTS` dict
- `app.py:832` / `:850` — `_deactivate_ai_once` / `_reject_if_game_over`

## Cross-references

- [`../AGENTS.md`](../AGENTS.md) — scenario-wide architecture and patterns
- [`../SPAN_LINKS.md`](../SPAN_LINKS.md) — full span-link design spec and replay flow
- [`../app/CLAUDE.md`](../app/CLAUDE.md) — location-server HTTP API this service calls
- [`../ai_opponent/CLAUDE.md`](../ai_opponent/CLAUDE.md) — AI service this one activates/deactivates
