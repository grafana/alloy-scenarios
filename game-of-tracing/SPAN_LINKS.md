# Span Links Implementation in Game of Tracing

This document explains how span links are implemented in the Game of Tracing game to enable game replay functionality.

## What Are Span Links?

Span links allow you to create relationships between spans that aren't in a direct parent-child hierarchy. Unlike parent-child relationships (which are synchronous and hierarchical), links are more flexible and can connect spans across different traces or time periods.

## Implementation Overview

### Game Session Tracking

Each player gets a unique `game_session_id` when they select a faction. This ID is used to track all their actions throughout the game:

```python
# Generated when player selects faction
session['game_session_id'] = str(uuid.uuid4())
session['action_sequence'] = 0
```

### Action Storage

Every significant game action is stored in a SQLite database with its trace information:

```sql
CREATE TABLE game_actions (
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
    game_state_after TEXT
)
```

### Span Link Creation

Each new action creates a span link to the previous action in the sequence:

```python
# Get previous action's span context
previous_span_context = get_previous_action_context(game_session_id, current_sequence)

# Create span link using official OpenTelemetry API
if previous_span_context:
    link = trace.Link(
        previous_span_context,
        attributes={
            "link.type": "game_sequence",
            "link.relation": "follows",
            "game.sequence": "true"
        }
    )
    links.append(link)

# Create new span with links
with tracer.start_as_current_span(
    "move_army",
    kind=SpanKind.SERVER,
    links=links,  # Links to previous actions
    attributes={
        "game.session.id": game_session_id,
        "game.action.type": "move_army",
        "game.action.sequence": current_sequence + 1
    }
) as span:
    # ... action logic ...
```

## Supported Actions

The following game actions create span links:

1. **collect_resources** - Collecting resources at a location
2. **create_army** - Creating armies at capitals
3. **move_army** - Moving armies between locations
4. **all_out_attack** - Launching all-out attacks

## Battle Mechanics

The game uses simple but effective battle calculations:

### Combat Rules

1. **Same Faction**: Reinforcement
   - Armies combine: `final_army = attacking_army + defending_army`
   - Used for friendly army movements and reinforcements

2. **Different Factions**: Combat
   - **Attacker Victory**: `remaining_army = attacking_army - defending_army`
   - **Defender Victory**: `remaining_army = defending_army - attacking_army`
   - **Stalemate**: `remaining_army = 0` (equal armies destroy each other)

### All-Out Attack Special Rules

- All-out attacks automatically collect armies from friendly villages along the path
- This simulates gathering reinforcements during the march to enemy territory
- Example: 5 armies + 2 village armies = 7 armies continuing to target

### Battle Calculation Code

```python
def _handle_battle(self, attacking_army: int, attacking_faction: str, 
                  defending_army: int, defending_faction: str) -> tuple[str, int, str]:
    # Same faction = reinforcement
    if attacking_faction == defending_faction:
        return "reinforcement", attacking_army + defending_army, attacking_faction
    
    # Actual combat
    if attacking_army > defending_army:
        remaining = attacking_army - defending_army
        return "attacker_victory", remaining, attacking_faction
    elif defending_army > attacking_army:
        remaining = defending_army - attacking_army
        return "defender_victory", remaining, defending_faction
    else:
        return "stalemate", 0, defending_faction
```

## Game Restart Functionality

The restart system ensures complete game state reset:

### What Gets Reset

1. **Game State Variables**
   - `GAME_OVER`, `WINNER`, `VICTORY_MESSAGE` flags
   - Global game state in war map

2. **Span Links Database**
   - All game action records cleared
   - Fresh start for span link chains

3. **Faction Assignments**
   - Player faction selections cleared
   - All factions become available

4. **AI Opponent**
   - AI automatically deactivated
   - Prevents ghost AI actions

5. **Location Database**
   - All locations reset to initial state
   - Resources, armies, and factions restored

### Restart Process

```python
def reset_game_data():
    # Reset local game state
    reset_game_state()
    
    # Deactivate AI
    requests.post(f"{AI_SERVICE_URL}/deactivate")
    
    # Clear faction assignments
    release_all_factions()
    
    # Clear span links database
    cursor.execute("DELETE FROM game_actions")
    
    # Reset location database
    make_api_request('southern_capital', 'reset', method='POST')
```

