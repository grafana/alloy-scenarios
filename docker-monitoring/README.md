# Docker monitoring

This scenario shows how Grafana Alloy monitors Docker container metrics and logs.
Alloy uses `prometheus.exporter.cadvisor` for container metrics and `loki.source.docker` to tail container logs through the Docker socket.
Metrics remote-write to Prometheus and logs push to Loki.
The `config.alloy` file defines the pipeline.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, 3100 for Loki, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Alloy reads from the Docker socket on the host and forwards container metrics and logs to Prometheus and Loki.

```text
+-------------+     +-------+     +-------------+     +---------+
| Docker host |     |       |---->| Prometheus  |---->|         |
| containers  |---->| Alloy |     +-------------+     | Grafana |
|             |     |       |---->|    Loki     |---->|         |
+-------------+     +-------+     +-------------+     +---------+
```

- **Docker host**: Running containers on the machine where you start the stack.
  Alloy mounts the Docker socket and host paths needed by cAdvisor.
- **Alloy**: Collects container metrics with cAdvisor and tails container logs, then forwards both signals to their backends.
- **Prometheus**: Stores container metrics from remote write.
- **Loki**: Stores container log lines.
- **Grafana**: Queries metrics and logs through provisioned Prometheus and Loki data sources.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/docker-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh docker-monitoring`

3. Check that all containers are up: `cd alloy-scenarios/docker-monitoring && docker compose ps`

   Expect `alloy`, `prometheus`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph and component health.
- **Prometheus** at http://localhost:9090: Query container metrics directly.
- **Loki** at http://localhost:3100: Log storage backend.

## Understand the configuration

The `config.alloy` pipeline runs two parallel paths for metrics and logs.

Metrics path:

1. **`prometheus.exporter.cadvisor "example"`**: Exposes container metrics from the Docker socket with `docker_only = true`.
2. **`discovery.relabel "example"`**: Sets `job` to `integrations/docker` and `instance` to the Alloy hostname.
3. **`prometheus.scrape "scraper"`**: Scrapes cAdvisor metrics every 10 seconds and forwards samples to `prometheus.remote_write.demo`.
4. **`prometheus.remote_write "demo"`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

Logs path:

1. **`discovery.docker "linux"`**: Discovers containers through the Docker socket.
2. **`discovery.relabel "logs_integrations_docker"`**: Sets `container_name` from the container name and `instance` to the Alloy hostname.
3. **`loki.source.docker "default"`**: Tails logs from discovered containers and forwards them to `loki.process.docker_logs`.
4. **`loki.process "docker_logs"`**: Drops logs from infrastructure containers matching `alloy`, `grafana`, and `loki`, then forwards the rest to `loki.write.local`.
5. **`loki.write "local"`**: Pushes log lines to Loki at `http://loki:3100/loki/api/v1/push`.

## Try it out

1. Open Grafana **Explore**, select the **Prometheus** data source, and run:

   ```promql
   container_cpu_usage_seconds_total{job="integrations/docker"}
   ```

2. Switch to the **Loki** data source and try:

   ```logql
   {container_name=~".+"}
   ```

   Logs from `alloy`, `grafana`, and `loki` are dropped by `loki.process.docker_logs`.

3. Open the Alloy UI at http://localhost:12345 and check that the cAdvisor and Docker log components are healthy.

## Customize the scenario

Edit the `stage.drop` expression in `loki.process "docker_logs"` to change which container names are excluded, or change `scrape_interval` on `prometheus.scrape "scraper"`.

## Troubleshoot common problems

Use these steps when Alloy cannot reach Docker or ports conflict.

### Alloy cannot connect to the Docker socket on macOS

On some Docker Desktop versions, change the socket mount in `docker-compose.yml` from `/var/run/docker.sock` to `/var/run/docker.sock.raw`.

### Port conflicts with other services

Ports 3000, 9090, 3100, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `prometheus.exporter.cadvisor` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.cadvisor/
- `loki.source.docker` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
- Linux host monitoring scenario: [../linux/](../linux/)
