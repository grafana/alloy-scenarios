# From — A simulation-driven telemetry scenario

> A small, dread-soaked town runs forever. People hide indoors at dusk. Creatures crawl out of the forest. Sometimes the town falls and a new cycle begins. Every tick emits OpenTelemetry traces, metrics, logs, and continuous profiles into Grafana Alloy — so you can debug a *living* system instead of a synthetic load generator.

## What this scenario demonstrates

- A long-running Python simulation (`from-sim`) that produces traces, metrics, logs, and Pyroscope profiles in a coordinated, story-driven way.
- A full LGMT + Pyroscope stack wired through Alloy, configured to receive OTLP/HTTP and OTLP/gRPC.
- A live web map (the **Fromville** UI) so you can see the simulation events that produced the telemetry you're querying in Grafana.
- Optional Claude-driven narration when `ANTHROPIC_API_KEY` is set — the LLM only colours flavour text and never affects deterministic simulation outcomes.

## Run it

```bash
# from this directory
docker compose up -d

# or, from the repo root, with pinned image versions:
./run-example.sh from-simulation
```

Tear down:

```bash
docker compose down
```

## Endpoints

| Service        | URL                                    | Notes                                            |
| -------------- | -------------------------------------- | ------------------------------------------------ |
| Fromville UI   | <http://localhost:8080>                | Live map, event log, roster, stats               |
| Snapshot JSON  | <http://localhost:8080/api/snapshot>   | Curl-friendly dump of the current world         |
| Health probe   | <http://localhost:8080/health>         | `{"ok": true, "tick": ...}`                      |
| Grafana        | <http://localhost:3000>                | Anonymous Admin; no login                        |
| Alloy UI       | <http://localhost:12345>               | Pipeline debug graph                             |
| Prometheus     | <http://localhost:9090>                | Direct PromQL                                    |
| Tempo          | <http://localhost:3200>                | Tempo API                                        |
| Loki           | <http://localhost:3100>                | Loki API                                         |
| Pyroscope      | <http://localhost:4040>                | Continuous profiling                             |

## Environment variables

All variables are optional — defaults are in `docker-compose.yml` and `app/contracts.py::Config.from_env`.

