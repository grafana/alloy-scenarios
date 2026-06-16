# Build only what you need (minimal OTel Collector)

Grafana Alloy is a distribution of the OpenTelemetry Collector. The full `grafana/alloy` image bundles every component Alloy ships — Prometheus pipelines, Loki pipelines, dozens of OTel components, the Alloy UI, and more. That's convenient, but if all you need is "receive OTLP, batch it, forward OTLP," you're shipping a lot of code you'll never run.

This scenario shows how to build a collector that contains **only the parts you need**, using the [OpenTelemetry Collector Builder (OCB)](https://github.com/open-telemetry/opentelemetry-collector/tree/main/cmd/builder) — the same tool Alloy uses internally to generate its OTel engine.

The payoff: the image in this scenario is about **41 MB**, versus **~670 MB** for full `grafana/alloy:v1.17.0`.

## Why OCB and not "trim Alloy"

There is no build flag that slims the full Alloy (River) binary down to "just the OTel parts" — Alloy's `GO_TAGS` only toggle a few platform features. The OTel-native way to get a minimal collector is OCB: you declare the components you want in a manifest, and OCB generates and compiles a collector with exactly those.

Alloy does have an in-process, OCB-generated OTel engine you can run with `alloy otel`, but it is currently **experimental**, so this scenario uses standalone OCB. The result is a pure OpenTelemetry Collector — configured with an OTel **YAML** file, not Alloy River syntax.

## Overview

- **minimal-otel** — the collector built from [`builder-config.yaml`](builder-config.yaml). Pipeline: OTLP receiver → `memory_limiter` → `batch` → OTLP exporter (to Tempo) + `debug`.
- **Tempo** — stores the traces.
- **Grafana** — views the traces (Tempo datasource auto-provisioned).
- **telemetrygen** — the OpenTelemetry load generator, emits sample traces.

## Running the demo

From this directory:

```bash
docker compose up -d
```

The image versions in `docker-compose.yml` are pinned to the values in the repo-root `image-versions.env`. The first build runs OCB and compiles the collector (typically under a minute — far quicker than the fork-based scenarios in this directory).

Then open Grafana at [http://localhost:3000](http://localhost:3000), go to **Explore → Tempo**, and run a **Search** for service name `minimal-demo`.

## What to expect

- The collector logs each batch via the `debug` exporter:

  ```
  info  Traces  {"otelcol.component.id": "debug", "otelcol.signal": "traces", "resource spans": 1, "spans": 2}
  ```

- Traces from service `minimal-demo` appear in Tempo. You can confirm from the CLI:

  ```bash
  curl -s "http://localhost:3200/api/search?tags=service.name%3Dminimal-demo&limit=3"
  ```

- See the size difference for yourself:

  ```bash
  docker images | grep -E "minimal-otel|grafana/alloy"
  ```

- Inspect exactly which components were compiled in:

  ```bash
  docker run --rm $(docker compose images -q minimal-otel) components
  ```

## How the build works

[`Dockerfile`](Dockerfile) is a two-stage build:

1. **build stage** (`golang:1.25` — OCB v0.147.0 requires Go ≥ 1.25): runs
   `go run go.opentelemetry.io/collector/cmd/builder@<OCB_VERSION> --config builder-config.yaml`,
   which generates the collector's `main` package and compiles a static binary.
2. **runtime stage** (`distroless/static`): copies just the binary in.

[`builder-config.yaml`](builder-config.yaml) is the manifest. To add a capability, add a `gomod` line under the right section and rebuild — for example, to also write metrics to Prometheus you'd add `go.opentelemetry.io/collector/exporter/otlphttpexporter` or a contrib exporter. Versions are pinned to the OpenTelemetry release that Alloy v1.17.0 ships (unstable `v0.147.0`, stable `v1.53.0`).

## Customizing

- **Different signals**: this manifest builds a traces pipeline, but the OTLP receiver and exporter handle metrics and logs too — add `metrics:` / `logs:` pipelines in [`config.yaml`](config.yaml).
- **More components**: browse the [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector) and [collector-contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib) repos, add the `gomod` to `builder-config.yaml`, and rebuild.
