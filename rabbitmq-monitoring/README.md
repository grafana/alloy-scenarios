# RabbitMQ monitoring

This scenario collects RabbitMQ metrics and container logs with a single Alloy pipeline.
Alloy scrapes the built-in Prometheus endpoint from the `rabbitmq_prometheus` plugin and tails the RabbitMQ container logs from the Docker socket.
A load generator publishes one persistent message per second to the `alloy-sample` queue so queue metrics stay active.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 5672 for AMQP, 15672 for the RabbitMQ management UI, 15692 for RabbitMQ Prometheus metrics, 3000 for Grafana, 3100 for Loki, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+     +-------------+     +-------------+     +---------+
| rabbitmq |     |             |---->| Prometheus  |---->|         |
|          |     | Alloy       |     +-------------+     | Grafana |
|          |---->|             |---->| Loki        |---->|         |
+----------+     +-------------+     +-------------+     +---------+
```

- **rabbitmq**: Broker with the management and Prometheus plugins enabled. Exposes metrics on port 15692 and the management UI on port 15672.
- **loadgen**: RabbitMQ PerfTest publisher that creates the durable `alloy-sample` queue and publishes one persistent message per second.
- **Alloy**: Runs `config.alloy`. Scrapes `rabbitmq:15692` every 15 seconds and collects RabbitMQ container logs through the Docker socket. The configuration enables the Alloy UI debug view.
- **Prometheus**: Stores metrics through its remote write receiver at `http://prometheus:9090/api/v1/write`.
- **Loki**: Stores logs at `http://loki:3100/loki/api/v1/push`.
- **Grafana**: Queries Prometheus and Loki through provisioned data sources.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/rabbitmq-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh rabbitmq-monitoring`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `rabbitmq-monitoring` directory, check that all containers are up: `docker compose ps`

   Expect `rabbitmq`, `loadgen`, `alloy`, `loki`, `prometheus`, and `grafana`.
   Alloy waits for RabbitMQ to pass its health check before startup.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with Prometheus and Loki data sources. You don't need to log in.
- **Alloy UI** at http://localhost:12345: Component graph for the metrics and logs pipelines. `config.alloy` enables the Alloy UI debug view.
- **Prometheus** at http://localhost:9090: RabbitMQ metrics from remote write.
- **Loki** at http://localhost:3100: RabbitMQ container logs.
- **RabbitMQ management UI** at http://localhost:15672: User `guest`, password `guest`.
- **RabbitMQ Prometheus endpoint** at http://localhost:15692/metrics: Built-in metrics from the `rabbitmq_prometheus` plugin.

## Understand the Alloy pipeline

`config.alloy` keeps the metrics and logs pipelines separate.

### Metrics pipeline

1. **`prometheus.scrape`**: Scrapes `rabbitmq:15692` every 15 seconds with `job="rabbitmq"`.
2. **`prometheus.remote_write`**: Sends metrics to `http://prometheus:9090/api/v1/write`.

### Logs pipeline

1. **`discovery.docker`**: Discovers containers from the Docker socket.
2. **`discovery.relabel`**: Keeps the `rabbitmq-monitoring-rabbitmq` container and sets `job="rabbitmq"`.
3. **`loki.source.docker`**: Tails RabbitMQ container logs.
4. **`loki.write`**: Sends logs to `http://loki:3100/loki/api/v1/push`.

### RabbitMQ settings

- **`enabled_plugins`**: Enables `rabbitmq_management` and `rabbitmq_prometheus`.
- **`rabbitmq.conf`**: Sets `prometheus.return_per_object_metrics = true` so queue-level labels appear on `/metrics`. Sends debug-level console logs to Docker.

## Try it out

Wait about 30 seconds after startup, then open Grafana at http://localhost:3000 and go to **Explore**.

1. Select the **Prometheus** data source and run:

   - `rabbitmq_up`: Broker reachability
   - `rabbitmq_queue_messages{queue="alloy-sample"}`: Messages in the demo queue
   - `rabbitmq_channels`: Open channel count

2. Select the **Loki** data source and run:

   - `{job="rabbitmq"}`: All RabbitMQ container logs
   - `{job="rabbitmq"} |~ "accepting AMQP connection|authenticated and granted access"`: Connection lifecycle events

   RabbitMQ logs connection lifecycle events by default. Check channel counts with the `rabbitmq_channels` PromQL query above.

3. Open the Alloy UI at http://localhost:12345 and inspect both pipelines in the debug view.

## Customize the scenario

- **Change load rate**: Edit the `loadgen` service `command` in `docker-compose.yml`.
- **Adjust log level**: Edit `log.console.level` in `rabbitmq.conf`.
- **Scrape a different target**: Edit targets under `prometheus.scrape` in `config.alloy`.

## Troubleshoot common problems

This section covers startup failures, missing telemetry, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `rabbitmq`, `alloy`, or `loki`.
Alloy starts after RabbitMQ passes its health check. Check `docker compose logs rabbitmq` if Alloy never starts.

### No metrics or logs in Grafana

Wait about 30 seconds for RabbitMQ and the load generator to start.
In Grafana, run `rabbitmq_up` in Prometheus and `{job="rabbitmq"}` in Loki.
Check Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 5672, 15672, 15692, 3000, 3100, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down -v` from the `rabbitmq-monitoring` directory.

The `-v` flag removes named volumes so the next run starts clean.

## Next steps

- Alloy `prometheus.scrape` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/
- Alloy `loki.source.docker` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
- RabbitMQ Prometheus plugin: https://www.rabbitmq.com/docs/prometheus
- More examples: https://github.com/grafana/alloy-scenarios
