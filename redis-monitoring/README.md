# Redis metrics

This scenario collects Redis metrics with the `prometheus.exporter.redis` component in Grafana Alloy.
Alloy connects to Redis, scrapes exporter metrics, and remote-writes them to Prometheus.
Grafana queries Prometheus through a provisioned data source.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 6379 for Redis, 3000 for Grafana, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------+       +-------+       +-------------+       +---------+
| redis |       | Alloy |       | Prometheus  |       | Grafana |
|       |<----->|       |------>|             |------>|         |
+-------+       +-------+       +-------------+       +---------+
```

- **redis**: Redis 8 on port 6379.
- **Alloy**: Runs `config.alloy`. `prometheus.exporter.redis` connects to `redis:6379`, `prometheus.scrape` collects metrics, and `prometheus.remote_write` sends them to Prometheus. The configuration enables the Alloy UI debug view.
- **Prometheus**: Stores metrics through its remote write receiver at `http://prometheus:9090/api/v1/write`.
- **Grafana**: Queries Prometheus through a provisioned data source.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/redis-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh redis-monitoring`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `redis-monitoring` directory, check that all containers are up: `docker compose ps`

   Expect `redis`, `alloy`, `prometheus`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Prometheus data source. You do not need to log in.
- **Alloy UI** at http://localhost:12345: Component graph for `prometheus.exporter.redis`, `prometheus.scrape`, and `prometheus.remote_write`. `config.alloy` enables the Alloy UI debug view.
- **Prometheus** at http://localhost:9090: Redis metrics from remote write.
- **Redis** at localhost:6379: Database instance Alloy monitors.

## Understand the Alloy pipeline

`config.alloy` defines the pipeline:

1. **`prometheus.exporter.redis`**: Connects to `redis:6379` and exposes Redis metrics.
2. **`prometheus.scrape`**: Scrapes the exporter targets.
3. **`prometheus.remote_write`**: Sends metrics to `http://prometheus:9090/api/v1/write`.

The `livedebugging` block enables the Alloy UI debug view.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Prometheus** data source and run these PromQL queries:

   - `redis_up`: Whether Redis is reachable
   - `redis_connected_clients`: Number of connected clients
   - `redis_used_memory_bytes`: Memory usage
   - `redis_commands_total`: Total commands processed
   - `redis_keyspace_hits_total`: Cache hits
   - `redis_keyspace_misses_total`: Cache misses

2. Open the Alloy UI at http://localhost:12345.

   Navigate to the component graph to verify `prometheus.exporter.redis` → `prometheus.scrape` → `prometheus.remote_write`.
   Use the debug view to inspect metrics flowing through each component.

## Customize the scenario

- **Change the Redis address**: Edit `redis_addr` under `prometheus.exporter.redis` in `config.alloy`.
- **Point at another Prometheus**: Update the remote write URL in `prometheus.remote_write` in `config.alloy`.

## Troubleshoot common problems

This section covers startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `redis`, `alloy`, or `prometheus`.

### No Redis metrics in Prometheus

In Grafana, select the **Prometheus** data source in **Explore** and run `redis_up`.
Open the Alloy UI at http://localhost:12345 and check that `prometheus.exporter.redis` targets are up.

### Port conflicts with other services

Ports 6379, 3000, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `redis-monitoring` directory.

## Next steps

- Alloy `prometheus.exporter.redis` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.redis/
- More examples: https://github.com/grafana/alloy-scenarios
