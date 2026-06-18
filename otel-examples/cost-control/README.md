# Telemetry cost control

This scenario shows how to reduce observability costs by filtering noisy telemetry and applying probabilistic sampling in the Alloy OTel Engine pipeline before data reaches your backends.

The demo app generates high-volume health checks, DEBUG logs, and occasional business traces.
The OTel YAML config in `config-otel.yaml` drops probe traffic, filters debug logs, samples traces, and strips high-cardinality attributes.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3100 for Loki, 3200 for Tempo, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+     +-------+     +------+     +---------+
| demo-app |     |       |---->| Loki |---->|         |
|          | OTLP| Alloy |     +------+     | Grafana |
|          |---->| OTel  |---->| Tempo|---->|         |
+----------+     +-------+     +------+     +---------+
```

- **demo-app**: Flask app on port 8080 that emits noisy health checks, DEBUG logs, and business traces to Alloy over OTLP.
- **Alloy**: Runs the OTel Engine with `config-otel.yaml` and exposes the Alloy UI through the `alloyengine` extension in `config.alloy`.
- **Loki**: Stores filtered logs at `http://loki:3100`.
- **Tempo**: Stores sampled traces at `http://tempo:3200`.
- **Grafana**: Queries logs and traces through provisioned Loki and Tempo data sources.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-examples/cost-control`
   - Build and deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/cost-control && docker compose --env-file ../../image-versions.env up -d --build`

3. From the `cost-control` directory, check that all containers are up: `docker compose ps`

   You should see `demo-app`, `alloy`, `loki`, `tempo`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: Endpoints for health checks, orders, and errors.
- **Grafana** at http://localhost:3000: **Explore** with Loki and Tempo data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline debugging UI enabled by the `alloyengine` extension.
- **OTel Engine HTTP server** at http://localhost:8888: OTel Engine health and diagnostics endpoint.
- **Loki** at http://localhost:3100: Log backend API.
- **Tempo** at http://localhost:3200: Trace storage backend.

## Understand the OTel pipeline

The pipeline is defined in `config-otel.yaml`. The `config.alloy` file is minimal and only enables the Alloy UI alongside the OTel Engine.

Trace pipeline:

1. **`filter/traces`**: Drops spans where `http.target` or `http.route` matches `/health`, `/ready`, or `/metrics`.
2. **`probabilistic_sampler`**: Keeps 25% of remaining traces through head-based sampling.
3. **`transform/strip`**: Removes `http.user_agent` and `http.request.header.cookie` from spans.
4. **`batch`**: Batches spans before export to Tempo.

Log pipeline:

1. **`filter/logs`**: Drops log records with `severity_number` below 9, which excludes DEBUG logs.
2. **`batch`**: Batches log records before export to Loki.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`.

## Try it out

The demo app's background load generator calls `/health` about 70% of the time, `/ready` about 10%, `/api/order` about 15%, and `/api/error` about 5%.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Tempo** data source and run these TraceQL queries:

   - `{resource.service.name="cost-control-demo"}`: Traces from the demo app
   - `{span.http.route="/api/order"}`: Business order traces that pass filtering
   - `{status=error}`: Error traces from `/api/error`

   You should see `/api/order` and `/api/error` spans but no `/health` or `/ready` spans. Those probe traces are dropped by `filter/traces`.

2. Select the **Loki** data source and run these LogQL queries:

   - `{service_name="cost-control-demo"}`: All logs that passed filtering
   - `{service_name="cost-control-demo"} | json`: Parsed log lines from the demo app

   You should see INFO and ERROR logs but no DEBUG logs.

3. Compare sampling volume in Tempo with the app's request rate. Only about 25% of non-filtered traces are kept by `probabilistic_sampler`.

4. Open the Alloy UI at http://localhost:12345 to inspect the OTel pipeline, or visit http://localhost:8888 for the OTel Engine HTTP server.

## Customize the scenario

- **Adjust sampling rate**: Edit `sampling_percentage` in `probabilistic_sampler` in `config-otel.yaml`.
- **Change trace filters**: Edit the span conditions in `filter/traces` in `config-otel.yaml`.
- **Change log severity cutoff**: Edit the `severity_number` threshold in `filter/logs` in `config-otel.yaml`.
- **Strip other attributes**: Add statements to `transform/strip` in `config-otel.yaml`.

## Troubleshoot common problems

Diagnose container startup failures, missing telemetry, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `loki`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No traces appear in Tempo after a few minutes

Wait for the demo app's background load generator to start. It sleeps five seconds after startup.
Open the Alloy UI at http://localhost:12345 and check that Alloy is running.
In Grafana, search Tempo for `{resource.service.name="cost-control-demo"}`.
Remember that probe traces are filtered and only about 25% of remaining traces are sampled.

### No logs appear in Loki after a few minutes

In Grafana, run `{service_name="cost-control-demo"}` on the **Loki** data source.
DEBUG logs are filtered out by design. Trigger an order or error request if you need fresh INFO or ERROR lines.

### Port conflicts with other services

Ports 8080, 3000, 3100, 3200, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/cost-control` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry filter processor: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/filterprocessor
- More examples: https://github.com/grafana/alloy-scenarios
