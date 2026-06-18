# PostgreSQL monitoring

This scenario shows how to collect PostgreSQL server metrics with the `prometheus.exporter.postgres` component in Grafana Alloy.
Alloy connects to PostgreSQL, scrapes exporter metrics every 15 seconds, and remote-writes them to Prometheus.
Grafana queries Prometheus through a provisioned data source.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 5432 for PostgreSQL, 3000 for Grafana, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+       +-------+       +-------------+       +---------+
| postgres |  DSN  | Alloy |       | Prometheus  |       | Grafana |
|          |<----->|       |------>|             |------>|         |
+----------+       +-------+       +-------------+       +---------+
```

- **postgres**: PostgreSQL 18 on port 5432 with user `alloy`, password `alloy`, and database `alloy`.
- **Alloy**: Runs `config.alloy`. `prometheus.exporter.postgres` connects to PostgreSQL, `prometheus.scrape` collects metrics every 15 seconds, and `prometheus.remote_write` sends them to Prometheus. Live debugging is enabled.
- **Prometheus**: Stores metrics through its remote write receiver at `http://prometheus:9090/api/v1/write`.
- **Grafana**: Queries Prometheus through a provisioned data source.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/postgres-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh postgres-monitoring`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `postgres-monitoring` directory, check that all containers are up: `docker compose ps`

   Expect `postgres`, `alloy`, `prometheus`, and `grafana`.
   Alloy waits for PostgreSQL to pass its health check before starting.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Prometheus data source, with no login required.
- **Alloy UI** at http://localhost:12345: Component graph for `prometheus.exporter.postgres`, `prometheus.scrape`, and `prometheus.remote_write`. Live debugging is enabled in `config.alloy`.
- **Prometheus** at http://localhost:9090: PostgreSQL metrics from remote write.
- **PostgreSQL** at localhost:5432: Database instance Alloy monitors.

## Understand the Alloy pipeline

`config.alloy` defines the pipeline:

1. **`prometheus.exporter.postgres`**: Connects to `postgresql://alloy:alloy@postgres:5432/alloy?sslmode=disable` and exposes PostgreSQL metrics.
2. **`prometheus.scrape`**: Scrapes the exporter every 15 seconds.
3. **`prometheus.remote_write`**: Sends metrics to `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect data flow in the Alloy UI.

### Metrics collected

- **pg_up**: Whether the PostgreSQL instance is reachable
- **pg_stat_database_***: Database-level statistics such as transactions committed, rolled back, rows fetched, inserted, updated, deleted, deadlocks, and temp files
- **pg_stat_bgwriter_***: Background writer statistics such as buffers written and checkpoints
- **pg_settings_***: PostgreSQL server configuration settings exposed as metrics
- **pg_stat_activity_***: Connection and session activity
- **pg_locks_***: Lock statistics by mode

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Prometheus** data source and run these PromQL queries:

   - `pg_up`: PostgreSQL reachability
   - `{__name__=~"pg_stat_database_.*"}`: Database-level statistics
   - `{__name__=~"pg_"}`: All PostgreSQL exporter metrics

2. Open the Alloy UI at http://localhost:12345.

   Navigate to the component graph to verify `prometheus.exporter.postgres` → `prometheus.scrape` → `prometheus.remote_write`.
   Use live debugging to inspect metrics flowing through each component.

## Customize the scenario

- **Change the database connection**: Edit `data_source_names` under `prometheus.exporter.postgres` in `config.alloy`.
- **Change scrape interval**: Edit `scrape_interval` under `prometheus.scrape` in `config.alloy`.
- **Point at another Prometheus**: Update the remote write URL in `prometheus.remote_write` in `config.alloy`.

## Troubleshoot common problems

Covers startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `postgres`, `alloy`, or `prometheus`.
Alloy depends on PostgreSQL passing its health check. Check `docker compose logs postgres` if Alloy never starts.

### No PostgreSQL metrics in Prometheus

Wait for Alloy to start after PostgreSQL becomes healthy.
In Grafana, select the **Prometheus** data source in **Explore** and run `pg_up`.
Open the Alloy UI at http://localhost:12345 and check that `prometheus.exporter.postgres` targets are up.

### Port conflicts with other services

Ports 5432, 3000, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `postgres-monitoring` directory.

## Next steps

- Alloy `prometheus.exporter.postgres` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.postgres/
- More examples: https://github.com/grafana/alloy-scenarios