### Verification

Use the debug endpoint to verify complete reset:

```bash
curl http://localhost:8080/api/debug/restart_verification
```

Expected response:
```json
{
  "success": true,
  "all_systems_reset": true,
  "details": {
    "game_state_reset": true,
    "span_links_cleared": true,
    "faction_assignments_cleared": true,
    "ai_deactivated": true,
    "database_reset": true
  }
}
```

## Game Replay Chain

With span links, you can trace the complete game narrative:

```
Game Start → Collect Resources → Create Army → Move Army → Battle → Victory
     ↑              ↑               ↑           ↑         ↑        ↑
  [trace_1]     [trace_2]       [trace_3]   [trace_4] [trace_5] [trace_6]
                    ↑               ↑           ↑         ↑        ↑
               [links to]      [links to]  [links to] [links to] [links to]
               trace_1         trace_2     trace_3    trace_4   trace_5
```

## Game Replay Through Tempo

### TraceQL Queries for Replay

#### 1. Find All Game Sessions
```traceql
{game.session.id!=""}
```

#### 2. Get Specific Game Session
```traceql
{game.session.id="abc-123-def"}
```

#### 3. Find Actions with Span Links
```traceql
{link.type="game_sequence"}
```

#### 4. Find Game Actions by Type
```traceql
{game.action.type="move_army"}
```

#### 5. Find Actions by Player
```traceql
{player.name="Alice" && game.session.id!=""}
```

#### 6. Find Battle Outcomes
```traceql
{span.battle.occurred=true}
```

#### 7. Follow One Army Across Every Hop
Every `/move_army` / `/all_out_attack` generates a `movement_id` that is stamped (as `game.movement.id`) on each hop's movement and battle spans:
```traceql
{span.game.movement.id="<uuid>"}
```

#### 8. Separate AI Activity from Human Play
The AI's decision cycles propagate `game.actor="ai"` via W3C Baggage, stamped onto every downstream span:
```traceql
{span.game.actor="ai"}
```

### Tempo API Integration

The replay system uses Tempo's HTTP API:

```python
# 1. Search for game sessions
GET /api/search?q={game.session.id!=""}

# 2. Get specific session traces  
GET /api/search?q={game.session.id="session-id"}

# 3. Get full trace details
GET /api/traces/{trace-id}

# 4. Extract span links from trace data
for span in trace['batches'][0]['spans']:
    for ref in span.get('references', []):
        if ref.get('refType') == 'FOLLOWS_FROM':
            # This is a span link
            linked_span_id = ref.get('spanID')
```

### Replay Engine Architecture

```python
class GameReplayEngine:
    def find_game_sessions(self) -> List[str]:
        """Query Tempo for all game sessions"""
        
    def get_session_traces(self, session_id: str) -> List[Dict]:
        """Get all traces for a specific session"""
        
    def extract_game_actions(self, traces: List[Dict]) -> List[GameAction]:
        """Parse traces into game actions"""
        
    def verify_span_links(self, actions: List[GameAction]) -> None:
        """Verify span link chain integrity"""
        
    def replay_session_step_by_step(self, session: GameSession) -> None:
        """Replay game session action by action"""
```

### Web UI Replay

The game includes web endpoints for replay:

- `GET /api/replay/sessions` - List available game sessions
- `GET /api/replay/session/{id}` - Get detailed replay data
- `GET /replay` - Replay dashboard page
- `GET /replay/{session-id}` - Specific session replay

### Replay Data Structure

```json
{
  "session_id": "abc-123-def",
  "player_name": "Alice",
  "faction": "southern",
  "actions": [
    {
      "sequence": 1,
      "action_type": "collect_resources",
      "trace_id": "trace-1",
      "span_id": "span-1",
      "span_links": [],  // First action has no links
      "timestamp": "2024-01-01T10:00:00Z",
      "location_id": "southern_capital"
    },
    {
      "sequence": 2,
      "action_type": "create_army", 
      "trace_id": "trace-2",
      "span_id": "span-2",
      "span_links": ["span-1"],  // Links to previous action
      "timestamp": "2024-01-01T10:01:00Z",
      "location_id": "southern_capital"
    }
  ],
  "span_link_chain": [
    {"sequence": 1, "valid_chain": true, "note": "First action"},
    {"sequence": 2, "valid_chain": true, "note": "Correctly links to action 1"}
  ]
}
```

