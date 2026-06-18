# Microsoft SQL Server Monitoring with Grafana Alloy

This scenario demonstrates how to monitor Microsoft SQL Server using Grafana Alloy's `prometheus.exporter.mssql` component, including a custom `query_config` for application-specific metrics. Alloy scrapes SQL Server metrics and remote-writes them to Prometheus, which Grafana queries for visualization.

The interesting part is the custom `query_config`: the argument **replaces** the exporter's built-in collector rather than extending it, so `mssql-queries.yaml` embeds the [upstream default collector](https://github.com/grafana/alloy/blob/main/internal/static/integrations/mssql/collector_config.yaml) as its base — connections, batch requests, IO stalls, buffer cache, log growths, and more — and appends two custom metrics at the end (per-file database sizes and a demo table row count).

A small load generator creates a `demo` database and inserts one row per second, so the custom metric keeps climbing.

## Prerequisites

- Docker and Docker Compose installed
- ~2 GB of free memory for the SQL Server container
- The `mcr.microsoft.com/mssql/server` image is amd64-only. The compose file sets `platform: linux/amd64` so it runs on Apple Silicon, but on a Mac you must also switch Docker Desktop to Rosetta emulation first — see [Apple Silicon (M-series Macs)](#apple-silicon-m-series-macs) below.

### Apple Silicon (M-series Macs)

SQL Server is an amd64-only binary. The `platform: linux/amd64` line in the compose file only tells Docker which image to pull — it does **not** choose how that image is emulated. Docker Desktop's default emulator (QEMU) **crashes SQL Server on startup**: the `mssql` container exits with code `139` and the logs show:

```
qemu: uncaught target signal 11 (Segmentation fault) - core dumped
```

Because `mssql-load` and `alloy` use `depends_on: condition: service_healthy`, they then report `dependency mssql failed to start` — that message is the gate working correctly, not a bug in the scenario; the real failure is the SQL Server crash above.

To fix it, switch Docker Desktop to Apple's Rosetta emulation (one-time setting):

1. **Docker Desktop → Settings → General**.
2. Enable **Use Virtualization framework**.
3. Enable **Use Rosetta for x86_64/amd64 emulation**.
4. **Apply & restart** Docker Desktop, then `docker compose up -d` again.

Rosetta runs the amd64 SQL Server binary reliably; QEMU does not. Intel Macs, Linux, and Windows on x86_64 run the image natively and need none of this.

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/mssql-monitoring
docker compose up -d
```

SQL Server takes up to a minute to initialize on first boot; the other services wait for its healthcheck.

## Access Points

| Service    | URL                       |
|------------|---------------------------|
| Grafana    | http://localhost:3000     |
| Alloy UI   | http://localhost:12345    |
| Prometheus | http://localhost:9090     |
| SQL Server | `localhost,1433` (sa / `Alloy-Demo-Pass123!`) |

## What to Expect

Open Grafana at http://localhost:3000, navigate to **Explore**, select the **Prometheus** datasource, and try these queries:

| What you're watching | Query |
|----------------------|-------|
| Database file sizes (custom query) | `mssql_database_filesize{db="demo"}` |
| Demo table row count (custom query, +1/sec) | `mssql_demo_events_rows` |
| Batch request throughput | `rate(mssql_batch_requests_total[1m])` |
| Open connections per database | `mssql_connections` |
| IO stall time by database | `rate(mssql_io_stall_seconds_total[5m])` |

`mssql_demo_events_rows` climbing one row per second — driven by the `mssql-load` container — is the scenario's success signal, together with `mssql_database_filesize` reporting every database file.

You can also inspect the Alloy pipeline at http://localhost:12345 to verify that the exporter, scrape, and remote write components are healthy. Live debugging is enabled for real-time pipeline inspection.

## How the Connection String Is Handled

The exporter's `connection_string` argument is an Alloy **secret**. The compose file passes it to the Alloy container as an environment variable and `config.alloy` reads it with `sys.env("MSSQL_CONNECTION_STRING")` — strings coerce into secrets one-way, so the credential never appears in the configuration file and the Alloy UI redacts it.

> **Production note:** for real deployments, source the connection string from a secret store instead of the compose file — see the [vault-secrets](../vault-secrets/) scenario for fetching credentials at runtime with `remote.vault`. A least-privilege monitoring login (rather than `sa`) needs `VIEW SERVER STATE` for the default collector's DMV queries.

## Customizing the Queries

`mssql-queries.yaml` holds the custom collector in the [sql_exporter](https://github.com/burningalchemist/sql_exporter) collector format. Add your own entries under `metrics:` — each needs a `metric_name`, `type`, `help`, optional `key_labels`, the `values` column(s), and the T-SQL `query`. Restart Alloy (or wait for `local.file` to re-read) and the new series appear in Prometheus.

## Stopping the Scenario

```bash
docker compose down
```
