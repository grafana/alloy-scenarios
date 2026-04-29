# RabbitMQ Monitoring with Grafana Alloy

This scenario demonstrates RabbitMQ observability with a single Alloy pipeline:

- **Metrics** - `prometheus.scrape` collects RabbitMQ's built-in `/metrics` endpoint from the `rabbitmq_prometheus` plugin and remote-writes the samples to Prometheus.
- **Logs** - `loki.source.docker` tails the RabbitMQ container logs from the Docker socket and sends them to Loki.

## Architecture

- **RabbitMQ** - the monitored broker, running the management and Prometheus plugins
- **loadgen** - a small RabbitMQ PerfTest publisher that creates the durable `alloy-sample` queue and publishes one persistent message per second
- **Grafana Alloy** - scrapes broker metrics, collects broker container logs, and forwards both signals
- **Loki / Prometheus / Grafana** - local backends and visualization, with datasources auto-provisioned

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root using centralized image versions
./run-example.sh rabbitmq-monitoring
```

## Accessing

- **Grafana**: http://localhost:3000 (no login required)
- **Alloy UI**: http://localhost:12345
- **Prometheus**: http://localhost:9090
- **Loki**: http://localhost:3100
- **RabbitMQ Management UI**: http://localhost:15672 (`guest` / `guest`)
- **RabbitMQ Prometheus endpoint**: http://localhost:15692/metrics

## Trying It Out

Within about 30 seconds, open Grafana Explore and run these queries.

### Metrics

```promql
rabbitmq_up
```

```promql
rabbitmq_queue_messages{queue="alloy-sample"}
```

```promql
rabbitmq_channels
```

The scenario sets `prometheus.return_per_object_metrics = true` so queue-level labels are visible on `/metrics`.

### Logs

```logql
{job="rabbitmq"}
```

```logql
{job="rabbitmq"} |~ "accepting AMQP connection|authenticated and granted access"
```

RabbitMQ logs connection lifecycle events by default. Channel counts are best checked with metrics:

```promql
rabbitmq_channels
```

## Key Configuration

- `enabled_plugins` enables `rabbitmq_management` and `rabbitmq_prometheus`.
- `rabbitmq.conf` sends debug-level console logs to Docker and returns per-object queue metrics from `/metrics`.
- `config.alloy` keeps the metrics and logs pipelines separate and labels RabbitMQ logs as `job="rabbitmq"`.

## Stopping

```bash
docker compose down -v
```
