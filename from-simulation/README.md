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

## Repository

Return to the [main repo README](../README.md) for the full scenario index.
