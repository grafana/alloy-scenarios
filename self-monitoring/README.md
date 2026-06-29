# Alloy metrics and logs

This scenario collects Alloy internal metrics and Docker container logs from the same host.
Alloy scrapes its own metrics with `prometheus.exporter.self`, discovers containers through the Docker socket, and sends metrics to Prometheus and logs to Loki.
This stack doesn't include Grafana.
You query metrics in the Prometheus UI and inspect pipelines in the Alloy UI.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 9090 for Prometheus, 3100 for Loki, and 12345 for the Alloy UI free on the host.
- Access to `/var/run/docker.sock` on the host.
  Alloy mounts the socket to discover containers and tail their logs.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------------+     +-------+     +-------------+
| Docker      |     |       |---->| Prometheus  |
| containers  |---->| Alloy |     +-------------+
| docker.sock |     |       |---->|    Loki     |
+-------------+     +-------+     +-------------+
```

- **Alloy**: Runs `config.alloy`.
  Scrapes self metrics with `prometheus.exporter.self`, tails Docker container logs through the socket, and remote-writes metrics to Prometheus and logs to Loki.
- **Prometheus**: Stores metrics through its remote write receiver at `http://prometheus:9090/api/v1/write`.
- **Loki**: Stores logs at `http://loki:3100/loki/api/v1/push`.

Self metrics come from inside the Alloy process.
Log collection reads container stdout through `unix:///var/run/docker.sock` and includes the `alloy`, `prometheus`, and `loki` containers in this stack.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yaml`.

   - Go to the scenario: `cd alloy-scenarios/self-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh self-monitoring`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `self-monitoring` directory, check that all containers are up: `docker compose ps`

   Expect `alloy`, `prometheus`, and `loki`.

## Explore the services

- **Alloy UI** at http://localhost:12345: Component graph for the self-metrics and Docker log pipelines.
- **Prometheus** at http://localhost:9090: Alloy self metrics from remote write.
- **Loki** at http://localhost:3100: Container logs from `loki.source.docker`.

## Understand the Alloy pipeline

`config.alloy` defines two pipelines.

### Self metrics

1. **`prometheus.exporter.self`**: Exposes Alloy internal metrics.
2. **`discovery.relabel`**: Adds `instance` and `container=alloy` labels.
3. **`prometheus.scrape`**: Scrapes the exporter with job name `integrations/alloy`.
4. **`prometheus.relabel`**: Passes metrics through to remote write.
5. **`prometheus.remote_write`**: Sends metrics to `http://prometheus:9090/api/v1/write`.

`prometheus.exporter.self` exposes metrics for memory usage, CPU utilization, component health, and scrape statistics.

### Docker logs

1. **`discovery.docker`**: Discovers containers on `unix:///var/run/docker.sock`.
2. **`discovery.relabel`**: Extracts a short `container` label from Docker container names and sets `instance` from the host name.
3. **`loki.source.docker`**: Tails logs from discovered containers.
4. **`loki.write`**: Sends logs to `http://loki:3100/loki/api/v1/push`.

Log collection includes Alloy, Prometheus, Loki, and any other containers running on the same Docker host.

## Try it out

1. Open the Alloy UI at http://localhost:12345.

   Navigate to the component graph to verify the self-metrics path `prometheus.exporter.self` → `prometheus.scrape` → `prometheus.remote_write` and the log path `loki.source.docker` → `loki.write`.

2. Open Prometheus at http://localhost:9090 and go to **Graph**.

   Run these PromQL queries:

   - `{job="integrations/alloy"}`: All Alloy self metrics
   - `go_goroutines{job="integrations/alloy"}`: Go runtime goroutines
   - `process_resident_memory_bytes{job="integrations/alloy"}`: Resident memory usage

3. Query Loki for container logs.

   This stack has no Grafana UI.
   Use [logcli](https://grafana.com/docs/loki/latest/query/logcli/) or another Loki client with these LogQL queries:

   - `{container="alloy"}`: Alloy container logs
   - `{container="prometheus"}`: Prometheus container logs
   - `{container="loki"}`: Loki container logs

## Customize the scenario

- **Change metric labels**: Edit rules under `discovery.relabel.integrations_alloy_health` in `config.alloy`.
- **Change log labels**: Edit rules under `discovery.relabel.logs_integrations_docker` in `config.alloy`.
- **Point at other backends**: Update the remote write URL in `prometheus.remote_write` or the push URL in `loki.write` in `config.alloy`.

## Troubleshoot common problems

This section covers startup failures, missing data, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `alloy`, `prometheus`, or `loki`.

### No Alloy metrics in Prometheus

Open the Alloy UI at http://localhost:12345 and check that `prometheus.exporter.self` targets are up.
In the Prometheus UI at http://localhost:9090, run `{job="integrations/alloy"}`.

### No container logs in Loki

Check that Alloy can access the Docker socket.
The compose file mounts `/var/run/docker.sock` into the Alloy container.
Open the Alloy UI at http://localhost:12345 and verify that `loki.source.docker` is receiving log entries.

### Port conflicts with other services

Ports 9090, 3100, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yaml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `self-monitoring` directory.

## Next steps

- Alloy `prometheus.exporter.self` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.self/
- Alloy `loki.source.docker` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
- More examples: https://github.com/grafana/alloy-scenarios