## Querying Span Links

### In Grafana Tempo

Search for traces with game session information:
```
{game.session.id!=""}
```

Find spans with links:
```
{link.type="game_sequence"}
```

### Trace Attributes

Each span includes these attributes for game replay:
- `game.session.id` - Unique session identifier
- `game.action.type` - Type of action (move_army, create_army, etc.)
- `game.action.sequence` - Sequence number in the game
- `link.type` - Type of link (game_sequence)
- `link.relation` - Relationship (follows)

## Testing

Run the test script to verify span links are working:

```bash
cd game-of-tracing
python debug_span_links.py
```

This will:
1. Select a faction
2. Perform a sequence of actions
3. Each action will link to the previous one
4. Provide instructions for viewing the links in Grafana
5. Test battle calculation mechanics
6. Verify restart functionality

Test the replay functionality:

```bash
cd game-of-tracing
python war_map/replay.py
```

## Educational Value

Span links demonstrate:
- **Cross-trace relationships** - Actions in different traces can be related
- **Historical context** - Each action knows what came before it
- **Game narrative** - Complete story of how the game unfolded
- **Advanced OpenTelemetry** - Real-world use of span links feature
- **Tempo integration** - How to query and reconstruct trace relationships

## Game Replay Benefits

1. **Debugging** - Understand what led to game outcomes
2. **Analytics** - Analyze player behavior patterns
3. **Education** - Show distributed tracing concepts in action
4. **Auditing** - Verify game logic and fairness
5. **Entertainment** - Watch epic games unfold step by step

## Future Enhancements

Potential additions:
- AI action links to player actions that triggered them
- Battle outcome links to the actions that led to the battle
- Resource transfer chains across multiple locations
- Victory condition traces showing the sequence that led to game end
- Interactive replay UI with game map visualization
- Export replay data for external analysis 

## Troubleshooting Replay Functionality

### Tempo API Query Strategy

The replay system uses a **two-step approach** to work reliably with Tempo:

#### **Step 1: Discover Game Sessions**
Uses Tempo's tag values API to find all available game session IDs:
```bash
GET /api/v2/search/tag/game.session.id/values?start=<timestamp>&end=<timestamp>&limit=50
```

This returns all unique values for the `game.session.id` tag, giving us a list of available sessions.

#### **Step 2: Query Each Session**
For each discovered session ID, queries for its traces:
```bash
GET /api/search?q={game.session.id="specific-session-id"}&limit=100
```

This approach avoids complex TraceQL queries that might fail with 400 errors.

### Common Issues and Solutions

#### 1. Tempo Query Errors (400 Bad Request)

**Problem**: Getting 400 errors when querying Tempo with complex TraceQL

**Solutions**:
- **New approach**: Use tag values API first, then simple session-specific queries
- **Fallback**: System automatically falls back to local SQLite database
- **Logging**: Enhanced logging shows exactly which queries are being attempted

#### 2. Missing Span Attributes

**Problem**: Custom span attributes like `game.session.id` may not be indexed in Tempo

**Solutions**:
- **Attribute verification**: Check that spans are being created with correct attributes
- **Hybrid approach**: Local database stores action sequence as backup
- **Index configuration**: Ensure Tempo is configured to index custom attributes

#### 3. Time Range Issues

**Solutions**:
- **4-hour window**: System now uses 4-hour time windows for discovery
- **Unix timestamps**: Uses seconds-based timestamps for better compatibility
- **Configurable ranges**: Time ranges can be adjusted based on game session length

### Data Source Fallbacks

The replay system has multiple data sources in order of preference:

1. **`tempo_tag_values`** - Primary approach using tag values API
2. **`tempo_search_only`** - Basic span data from search results only  
3. **`local_db_fallback`** - SQLite database as final fallback

### Debug Tools

#### 1. Replay Debug Script
```bash
cd game-of-tracing
python debug_replay.py
```

