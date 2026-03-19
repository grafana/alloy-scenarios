# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a collection of self-contained demonstration scenarios for **Grafana Alloy**, the telemetry collection and processing pipeline. Each scenario lives in its own top-level directory and showcases a specific monitoring use case using the **LGMT stack** (Loki, Grafana, Metrics/Prometheus, Tempo).

## Running Scenarios

```bash
# Option 1: Direct (uses default image versions in docker-compose.yml)
cd <scenario-dir> && docker compose up -d

# Option 2: Centralized image versions (from repo root)
./run-example.sh <scenario-dir>

# Stop a scenario
cd <scenario-dir> && docker compose down
```

Image versions are centralized in `image-versions.env` at the repo root. Docker-compose files reference these via `${VAR:-default}` syntax.

Kubernetes scenarios (under `k8s/`) use Helm charts instead of Docker Compose — see their individual READMEs.

## Scenario Structure

Every Docker-based scenario follows this layout:

```
scenario-name/
├── docker-compose.yml      # LGMT stack + Alloy (infrastructure only)
├── docker-compose.coda.yml # Demo app services (run via coda CLI or -f flag)
├── config.alloy             # Alloy pipeline configuration (River/HCL syntax)
├── loki-config.yaml         # Loki backend config
├── prom-config.yaml         # Prometheus backend config
├── tempo-config.yaml        # Tempo config (if tracing is involved)
├── README.md                # What the scenario demonstrates and how to use it
└── app/                     # Optional demo application (typically Python/Flask)
```

## Alloy Configuration Language

`config.alloy` files use Alloy's River syntax (HCL-like). Pipelines follow a consistent pattern:

1. **Receivers/Sources** — ingest data (`loki.source.*`, `otelcol.receiver.*`, `prometheus.exporter.*`)
2. **Processors/Transformers** — parse, relabel, batch (`loki.process.*`, `discovery.relabel`, `otelcol.processor.*`)
3. **Writers/Exporters** — send to backends (`loki.write.*`, `prometheus.remote_write.*`, `otelcol.exporter.*`)

Components are wired together by passing outputs to inputs (e.g., `forward_to = [loki.write.default.receiver]`).

## Creating a New Scenario

Templates exist in `.cursor/docker-example.mdc` (Docker) and `.cursor/k8s-example.mdc` (Kubernetes) with full boilerplate for all config files.

Checklist for a new scenario:
1. Create a new top-level directory named after the scenario
2. Include `docker-compose.yml`, `config.alloy`, backend configs, and `README.md`
3. Use `${VAR:-default}` for image versions matching `image-versions.env` keys
4. Grafana service should auto-provision datasources via entrypoint script (see template)
5. Add the scenario to the main `README.md` table
6. Alloy UI is available at `http://localhost:12345` for debugging pipelines

## Key Conventions

- Grafana runs on port 3000 with anonymous admin auth enabled (no login required)
- Alloy HTTP server runs on port 12345
- Python demo apps use OpenTelemetry SDK for instrumentation (`telemetry.py` pattern)
- Backend configs (loki, prometheus, tempo) are minimal single-instance dev configs — not production-ready
