# Count connector

This scenario shows how to derive count metrics from traces and logs with the OTel count connector, without extra application instrumentation.
The demo app sends spans and log records to Alloy over OTLP.
The count connector emits `span.count`, `span.error.count`, `log.count`, and `log.error.count` to Prometheus while the original traces and logs go to Tempo and Loki.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3100 for Loki, 3200 for Tempo, 9090 for Prometheus, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+     +-------------+     +-------------+     +---------+
| demo-app |     |             |---->| Prometheus  |---->|         |
|          | OTLP| Alloy OTel  |     +-------------+     | Grafana |
|          |---->| Engine      |---->| Tempo       |---->|         |
+----------+     |             |     +-------------+     |         |
                 |             |---->| Loki        |---->|         |
                 +-------------+     +-------------+     +---------+
```

- **demo-app**: Flask app on port 8080 that emits OK and error traces plus INFO, WARN, and ERROR logs.
- **Alloy**: Runs the OTel Engine from `config-otel.yaml`. The count connector derives metrics from incoming traces and logs and sends them to Prometheus. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.
- **Prometheus**: Stores derived count metrics through its OTLP receiver.
- **Tempo**: Stores original traces.
- **Loki**: Stores original logs.
- **Grafana**: Queries Prometheus, Tempo, and Loki through provisioned data sources.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/count-connector`
   - Deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/count-connector && docker compose --env-file ../../image-versions.env up -d --build`

3. From the `count-connector` directory, check that all containers are up: `docker compose ps`

   Expect `demo-app`, `alloy`, `loki`, `prometheus`, `tempo`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: `/api/process`, `/api/notify`, and `/health`.
- **Grafana** at http://localhost:3000: **Explore** with Prometheus, Tempo, and Loki data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Prometheus** at http://localhost:9090: Derived count metrics.
- **Loki** at http://localhost:3100: Log backend API.
- **Tempo** at http://localhost:3200: Trace storage backend.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### Count connector metrics

`connectors/count` defines four derived metrics:

- `span.count`: Total spans received
- `span.error.count`: Spans where `status.code == 2`
- `log.count`: Total log records received
- `log.error.count`: Log records where `severity_number >= 17`

The count connector acts as an exporter in the trace and log pipelines and as a receiver in the metrics pipeline.

### Pipeline wiring

1. **Traces**: `otlp` → `batch` → `count` and `otlp/tempo`
2. **Logs**: `otlp` → `batch` → `count` and `otlphttp/loki`
3. **Metrics**: `count` → `deltatocumulative` → `batch` → `otlphttp/prometheus`

`deltatocumulative` converts delta temporality from the count connector into cumulative metrics for Prometheus.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The background load generator calls `/api/process` or `/api/notify` every two seconds and emits standalone INFO, WARN, and ERROR log lines.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Prometheus** data source and run these PromQL queries:

   - `rate(span_count_total[5m])`: Span throughput
   - `rate(span_error_count_total[5m])`: Error span throughput
   - `rate(span_error_count_total[5m]) / rate(span_count_total[5m]) * 100`: Error span rate as a percentage
   - `rate(log_count_total[5m])`: Log record throughput
   - `rate(log_error_count_total[5m])`: Error log throughput

2. Select the **Tempo** data source and run `{resource.service.name="count-connector-demo"}` in **Search**.
   Expect both OK and error traces from `/api/process` and `/api/notify`.

3. Select the **Loki** data source and run `{service_name="count-connector-demo"} | json`.
   Expect INFO, WARN, and ERROR log lines.

4. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Add count metrics**: Edit `connectors/count` in `config-otel.yaml`.
- **Change error conditions**: Edit the `conditions` blocks for `span.error.count` or `log.error.count` in `config-otel.yaml`.
- **Point at another Prometheus**: Update `otlphttp/prometheus` in `config-otel.yaml`.

## Troubleshoot common problems

Covers startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `prometheus`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### Derived metrics are missing in Prometheus

Wait for the background load generator to start. It sleeps five seconds after startup.
In Grafana, select the **Prometheus** data source in **Explore** and run `rate(span_count_total[5m])`.
Open http://localhost:8888 to check OTel Engine telemetry.

### No traces or logs in Tempo or Loki

In Grafana, search Tempo for `{resource.service.name="count-connector-demo"}` and Loki for `{service_name="count-connector-demo"}`.
Call http://localhost:8080/api/process if you need fresh data.

### Port conflicts with other services

Ports 8080, 3000, 3100, 3200, 9090, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/count-connector` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry count connector: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/countconnector
- More examples: https://github.com/grafana/alloy-scenarios
