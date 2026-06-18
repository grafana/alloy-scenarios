# Telemetry cost control

This scenario shows how to cut observability costs in the Alloy OTel Engine pipeline.
The demo app emits noisy health checks and DEBUG logs alongside `/api/order` and `/api/error` traces.
`config-otel.yaml` filters probe spans and debug logs, samples 25% of remaining traces, and strips high-cardinality span attributes before export.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3100 for Loki, 3200 for Tempo, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

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

- **demo-app**: Flask app on port 8080 that sends health checks, DEBUG logs, and business traces to Alloy over OTLP.
- **Alloy**: Runs the OTel Engine from `config-otel.yaml`. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.
- **Loki**: Stores filtered logs at `http://loki:3100`.
- **Tempo**: Stores sampled traces at `http://tempo:3200`.
- **Grafana**: Queries logs and traces through provisioned Loki and Tempo data sources.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/cost-control`
   - Deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/cost-control && docker compose --env-file ../../image-versions.env up -d --build`

3. From the `cost-control` directory, check that all containers are up: `docker compose ps`

   You should see `demo-app`, `alloy`, `loki`, `tempo`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: Endpoints for health checks, orders, and errors.
- **Grafana** at http://localhost:3000: **Explore** with Loki and Tempo data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Loki** at http://localhost:3100: Log backend API.
- **Tempo** at http://localhost:3200: Trace storage backend.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### Trace pipeline

1. **`filter/traces`**: Drops spans where `http.target` is `/health`, `/ready`, or `/metrics`, or where `http.route` is `/health` or `/ready`.
2. **`probabilistic_sampler`**: Keeps 25% of remaining traces. Change `sampling_percentage` to balance cost and visibility.
3. **`transform/strip`**: Removes `http.user_agent` and `http.request.header.cookie` from spans.
4. **`batch`**: Batches spans before export to Tempo.

### Log pipeline

1. **`filter/logs`**: Drops log records with `severity_number` below 9, which excludes DEBUG logs.
2. **`batch`**: Batches log records before export to Loki.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The background load generator calls `/health` about 70% of the time, `/ready` about 10%, `/api/order` about 15%, and `/api/error` about 5%.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Tempo** data source and run these TraceQL queries:

   - `{resource.service.name="cost-control-demo"}`: Traces from the demo app
   - `{resource.service.name="cost-control-demo" && name="process-order"}`: Order traces that survive filtering
   - `{status=error}`: Error traces from `/api/error`

   Expect `/api/order` and `/api/error` spans in Tempo, not `/health` or `/ready`. The demo app has no `/metrics` endpoint, but `filter/traces` drops it when present.

2. Select the **Loki** data source and run these LogQL queries:

   - `{service_name="cost-control-demo"}`: Logs from the demo app
   - `{service_name="cost-control-demo"} | json`: Parsed log lines

   You should see INFO and ERROR logs but no DEBUG logs.

3. Compare trace volume in Tempo with the app request rate. `probabilistic_sampler` keeps about 25% of non-filtered traces.

4. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Adjust sampling rate**: Edit `sampling_percentage` in `probabilistic_sampler` in `config-otel.yaml`.
- **Change trace filters**: Edit the span conditions in `filter/traces` in `config-otel.yaml`.
- **Change log severity cutoff**: Edit the `severity_number` threshold in `filter/logs` in `config-otel.yaml`.
- **Strip other attributes**: Add statements to `transform/strip` in `config-otel.yaml`.

## Troubleshoot common problems

Covers startup failures, missing telemetry, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `loki`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No traces appear in Tempo after a few minutes

Wait for the background load generator to start. It sleeps five seconds after startup.
Open the Alloy UI at http://localhost:12345 and check that Alloy is running.
In Grafana, search Tempo for `{resource.service.name="cost-control-demo"}`.
Probe traces are filtered out, and only about 25% of remaining traces are sampled.

### No logs appear in Loki after a few minutes

In Grafana, run `{service_name="cost-control-demo"}` on the **Loki** data source.
DEBUG logs are filtered out by design. Call `/api/order` or `/api/error` if you need fresh INFO or ERROR lines.

### Port conflicts with other services

Ports 8080, 3000, 3100, 3200, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/cost-control` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry filter processor: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/filterprocessor
