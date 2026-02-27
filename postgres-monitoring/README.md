# PostgreSQL Monitoring with Grafana Alloy

This scenario demonstrates how to monitor a PostgreSQL database using Grafana Alloy's built-in `prometheus.exporter.postgres` component. Alloy scrapes PostgreSQL server metrics and forwards them to Prometheus via remote write. Grafana is pre-configured with Prometheus as a datasource so you can explore the collected metrics immediately.

## Prerequisites

- Docker
- Docker Compose
- Git

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/postgres-monitoring
docker compose up -d
```

To use the centralized image versions from the repo root:

```bash
cd alloy-scenarios
./run-example.sh postgres-monitoring
```

## Access Points

| Service    | URL                        |
|------------|----------------------------|
| Grafana    | http://localhost:3000      |
| Alloy UI   | http://localhost:12345     |
| Prometheus | http://localhost:9090      |

Grafana is configured with anonymous admin access enabled, so no login is required.

## What to Expect

Once the stack is running, Alloy connects to the PostgreSQL instance and begins collecting metrics via the `prometheus.exporter.postgres` component. These metrics are scraped every 15 seconds and forwarded to Prometheus.

Metrics you can explore in Grafana include:

- **pg_up** -- Whether the PostgreSQL instance is reachable
- **pg_stat_database_*/** -- Database-level statistics (transactions committed, rolled back, rows fetched, inserted, updated, deleted, deadlocks, temp files, etc.)
- **pg_stat_bgwriter_*/** -- Background writer statistics (buffers written, checkpoints, etc.)
- **pg_settings_*/** -- PostgreSQL server configuration settings exposed as metrics
- **pg_stat_activity_*/** -- Connection and session activity
- **pg_locks_*/** -- Lock statistics by mode

### Exploring Metrics

1. Open **Grafana** at http://localhost:3000
2. Go to **Explore** and select the **Prometheus** datasource
3. Search for metrics starting with `pg_` to browse all available PostgreSQL metrics

### Debugging the Pipeline

1. Open the **Alloy UI** at http://localhost:12345
2. Navigate to the component graph to see the pipeline: `prometheus.exporter.postgres` -> `prometheus.scrape` -> `prometheus.remote_write`
3. Use the **Live Debugging** feature (enabled in the config) to inspect data flowing through each component

## Stopping the Scenario

```bash
docker compose down
```
