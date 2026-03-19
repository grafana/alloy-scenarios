# Kafka-Buffered Trace Pipeline

Demonstrates using Apache Kafka as a durable buffer in an OpenTelemetry trace pipeline. Alloy runs both the agent tier (OTLP receiver to Kafka) and the gateway tier (Kafka to Tempo) in a single collector instance, showcasing the two-tier architecture pattern.

## What This Demonstrates

- **Kafka as a durable buffer**: Traces are written to Kafka before being exported to Tempo, providing resilience against backend outages
- **Two-tier collector architecture**: The agent tier ingests OTLP and writes to Kafka; the gateway tier reads from Kafka and exports to Tempo
- **Single-collector demo**: Both tiers run in one Alloy instance for simplicity, but in production these would be separate deployments
- **KRaft mode Kafka**: Uses Bitnami Kafka with KRaft (no ZooKeeper required)
- **Auto topic creation**: The `otlp-traces` topic is created automatically on first write

## Architecture

```
App --OTLP--> Alloy (agent tier) --Kafka--> Alloy (gateway tier) --OTLP--> Tempo
```

In this demo, both tiers are the same Alloy instance with two separate pipelines:

1. **`traces/ingest`**: `otlp` receiver -> `kafka` exporter
2. **`traces/export`**: `kafka` receiver -> `batch` processor -> `otlp/tempo` exporter

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

Wait about 30 seconds for Kafka to initialize before traces start flowing.

## Explore

Open Grafana at [http://localhost:3000](http://localhost:3000) and go to **Explore > Tempo**.

Search for traces from `kafka-buffer-demo`. You should see traces for HTTP endpoints (`/api/items`, `/api/checkout`, `/api/health`) with database query child spans.

### Demonstrate Resilience

The key benefit of the Kafka buffer is resilience. Try this experiment:

1. Let the demo run for a minute to generate some traces
2. Stop Tempo: `docker compose stop tempo`
3. Wait 30 seconds (traces are buffering in Kafka)
4. Restart Tempo: `docker compose start tempo`
5. Check Grafana -- the buffered traces should appear in Tempo

This works because Kafka retains messages until the consumer (gateway tier) successfully reads them.

## Key Configuration

The `config-otel.yaml` defines:

1. **`kafka` exporter**: Writes OTLP-encoded trace data to the `otlp-traces` Kafka topic
2. **`kafka` receiver**: Reads from the same topic and deserializes traces
3. **Two pipelines**: `traces/ingest` (app -> Kafka) and `traces/export` (Kafka -> Tempo)

The Kafka exporter uses `otlp_proto` encoding, which preserves full trace fidelity through the buffer.

## Stop

```bash
docker compose down
```
