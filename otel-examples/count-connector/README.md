# Count Connector (Derive Metrics from Signals)

Use the OTel count connector to automatically derive count metrics from traces and logs -- the "metrics from signals" pattern -- without additional instrumentation.

## What This Demonstrates

- **Count connector** deriving metrics from trace spans and log records
- Generating error rate metrics (`span.error.count`, `log.error.count`) from signal status codes
- Generating volume metrics (`span.count`, `log.count`) for throughput monitoring
- Routing derived metrics to Prometheus while original signals go to Tempo and Loki

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

## Explore

Open Grafana at [http://localhost:3000](http://localhost:3000).

### View derived metrics in Prometheus

Go to Explore > Prometheus and query the following metrics:

```promql
# Total span count (rate per second)
rate(span_count_total[5m])

# Error span count (rate per second)
rate(span_error_count_total[5m])

# Error rate as a percentage
rate(span_error_count_total[5m]) / rate(span_count_total[5m]) * 100

# Total log record count
rate(log_count_total[5m])

# Error log count
rate(log_error_count_total[5m])
```

### View original traces in Tempo

Go to Explore > Tempo and search for `count-connector-demo` traces. You will see both successful (OK) and error traces.

### View original logs in Loki

Go to Explore > Loki and query:

```logql
{service_name="count-connector-demo"} | json
```

### Check the Alloy OTel pipeline

Visit the Alloy OTel HTTP server at [http://localhost:8888](http://localhost:8888).

## Key Configuration

The `config-otel.yaml` pipeline uses the **count connector** to bridge signals:

1. **`connectors/count`** -- Defines four derived metrics:
   - `span.count` -- Total number of spans received
   - `span.error.count` -- Spans where `status.code == 2` (ERROR)
   - `log.count` -- Total number of log records received
   - `log.error.count` -- Logs where `severity_number >= 17` (ERROR and above)

2. **Pipeline wiring:**
   - `traces` pipeline: receives OTLP, exports to both `count` connector and `otlp/tempo`
   - `logs` pipeline: receives OTLP, exports to both `count` connector and `otlphttp/loki`
   - `metrics` pipeline: receives from `count` connector, exports to `otlphttp/prometheus`

The count connector acts as both an exporter (in the traces/logs pipelines) and a receiver (in the metrics pipeline), bridging signals without any application changes.

## Stop

```bash
docker compose down
```
