# Microsoft SQL Server monitoring

This scenario shows how to monitor Microsoft SQL Server with the Alloy `prometheus.exporter.mssql` component.
Alloy runs T-SQL queries through the bundled `sql_exporter` integration, scrapes the resulting metrics every 15 seconds, and remote-writes them to Prometheus for visualization in Grafana.
The `query_config` argument **replaces** the exporter's built-in collector rather than extending it, so `mssql-queries.yaml` embeds the [upstream default collector](https://github.com/grafana/alloy/blob/main/internal/static/integrations/mssql/collector_config.yaml) as its base, including connections, batch requests, IO stalls, buffer cache, and log growths, and appends two custom metrics at the end: per-file database sizes and a demo table row count.
A `mssql-load` sidecar creates a `demo` database and inserts one row per second so the custom row-count metric keeps climbing.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- About 2 GB of free memory for the SQL Server container.
- Ports 1433 for SQL Server, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy free on the host.
- On Apple Silicon Macs, Docker Desktop must use Rosetta for amd64 emulation. Refer to [Apple Silicon hosts need Rosetta emulation](#apple-silicon-hosts-need-rosetta-emulation) if SQL Server exits on startup.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

Both this scenario and [mysql-monitoring](../mysql-monitoring/) scrape a relational database with a Prometheus exporter and remote write.
MySQL uses the built-in collector only.
SQL Server adds a custom `query_config` loaded from `mssql-queries.yaml` and a load generator that drives application-specific metrics.

| Topic          | [mysql-monitoring](../mysql-monitoring/) | This scenario                                                  |
| -------------- | ---------------------------------------- | -------------------------------------------------------------- |
| Exporter       | `prometheus.exporter.mysql`              | `prometheus.exporter.mssql`                                    |
| Custom queries | Built-in collector only                  | `query_config` replaces the default collector                  |
| Demo workload  | None                                     | `mssql-load` inserts one row per second into `demo.dbo.events` |
| Success signal | `mysql_up` and standard status metrics   | `mssql_demo_events_rows` increases about once per second       |

## Understand the architecture

```text
+-------------+     +------------+     +-------+     +------------+     +---------+
| mssql-load  |---->| SQL Server |<----| Alloy |---->| Prometheus |---->| Grafana |
+-------------+     +------------+     +-------+     +------------+     +---------+
```

- **mssql-load**: Creates the `demo` database and `dbo.events` table, then inserts one row per second to drive the custom `mssql_demo_events_rows` metric.
- **SQL Server**: Runs the `mcr.microsoft.com/mssql/server` image on port 1433 with the `sa` login. The compose file sets `platform: linux/amd64` because the image is amd64-only.
- **Alloy**: Reads `mssql-queries.yaml`, connects to SQL Server through `prometheus.exporter.mssql`, scrapes exporter metrics, and remote-writes them to Prometheus.
- **Prometheus**: Stores metrics received through its remote write API.
- **Grafana**: Queries Prometheus in **Explore**. Anonymous admin access is enabled.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.
   - Navigate to this scenario: `cd alloy-scenarios/mssql-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Prometheus, and Alloy.
   - Deploy the scenario: `./run-example.sh mssql-monitoring`

3. Check that the stack is ready: `cd alloy-scenarios/mssql-monitoring && docker compose ps`
   SQL Server can take up to about a minute to pass its health check on first boot.
   The `mssql-load` and `alloy` services won't start until SQL Server is healthy.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Metrics storage and the query UI.
- **SQL Server** at localhost:1433: Database endpoint with user `sa` and password `Alloy-Demo-Pass123!`.

## Understand the configuration

The metrics pipeline in the Alloy configuration file, `config.alloy`, has four components plus live debugging.

1. **`local.file.queries`**: Reads `/etc/alloy/mssql-queries.yaml` from the mounted volume. The exporter's `query_config` argument takes the file contents as a string.
2. **`prometheus.exporter.mssql.default`**: Connects to SQL Server with `connection_string = sys.env("MSSQL_CONNECTION_STRING")`. The compose file sets that variable to `sqlserver://sa:Alloy-Demo-Pass123!@mssql:1433?encrypt=true&trustservercertificate=true`. Alloy treats the value as a one-way secret, so the credential doesn't appear in the configuration file and the Alloy UI redacts it. The `query_config` value comes from `local.file.queries.content`.
3. **`prometheus.scrape.mssql`**: Scrapes `prometheus.exporter.mssql.default.targets` every 15 seconds and forwards samples to `prometheus.remote_write.default`.
4. **`prometheus.remote_write.default`**: Sends metrics to `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

The `query_config` argument replaces the exporter's built-in collector entirely.
To keep the standard DMV metrics and add custom ones, `mssql-queries.yaml` copies the upstream default collector and appends two metrics at the end of the `metrics:` list:

- `mssql_database_filesize`: Per-file size in bytes from `sys.master_files`.
- `mssql_demo_events_rows`: Row count of `demo.dbo.events`, with a guard query so collection succeeds before the load generator creates the table.

In production, source the connection string from a secret store instead of the compose file.
Refer to the [vault-secrets](../vault-secrets/) scenario for fetching credentials at runtime with `remote.vault`.
Use a least-privilege monitoring login rather than `sa`.
That login needs `VIEW SERVER STATE` for the default collector's DMV queries.

## Try it out

1. Open Grafana at http://localhost:3000 and navigate to **Explore**.

2. Select the **Prometheus** data source and run these queries:
   - Database file sizes for the demo database: `mssql_database_filesize{db="demo"}`
   - Demo table row count, increases about once per second: `mssql_demo_events_rows`
   - Batch request throughput: `rate(mssql_batch_requests_total[1m])`
   - Open connections per database: `mssql_connections`
   - IO stall time by database: `rate(mssql_io_stall_seconds_total[5m])`

   `mssql_demo_events_rows` climbing one row per second, driven by the `mssql-load` container, is the scenario's success signal, together with `mssql_database_filesize` reporting every database file.

3. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `prometheus.exporter.mssql.default`, `prometheus.scrape.mssql`, or `prometheus.remote_write.default` from the component graph to use live debug.

## Customize the scenario

- **Add custom metrics**: Edit `mssql-queries.yaml` in the [sql_exporter](https://github.com/burningalchemist/sql_exporter) collector format. Add entries under `metrics:` with a `metric_name`, `type`, `help`, optional `key_labels`, the `values` column or columns, and the T-SQL `query`. Restart Alloy or wait for `local.file.queries` to re-read the file.
- **Change scrape frequency**: Update `scrape_interval` in `prometheus.scrape.mssql` in the Alloy configuration file, `config.alloy`.
- **Use a monitoring login instead of `sa`**: Create a SQL Server login with `VIEW SERVER STATE`, update `MSSQL_CONNECTION_STRING` in `docker-compose.yml`, and restart the `alloy` container.
- **Point Alloy at an external SQL Server**: Remove the `mssql` and `mssql-load` services from `docker-compose.yml`, set `MSSQL_CONNECTION_STRING` to your instance, and keep `mssql-queries.yaml` on the volume mount.

## Troubleshoot common problems

Diagnose SQL Server startup failures on Apple Silicon, dependency errors, slow first boot, missing metrics, and port conflicts.

### Apple Silicon hosts need Rosetta emulation

SQL Server is an amd64-only binary.
The `platform: linux/amd64` line in the compose file only tells Docker which image to pull.
It doesn't choose how that image is emulated.
Docker Desktop's default emulator, QEMU, crashes SQL Server on startup.
The `mssql` container exits with code `139` and the logs show:

```text
qemu: uncaught target signal 11 (Segmentation fault) - core dumped
```

Because `mssql-load` and `alloy` use `depends_on: condition: service_healthy`, they then report `dependency mssql failed to start`.
That message is the gate working correctly, not a bug in the scenario.
The real failure is the SQL Server crash above.

Switch Docker Desktop to Apple's Rosetta emulation as a one-time setting:

1. Open **Docker Desktop → Settings → General**.
2. Enable **Use Virtualization framework**.
3. Enable **Use Rosetta for x86_64/amd64 emulation**.
4. Select **Apply & restart** Docker Desktop, then run `docker compose up -d` again.

Rosetta runs the amd64 SQL Server binary reliably.
QEMU doesn't.
Intel Macs, Linux, and Windows on x86_64 run the image natively and don't need any of this.

### `dependency mssql failed to start`

Run `docker compose logs mssql` to read the SQL Server startup error.
On Apple Silicon without Rosetta, the logs show a QEMU segmentation fault.
On other hosts, check that about 2 GB of memory is available and that `MSSQL_SA_PASSWORD` meets SQL Server complexity requirements.

### No metrics appear in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that `prometheus.exporter.mssql.default`, `prometheus.scrape.mssql`, and `prometheus.remote_write.default` show a healthy status.
Run `docker compose ps` and check that the `mssql` container is healthy before `alloy` starts.
Query `mssql_demo_events_rows` in Prometheus at http://localhost:9090 to check that the exporter returns data.

### Port conflicts with other services

Ports 1433 for SQL Server, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `mssql-monitoring` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `prometheus.exporter.mssql` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.mssql/
- [mysql-monitoring](../mysql-monitoring/): MySQL metrics with the same remote-write pattern
- [vault-secrets](../vault-secrets/): Load credentials from HashiCorp Vault at runtime
- More examples: https://github.com/grafana/alloy-scenarios