This comprehensive script tests:
- Tempo connection and version
- Basic TraceQL query functionality  
- Game-specific attribute queries
- Replay API endpoints
- Local database fallback

#### 2. Manual Tempo Queries

Test Tempo directly using curl:

```bash
# Basic connectivity
curl http://localhost:3200/ready

# Simple trace search
curl "http://localhost:3200/api/search?q={span.name!=\"\"}&limit=5"

# Game-specific search
curl "http://localhost:3200/api/search?q={span.name=\"collect_resources\"}&limit=10"
```

#### 3. Replay API Testing

```bash
# Get available sessions
curl http://localhost:8080/api/replay/sessions

# Get specific session
curl http://localhost:8080/api/replay/session/your-session-id

# Check local database health
curl http://localhost:8080/api/debug/health
```

### Replay System Architecture

The improved replay system uses a **hybrid approach**:

#### 1. Primary Data Source: Tempo
- Queries Tempo using multiple TraceQL approaches
- Extracts complete span information including links
- Provides full distributed tracing context

#### 2. Fallback Data Source: Local SQLite
- Stores essential game action metadata
- Always available even if Tempo queries fail
- Enables replay functionality regardless of Tempo state

#### 3. Query Strategy
```python
# Multiple query attempts with increasing specificity
queries = [
    '{span.name="collect_resources" || span.name="create_army" || span.name="move_army" || span.name="all_out_attack"}',
    '{resource.service.name="war_map"}', 
    '{game.action.type!=""}',
    '{span.name!=""}'  # Fallback to any spans
]
```

### Performance Optimizations

#### 1. Time Window Optimization
- **Before**: 24-hour windows with nanosecond precision
- **After**: 1-hour windows with Unix second precision
- **Result**: Faster queries, reduced timeout errors

#### 2. Query Prioritization
- Try specific game queries first
- Fall back to broader queries if needed
- Use local database if all Tempo queries fail

#### 3. Response Caching
- Session metadata cached in local database
- Reduces repeated Tempo queries
- Improves UI responsiveness

### Access After Game Reset

The replay page is now accessible from the faction selection screen:

**Location**: [http://localhost:8080](http://localhost:8080) → "View Game Replays" button

**Benefits**:
- No need to be in an active game session
- Available immediately after game reset
- Persistent access to historical game data

### Expected Response Format

#### Successful Tempo Response
```json
{
  "success": true,
  "sessions": [
    {
      "session_id": "abc-123-def",
      "player_name": "Alice", 
      "faction": "southern",
      "start_time": 1234567890000000000,
      "action_count": 5,
      "last_action": "move_army"
    }
  ],
  "query_method": "tempo",
  "total_sessions": 1
}
```

#### Fallback Local Database Response
```json
{
  "success": true,
  "sessions": [...],
  "query_method": "local_db_fallback",
  "warning": "Tempo query failed: connection timeout"
}
```

### Tempo Configuration Requirements

For optimal replay functionality, ensure Tempo is configured with:

```yaml
# tempo-config.yaml
query_frontend:
  search:
    duration_slo: 5s
    throughput_bytes_slo: 1.073741824e+09

stream_over_http_enabled: true
```

And in docker-compose.yml:
```yaml
environment:
  - TEMPO_URL=http://tempo:3200
```

### TraceQL Query Examples

Based on the [Tempo API documentation](https://grafana.com/docs/tempo/latest/api_docs/), these queries should work:

#### Basic Queries
```traceql
# Find any spans with duration
{duration>1ms}

# Find spans by name
{span.name="collect_resources"}

# Find spans by service
{resource.service.name="war_map"}
```

#### Game-Specific Queries
```traceql
# Find game actions (if attributes are indexed)
{game.action.type!=""}

# Find player actions (if attributes are indexed)  
{player.name!=""}

# Combine conditions
{span.name="move_army" && player.faction="southern"}
```

### Integration with Grafana

Once the replay data is accessible, you can:

1. **View in Grafana Tempo**: Search for game session traces directly
2. **Create dashboards**: Visualize game progression over time
3. **Set up alerts**: Monitor for specific game events
4. **Analyze patterns**: Study player behavior across multiple games 