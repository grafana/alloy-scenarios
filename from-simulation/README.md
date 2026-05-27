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

## Repository

Return to the [main repo README](../README.md) for the full scenario index.
