# Log Secret Filtering

Demonstrates how Grafana Alloy's `loki.secretfilter` component automatically redacts secrets from log lines before they reach Loki.

## Overview

A Python application continuously writes log lines -- some containing fake secrets (AWS keys, database connection strings, GitHub tokens, JWTs, Slack webhooks) -- to a shared log file. Alloy tails the file, passes every line through `loki.secretfilter` using built-in Gitleaks patterns, and forwards the sanitized output to Loki. By the time logs appear in Grafana, sensitive values have been replaced with `<REDACTED:$SECRET_NAME>`.

The example includes:

- **secret-logger** -- Python app that emits a mix of normal and secret-containing log lines every 2 seconds.
- **Alloy** -- Tails the log file, applies `loki.secretfilter`, and pushes to Loki. Runs with `--stability.level=experimental` because `loki.secretfilter` is an experimental component.
- **Loki** -- Stores the redacted logs.
- **Grafana** -- Visualize and query logs to verify secrets have been removed.

## Running the Demo

1. Clone the repository:
   ```
   git clone https://github.com/grafana/alloy-scenarios.git
   cd alloy-scenarios
   ```

2. Navigate to this example directory:
   ```
   cd log-secret-filtering
   ```

3. Run using Docker Compose:
   ```
   docker compose up -d
   ```

   Or use the centralized image management:
   ```
   cd ..
   ./run-example.sh log-secret-filtering
   ```

4. Access Grafana at [http://localhost:3000](http://localhost:3000)

## What to Expect

1. Open Grafana and navigate to **Explore**.
2. Select the **Loki** datasource.
3. Run the query `{job="secret-app"}`.
4. You should see log lines where secrets have been replaced, for example:
   - `Found config: <REDACTED:aws-access-token> with secret`
   - `Database connection: <REDACTED:generic-api-key>`
   - Normal log lines (health checks, request timings) pass through unchanged.

## Architecture

```
┌─────────────────┐      ┌───────────────────────────────────────┐      ┌──────┐      ┌─────────┐
│  secret-logger  │─────▶│  Alloy                                │─────▶│ Loki │─────▶│ Grafana │
│  (writes logs)  │ file │  local.file_match ─▶ loki.source.file │ push │      │ query│         │
└─────────────────┘      │       ─▶ loki.secretfilter ─▶ loki.write     │      │      │         │
                         └───────────────────────────────────────┘      └──────┘      └─────────┘
```

## Alloy Pipeline

The `config.alloy` pipeline:

1. `local.file_match` -- discovers log files at `/tmp/logs/*.log`.
2. `loki.source.file` -- tails matched files and forwards log entries.
3. `loki.secretfilter` -- scans each log line against Gitleaks secret patterns and replaces matches with `<REDACTED:$SECRET_NAME>`.
4. `loki.write` -- pushes sanitized logs to Loki.

Visit the Alloy UI at [http://localhost:12345](http://localhost:12345) to inspect the running pipeline and use the live debugging view.
