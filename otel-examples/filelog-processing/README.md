# Filelog Processing

Demonstrates the OTel Collector **filelog receiver** with operator chains to parse mixed-format log files. A log generator writes both JSON and plaintext log lines to a shared volume, and Alloy (running the OTel engine) reads, parses, and ships them to Loki.

## What This Demonstrates

- **Filelog receiver** reading log files from disk using glob patterns
- **Conditional operator chains** that detect log format and apply the correct parser (JSON vs regex)
- **Severity parsing** to map log levels to OTel severity
- **Resource attribute injection** to tag all logs with a service name
- Exporting parsed logs to **Loki via OTLP/HTTP**

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

## Explore

1. Open Grafana at [http://localhost:3000](http://localhost:3000) (no login required).
2. Go to **Explore** and select the **Loki** datasource.
3. Try these LogQL queries:

```logql
{service_name="log-demo"}
```

```logql
{service_name="log-demo"} | json
```

```logql
{service_name="log-demo"} |= "ERROR"
```

4. Observe that both JSON and plaintext lines are ingested, with severity levels and timestamps correctly parsed.

## Key Configuration

The `config-otel.yaml` defines a filelog receiver with chained operators:

- **`json_parser`** (conditional) -- fires when the log line starts with `{`, extracting structured fields and timestamps.
- **`regex_parser`** (conditional) -- fires when the log line starts with a date pattern, capturing timestamp, level, and message.
- **`severity_parser`** -- maps the parsed `level` attribute to OTel severity.
- **`add` operator** -- injects `service.name` as a resource attribute.

Logs are batched and exported to Loki's OTLP endpoint at `http://loki:3100/otlp`.

## Stop

```bash
docker compose down
```
