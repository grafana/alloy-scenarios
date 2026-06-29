# Kafka buffer

This scenario shows how to use Apache Kafka as a durable buffer in a two-tier OpenTelemetry trace pipeline.
The demo app sends traces to the agent tier over OTLP.
The agent tier writes them to the `otlp-traces` Kafka topic.
The gateway tier reads from Kafka and exports to Tempo.
Both tiers run in one Alloy process for simplicity, but in production they are separate deployments.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9092 for Kafka, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+       +-------------+       +-------+       +-------------+       +-------+       +---------+
| demo-app | OTLP  | Alloy OTel  |       | Kafka |       | Alloy OTel  |       | Tempo |       | Grafana |
|          |------>| agent tier  |------>|       |------>| gateway tier|------>|       |------>|         |
+----------+       +-------------+       +-------+       +-------------+       +-------+       +---------+
```

- **demo-app**: Flask app on port 8080 that sends HTTP traces with database child spans to the agent tier over OTLP.
- **Alloy agent tier**: `traces/ingest` pipeline in `config-otel.yaml`. Accepts OTLP and writes traces to Kafka with `otlp_proto` encoding.
- **Kafka**: Apache Kafka in KRaft mode on port 9092. Stores traces in the `otlp-traces` topic until the gateway tier reads them.
- **Alloy gateway tier**: `traces/export` pipeline in `config-otel.yaml`. Reads from Kafka, batches spans, and exports to Tempo.
- **Tempo**: Stores traces at `http://tempo:4317`.
- **Grafana**: Queries Tempo through a provisioned data source.

Both tiers run in the same Alloy container in this demo. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/kafka-buffer`
   - Deploy the scenario: `docker compose up -d --build`

   Wait about 30 seconds for Kafka to initialize before traces start flowing.

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/kafka-buffer && docker compose --env-file ../../image-versions.env up -d --build`

   Wait about 30 seconds for Kafka to initialize before traces start flowing.

3. From the `kafka-buffer` directory, check that all containers are up: `docker compose ps`

   Expect `demo-app`, `alloy`, `kafka`, `tempo`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: `/api/items`, `/api/items/<id>`, `/api/checkout`, and `/api/health`.
- **Grafana** at http://localhost:3000: **Explore** with the Tempo data source, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Tempo** at http://localhost:3200: Trace storage backend.
- **Kafka** at localhost:9092: Trace buffer between ingest and export.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### Kafka receiver and exporter

Both use broker `kafka:9092` with protocol version `3.0.0` and topic `otlp-traces`.

- **`kafka` exporter**: Writes OTLP-encoded traces with `otlp_proto` encoding.
- **`kafka` receiver**: Reads traces from the same topic.

### Pipeline wiring

1. **Agent tier — `traces/ingest`**: `otlp` → `kafka`
2. **Gateway tier — `traces/export`**: `kafka` → `batch` → `otlp/tempo`

The agent tier buffers traces to Kafka. The gateway tier drains Kafka and exports to backends. In production, run each tier in a separate Alloy deployment.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The background load generator calls `/api/items`, `/api/checkout`, and `/api/health` every 0.5 to 2 seconds.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Tempo** data source and run `{resource.service.name="kafka-buffer-demo"}` in **Search**.
   Expect traces for `/api/items`, `/api/checkout`, and `/api/health` with database query child spans.

2. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

### Demonstrate resilience

Kafka buffers traces when Tempo is unavailable:

1. Let the demo run for a minute to generate traces.
2. Stop Tempo: `docker compose stop tempo`
3. Wait 30 seconds while traces buffer in Kafka.
4. Restart Tempo: `docker compose start tempo`
5. In Grafana, search Tempo for `{resource.service.name="kafka-buffer-demo"}` again.

   Buffered traces appear after Tempo restarts because Kafka retains messages until the export pipeline reads them successfully.

## Customize the scenario

- **Change the Kafka topic**: Update `topic` in the `kafka` receiver and exporter in `config-otel.yaml`.
- **Split tiers**: Move `traces/ingest` and `traces/export` into separate Alloy deployments in production.
- **Adjust load**: Edit the `generate_load` function in `app/app.py`.

## Troubleshoot common problems

Covers startup failures, missing traces, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `kafka`, `alloy`, or `tempo`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No traces in Tempo

Wait about 30 seconds for Kafka to finish starting, then wait for the demo app load generator to begin. It sleeps five seconds after startup.
In Grafana, select the **Tempo** data source in **Explore** and run `{resource.service.name="kafka-buffer-demo"}`.
Check Kafka with `docker compose logs kafka` and Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 8080, 3000, 3200, 9092, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/kafka-buffer` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry Kafka receiver: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/kafkareceiver
- OpenTelemetry Kafka exporter: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/kafkaexporter
- More examples: https://github.com/grafana/alloy-scenarios