| Variable                          | Default                | Purpose                                                |
| --------------------------------- | ---------------------- | ------------------------------------------------------ |
| `TICK_HZ`                         | `2.0`                  | Simulation ticks per real second                       |
| `TIME_SCALE`                      | `1.0`                  | Sim-minutes advanced per tick                          |
| `SEED`                            | unset                  | RNG seed for deterministic runs                        |
| `ANTHROPIC_API_KEY`               | unset                  | When set, enables Claude-driven narration              |
| `LLM_MODEL`                       | `claude-haiku-4-5`     | Anthropic model id                                     |
| `LLM_DECISION_RATE`               | `0.05`                 | Per-character probability of an LLM decision per tick  |
| `LLM_YELLOW_RATE`                 | `0.25`                 | Probability the Yellow Man dialogue is LLM-driven      |
| `LLM_MIN_TICK_GAP`                | `30`                   | Minimum ticks between LLM calls per actor              |
| `LLM_GLOBAL_RPM`                  | `6`                    | Hard cap on Anthropic API calls per minute             |
| `NPC_FLOOR`                       | `18`                   | Refill NPCs to at least this many active               |
| `RESURRECTION_BASE_TICKS`         | `700`                  | Mean ticks before a dead character returns             |
| `RESURRECTION_JITTER`             | `150`                  | Uniform jitter around the resurrection mean            |
| `RECOGNITION_THRESHOLD`           | `3`                    | Witness count for "I know who you are" recognition     |
| `YELLOW_APPEARANCE_DAYS_MIN`      | `5`                    | Min sim-days between Yellow Man appearances            |
| `YELLOW_APPEARANCE_DAYS_MAX`      | `10`                   | Max sim-days between Yellow Man appearances            |
| `YELLOW_IMPOSTER_PROB`            | `0.7`                  | Probability the Yellow Man arrives in IMPOSTER mode    |
| `YELLOW_DEADLINE_TICKS`           | `1500`                 | Ticks the town has to identify the imposter            |
| `LOG_LEVEL`                       | `INFO`                 | Python root logger level                               |
| `OTEL_EXPORTER_OTLP_ENDPOINT`     | `http://alloy:4318`    | OTLP/HTTP endpoint for logs + metrics                  |
| `PYROSCOPE_SERVER_ADDRESS`        | `http://alloy:9999`    | Pyroscope push endpoint                                |
| `SERVICE_NAME`                    | `from-sim`             | Resource service.name attribute                        |
| `PERSONALITY_DRIFT_RATE`          | `0.04`                 | How fast a survivor's personality traits drift per cycle |
| `JOURNAL_FRAGMENT_SURVIVAL_PROB`  | `0.6`                  | Per-fragment chance a journal line survives a wipe     |
| `DREAM_TRIGGER_SANITY_THRESHOLD`  | `40.0`                 | Sanity ceiling below which a sleeping character may dream |
| `DREAM_TRIGGER_PROB`              | `0.08`                 | Per-eligible-sleep chance of starting a dream          |
| `DREAM_DURATION_TICKS`            | `30`                   | How long a single dream lasts                          |
| `BUS_ARRIVAL_CYCLE_INTERVAL`      | `5`                    | Cycles between bus arrivals                            |
| `BUS_STAY_TICKS`                  | `1440`                 | Ticks the bus parks in town before departing           |
| `YELLOW_HYDRA_MIN`                | `2`                    | Minimum simultaneous Yellow Man tendrils in IMPOSTER mode |
| `YELLOW_HYDRA_MAX`                | `3`                    | Maximum simultaneous Yellow Man tendrils               |
| `LIGHTHOUSE_CALL_TICK_FRAC`       | `0.4`                  | Fraction of NIGHT after which the lighthouse may call  |
| `TRUST_BASELINE`                  | `0.5`                  | Initial pairwise trust value between characters        |
| `MIND_REFLECT_EVERY_TICKS`        | `600`                  | Cadence per named character for the Mind's reflection pass (≈5 sim-min) |
| `MIND_GOAL_TTL_ticks`             | `3600`                 | How long an active goal lives before it expires        |
| `MIND_NPC_ENABLED`                | `true`                 | When `true`, NPCs run the lightweight `NpcMind` (no LLM cost) |
| `LLM_THINKING_RPM`                | `2`                    | Reserved RPM slice for "thinking" LLM calls (Yellow Man tactics, belief flavour); split off the global RPM |
| `DETERMINISTIC_MODE`              | `false`                | When `true`, every LLM `maybe_*` returns None so `SEED` runs are byte-identical |

### Optional LLM narration

