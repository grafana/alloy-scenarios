# Promtail to Alloy Migration

This scenario is a side-by-side migration playbook: the same log file is tailed by **Promtail** (using `promtail-config.yaml`) and by **Alloy** (using `config.alloy`, derived with `alloy convert`), and both ship to the same Loki instance. Query Loki for either pipeline and you get identical log lines with identical labels — only the `collector` label differs.

[Promtail reached end of life on March 2, 2026](https://grafana.com/docs/loki/latest/send-data/promtail/): commercial support has ended and no future updates will be provided. [Grafana Alloy](https://grafana.com/docs/alloy/latest/) is its successor, and `alloy convert` automates most of the migration.

## Prerequisites

- Docker and Docker Compose installed

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/promtail-to-alloy-migration
docker compose up -d
```

## Access Points

| Service  | URL                    |
|----------|------------------------|
| Grafana  | http://localhost:3000  |
| Alloy UI | http://localhost:12345 |
| Loki     | http://localhost:3100  |

## Configuration Mapping

Every block in `promtail-config.yaml` maps to an Alloy component in `config.alloy` (both files carry matching comments):

| Promtail | Alloy | Notes |
|----------|-------|-------|
| `server:` | — | Alloy's HTTP server is a CLI flag (`--server.http.listen-addr`); no config block needed |
| `positions:` | — | Read offsets live in Alloy's `--storage.path` automatically. The converter also emits `legacy_positions_file` so an in-place migration resumes exactly where Promtail stopped |
| `clients.url` | `loki.write` → `endpoint.url` | Same push endpoint |
| `clients.external_labels` | `loki.write` → `external_labels` | This scenario uses it to tag the collector |
| `scrape_configs.static_configs` + `__path__` | `local.file_match` → `path_targets` | Static labels ride along on the target |
| file tailing (implicit) | `loki.source.file` | Both add the `filename` label automatically |
| `pipeline_stages: - regex` | `loki.process` → `stage.regex` | Identical regex syntax |
| `pipeline_stages: - labels` | `loki.process` → `stage.labels` | Identical label promotion |

## Run the Converter Yourself

Reproduce the conversion with:

```bash
docker run --rm -v "$(pwd)":/work grafana/alloy:v1.16.1 \
  convert --source-format=promtail --output=/work/converted.alloy /work/promtail-config.yaml
```

The committed `config.alloy` is semantically equivalent to the converter's output with a few deliberate differences, so the two are worth diffing:

* The converter inlines the targets on `loki.source.file` with a `file_match { enabled = true }` block; the committed config uses the equivalent — and more common — `local.file_match` component.
* The converter emits `legacy_positions_file = "/tmp/positions.yaml"` so a real migration picks up exactly where Promtail's positions file left off. This scenario omits it: both collectors deliberately read the file from the beginning so their output can be compared.
* `external_labels` is changed from `collector = "promtail"` to `collector = "alloy"` — that label is how you tell the two pipelines apart in Loki.

## Verify the Pipelines Are Equivalent

Open Grafana at http://localhost:3000, navigate to **Explore**, select the **Loki** datasource, and compare:

```logql
{job="demo-app", collector="promtail"}
```

```logql
{job="demo-app", collector="alloy"}
```

Both return the same lines with the same `job`, `level`, `service`, and `filename` labels. To watch them track each other:

```logql
sum by (collector) (count_over_time({job="demo-app"}[1m]))
```

The two series sit on top of each other — that's the migration proof.

## What to Expect

The `log-generator` container writes one structured logfmt line per second:

```
2026-06-11T10:00:00Z level=INFO service=payments msg="processed order 1000 in 20ms"
```

Both collectors tail `/var/log/demo/app.log` (mounted read-only at the same path in each container so the `filename` label matches), extract `level` and `service` as labels with a regex pipeline, and push to Loki with their own `collector` external label.

You can also inspect the Alloy side of the migration at http://localhost:12345 — live debugging is enabled, so you can watch `loki.process` parse lines in real time.

## Stopping the Scenario

```bash
docker compose down
```
