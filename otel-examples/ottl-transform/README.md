# OTTL transform

This scenario is a cookbook of useful OpenTelemetry Transformation Language patterns in the Alloy OTel Engine.
The demo app sends JSON string log bodies and traces with varied attributes over OTLP.
`config-otel.yaml` applies three transform processors to parse logs, enrich traces, and add resource attributes before export to Loki and Tempo.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 3200 for Tempo, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+     +-------------+     +------+     +---------+
| demo-app |     |             |---->| Loki |---->|         |
|          | OTLP| Alloy OTel  |     +------+     | Grafana |
|          |---->| Engine      |---->| Tempo|---->|         |
+----------+     +-------------+     +------+     +---------+
```

- **demo-app**: Python app that sends JSON log records and traces with `http.target`, `db.system`, and long attribute values every three seconds.
- **Alloy**: Runs the OTel Engine from `config-otel.yaml`. Log and trace pipelines use separate OTTL transform processors. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.
- **Loki**: Stores transformed logs through its OTLP HTTP endpoint at `http://loki:3100/otlp`.
- **Tempo**: Stores transformed traces at `http://tempo:4317`.
- **Grafana**: Queries Loki and Tempo through provisioned data sources.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/ottl-transform`
   - Deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/ottl-transform && docker compose --env-file ../../image-versions.env up -d --build`

3. From the `ottl-transform` directory, check that all containers are up: `docker compose ps`

   Expect `demo-app`, `alloy`, `loki`, `tempo`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with Loki and Tempo data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Loki** at http://localhost:3100: Log backend API.
- **Tempo** at http://localhost:3200: Trace storage backend.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### transform/parse-logs

Processes log records before export to Loki:

- Parses JSON string bodies with `ParseJSON(body)` when the body starts with `{`
- Maps `level` strings to OTel severity numbers: INFO=9, WARN=13, ERROR=17
- Deletes promoted `level` and `timestamp` attributes after extraction

### transform/traces

Processes spans before resource enrichment:

- Sets `app.tier=frontend` when `http.target` is present
- Sets `app.tier=backend` when `db.system` is present
- Truncates all span attributes to 256 characters with `truncate_all`
- Demonstrates `replace_pattern` on `http.method`

### transform/resources

Adds `deployment.environment=demo` to trace resources.

### Pipeline wiring

1. **Traces**: `otlp` → `transform/traces` → `transform/resources` → `batch` → `otlp/tempo`
2. **Logs**: `otlp` → `transform/parse-logs` → `batch` → `otlphttp/loki` and `debug`

The `debug` exporter prints detailed log output to the Alloy container logs.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The demo app sends telemetry every three seconds.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki** data source and run:

   - `{service_name="ottl-demo-app"}`: Parsed log records with promoted JSON fields

   JSON fields from the log body such as `order_id`, `message`, `amount`, and `error_code` appear as log attributes.
   The `level` and `timestamp` fields are removed after promotion.
   Severity numbers match the mapped levels: INFO=9, WARN=13, ERROR=17.

2. Select the **Tempo** data source and run `{resource.service.name="ottl-demo-app"}` in **Search**.

   - `app.tier=frontend` on spans with `http.target`, such as `GET /api/orders`
   - `app.tier=backend` on spans with `db.system`, such as `SELECT orders`
   - Long values such as `http.user_agent` and `db.connection_string` truncated to 256 characters
   - `deployment.environment=demo` on trace resources

3. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Add OTTL statements**: Edit the transform processors in `config-otel.yaml`.
- **Change severity mapping**: Edit the `set(severity_number, ...)` statements in `transform/parse-logs`.
- **Adjust truncation**: Change the `truncate_all` limit in `transform/traces`.

## Troubleshoot common problems

Covers startup failures, missing telemetry, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `loki`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No logs or traces in Loki or Tempo

Wait a few seconds for the demo app to send its first batch. It emits telemetry every three seconds.
In Grafana, search Loki for `{service_name="ottl-demo-app"}` and Tempo for `{resource.service.name="ottl-demo-app"}`.
Check Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 3000, 3100, 3200, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/ottl-transform` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OTTL reference: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/pkg/ottl
- More examples: https://github.com/grafana/alloy-scenarios