If you want the Claude narration channel, export your key in a `.env` file next to `docker-compose.yml`:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
docker compose up -d
```

Without a key the simulation runs in pure deterministic mode and the **Narration** panel in the UI stays hidden — every event is still produced, just without flavour prose.

## Screenshots

> _Placeholder — capture these once the stack runs end-to-end:_
>
> - `img/fromville-map.png` — full UI with day phase
> - `img/fromville-night.png` — UI with night phase and creature breach
> - `img/grafana-overview.png` — Grafana dashboard view

## v2 features

The second iteration adds cross-cycle memory, dreams, outsiders, and the lighthouse — six surfaces visible in the Fromville UI in addition to everything from v1.

### Khatri's Journal (right column, sepia panel)

Each cycle, characters jot fragments of village history into a shared Legacy. When the town falls and a new cycle begins, a fraction of fragments survive (controlled by `JOURNAL_FRAGMENT_SURVIVAL_PROB`) — their text is preserved but increasingly "burned": the higher a fragment's `burned` value, the more transparent its line in the journal panel. The HUD also surfaces `cycles_witnessed` ("Cycle N of all that has ever been") and a small "fragments" indicator.

### Building hash marks

Every time a creature breaches a building, a tally mark is etched into Legacy under that building's id. The UI renders up to twelve tally lines (groups of four with a diagonal slash) at the building's southeast corner; anything beyond twelve is summarised as "+N". These marks survive village wipes, so a building's scar count grows across cycles.

### The Bus and Outsiders

Periodically (every `BUS_ARRIVAL_CYCLE_INTERVAL` cycles) a yellow school bus drives in along the western dirt road, parks near the diner, and drops off "outsider" agents who pursue their own backstory goals for `BUS_STAY_TICKS` ticks before the bus departs east. Outsiders render as pale-gold dots with a "+" glyph above them; while the bus is in town, a yellow-bordered Bus panel lists each passenger with their backstory snippet and a countdown to the next arrival cycle. The SVG map gains continuation dirt-road segments at both edges so the bus path looks like it joins the existing oval.

### Yellow Man hydra (tendrils)

The Yellow Man is no longer a single imposter — in IMPOSTER mode he is now a small set of NPCs (between `YELLOW_HYDRA_MIN` and `YELLOW_HYDRA_MAX`). Every member of `payload.yellow.tendrils` gets a slow-pulsing mustard ring; the disguise leader (`yellow.disguised_as`) gets a brighter, faster ring. The town must identify all of them before the deadline.

### Dreams and dream-mode

When a sleeping character's sanity is below `DREAM_TRIGGER_SANITY_THRESHOLD`, they may begin to dream (`DREAM_TRIGGER_PROB` per eligible tick). Each active dream renders a small green-serif dialog box next to the dreamer with the latest one or two visitor lines, and the whole map shifts into "dream mode" — a hue-rotated, desaturated tint that returns to normal when no dreams are active. Dream lines that match certain trigger events become prophecies in Legacy that may fire one cycle later.

### Lighthouse call

Late in NIGHT (after `LIGHTHOUSE_CALL_TICK_FRAC` of the phase), the lighthouse may call a single character: they receive a slow aqua pulsing ring on the map and bias toward walking down to the lighthouse. When the call is active and the lighthouse's voice is heard, the "Voice from the Lighthouse" panel becomes visible — a black-background monospace radio that prints the rolling last ten `lighthouse_voice` event details with a CRT-style scanline twitch.

### Stability notes for v2 UI

- All v2 panels read snapshot fields **only**: `payload.legacy`, `payload.dreams`, `payload.bus`, `payload.lighthouse`, `payload.yellow.tendrils`. No new client/server contract is required beyond `snapshot_dict`.
- The dream overlay, hash-mark groups, ring overlays, bus group, and outsider glyphs are all reused between ticks — they are created on demand and torn down only when the corresponding world state stops emitting them, so per-tick render cost stays near v1.

### v3 — hand-drawn map & character tokens

The map is now the **Claude Design hand-drawn Fromville** — a paper-stock meadow inside a dark forest ring with a single S-curve highway, internal dirt streets, three Faraway/Bottle Trees, a rotating lighthouse beam, and all 18 numbered township buildings (forest scatter is generated client-side from a seeded RNG so it stays consistent across sessions). A new **Township Index** side panel lists every building with its number, mini-icon, and name; the five talisman-protected buildings — **Colony House, Clinic, Church, Sheriff's Office, Matthews' Home** — are marked with a ★. Named characters now render as hand-drawn 60×80 token sprites (one `<symbol>` per character, dropped onto the map via `<use href="#token-{name}">`), and the Man in Yellow / Boy in White get their own distinct tokens. Building windows glow at DUSK and NIGHT and a radial-gradient overlay deepens the village in dream-time.

### v9 — cognitive layer (Mind + AI Director)

Named characters and (lightweight) NPCs now run a four-layer cognitive stack
between the existing weighted-FSM and the optional LLM picker:

1. **Memory stream** — retrieves recent `character_memory` rows scored by
   recency × importance × structural relevance (deterministic; no embeddings).
2. **Beliefs** — every `MIND_REFLECT_EVERY_TICKS` ticks each named character
   clusters their recent memories and emits up to three typed beliefs
   (`house_weak:X`, `yellow_suspect:Y`, `loss:Z`, …) that are persisted as
   `character_memory` rows with `kind = "belief"` so they survive restart.
3. **Goals** — a deterministic rule table maps beliefs + drives to one active
   `Goal` per agent (`PROTECT_X`, `INVESTIGATE_X`, `REVENGE_X`, `FLEE_TO_Y`,
   `FIND_ITEM_Z`). Open/close are recorded in memory.
4. **Plan** — the active goal adds additive weight deltas onto the existing
   FSM menu; the weighted-FSM choice still runs last, so `SEED`-pinned runs
   stay deterministic.

A world-level **AI Director** (`app/agents/director.py`) reads town tension
(fear/sanity averages, food ratio, recent breach rate, yellow deadline) and
tunes three knobs each tick:

- `spawn_rate_mult` — creature cohort size at dusk
- `yellow_appearance_bias` — added to `YELLOW_IMPOSTER_PROB`
- `target_bias` — softmax over `legacy.building_breach_marks` and the new
  `legacy.talisman_failure_count` so historically weak buildings draw the
  next wave (creatures *learn* across cycles).

The **Yellow Man** is now actively strategic — tendril NPCs are chosen by an
"awareness × social-load" weight, and `LURE_OUTSIDE` prefers homes of
load-bearing roles (SHERIFF / CARETAKER / PRIEST). The previously-broken LLM
hook (`yellow_man.py:_consult_llm`) is wired to a generic
`LLMDecider.maybe_pick_string` on its own thinking-budget bucket so reflection
and tactical calls never starve the state-choice budget.

Visibility:

- HUD bar gains a **Minds** cell — Director pressure (0..1 with a colour
  gradient), goal-mix pips by kind, and the live belief count.
- Dossier panel adds a **Mind** section: active goal + top-3 beliefs with
  confidence bars, plus a reflection counter.
- OTel spans (`mind.recall`, `mind.reflect`, `mind.regoal`, `mind.shape_menu`,
  `director.recalc`, `yellow.target_select`) and metrics
  (`from_sim_director_pressure`, `from_sim_director_spawn_mult`,
  `from_sim_mind_beliefs_active`, `from_sim_mind_goals_active{kind}`,
  `from_sim_mind_reflections_total`, `from_sim_yellow_target_role{role}`,
  plus a new `purpose` label on `from_sim_llm_calls_total`).

LLM budget is split: 4 RPM for state-choice + `LLM_THINKING_RPM` (default 2)
for thinking. With `ANTHROPIC_API_KEY` unset, or `DETERMINISTIC_MODE=true`,
every cognitive op falls back to the deterministic path.

### v9.1 — pressure-equilibrium pass

Tuning pass on top of v9 to make monsters actually suppress survivor growth
rather than the user reducing arrivals. Key changes:

- Dusk creature cohort cap raised (12 → 20) and population scaling steepened
  (one extra per 8 living agents instead of 12).
- Cave spawner activates at DUSK as well as NIGHT, runs on a 60-tick cadence
  (was 90), and the soft cap rises 8 → 14.
- New mid-NIGHT wave (`creatures.tick_night_wave`) drops a half-strength
  cohort once per simulated night so cohort depletion no longer empties the
  map between dusk and dawn.
- Stalker creatures multi-kill (up to 3 prey before retreating); swarmers
  keep single-prey behaviour. A `creature_kill_streak` event fires on the
  second catch so rampages are visible in the journal.
- Hunt geometry: radius 110 → 150 (overcrowded 180 → 240), catch box 12 →
  14, chase speed bonus 0.4 → 0.6.
- `NPC_BREACH_DEATH_PROB` default 0.30 → 0.50 so getting through a door
  matters.
- AI Director gains a **population-stress** input: once live population
  crosses ~1.5× `NPC_FLOOR`, it subtracts from the raw pressure score
  (capped at 0.4), pushing the Director toward escalation. The spawn-mult
  ceiling also rises 1.4× → 1.6×, so a thriving town gets a max cohort of
  ~32 creatures.
- HUD minds cell gains a `PS` pip alongside Director pressure; the dossier
  is unchanged.

New metrics: `from_sim_director_population_stress` (gauge),
`from_sim_creatures_night_waves_total` (counter).
New events: `creature_night_wave`, `creature_kill_streak`.

The whole pass is deterministic with `SEED` set, and `DETERMINISTIC_MODE`
still disables every LLM call.

## Repository

Return to the [main repo README](../README.md) for the full scenario index.
