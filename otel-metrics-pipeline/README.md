# OpenTelemetry metrics pipeline

This scenario shows a full OpenTelemetry metrics pipeline through Grafana Alloy.
A Python app generates counters, histograms, and up-down counters with the OpenTelemetry SDK and sends them to Alloy over OTLP.
Alloy batches the metrics, adds a `deployment.environment` resource attribute, and exports them to Prometheus over OTLP/HTTP for visualization in Grafana.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +-------+       +-------------+       +---------+
| app              | OTLP  | Alloy | OTLP  | Prometheus  |       |         |
| demo-metrics-app |------>| batch | HTTP  | OTLP rcvr   |------>| Grafana |
|                  | gRPC  | xform |       |             |       |         |
+------------------+       +-------+       +-------------+       +---------+
```

- **app**: Python container that emits OTLP metrics every second to `alloy:4317` over gRPC.
- **Alloy**: Receives OTLP metrics, batches them, adds `deployment.environment = "demo"`, and exports to Prometheus at `http://prometheus:9090/api/v1/otlp`.
- **Prometheus**: Ingests metrics through its native OTLP receiver with native histogram support enabled.
- **Grafana**: Queries metrics through a provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-metrics-pipeline`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh otel-metrics-pipeline`

3. From the `otel-metrics-pipeline` directory, check that all containers are up: `docker compose ps`

   You should see `app`, `alloy`, `prometheus`, and `grafana`.

   The `app` container installs Python dependencies on first start, so metrics may take a minute to appear.

## Explore the services

- **Grafana** at http://localhost:3000: Query metrics in **Explore** with the Prometheus data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query ingested OTLP metrics directly.

## Understand the Alloy pipeline

The `config.alloy` pipeline has four components:

1. **`otelcol.receiver.otlp.default`**: Receives OTLP metrics over gRPC and HTTP.
2. **`otelcol.processor.batch.default`**: Batches metrics for efficient export.
3. **`otelcol.processor.transform.default`**: Sets `deployment.environment = "demo"` on the resource.
4. **`otelcol.exporter.otlphttp.prometheus`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/otlp`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

The demo app emits these OTLP metrics:

- `app.requests.total`: Counter of HTTP requests by endpoint, method, and status
- `app.errors.total`: Counter of errors by endpoint
- `app.request.duration`: Histogram of request latency in milliseconds
- `app.active_users`: Up-down counter of active users by region

Prometheus translates OTLP names to its naming conventions. Dots become underscores and units are appended as suffixes.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Prometheus** data source and run these PromQL queries:

   - `app_requests_total`: Total requests by endpoint, method, and status
   - `app_errors_total`: Total errors by endpoint
   - `app_request_duration_milliseconds_bucket`: Request latency histogram buckets
   - `app_active_users`: Current active users by region
   - `app_requests_total{deployment_environment="demo"}`: Requests with the resource attribute added by Alloy

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `otelcol.receiver.otlp.default`, `otelcol.processor.batch.default`, `otelcol.processor.transform.default`, or `otelcol.exporter.otlphttp.prometheus` from the component graph to use live debug.

## Customize the scenario

- **Change attribute transforms**: Edit `otelcol.processor.transform.default` in `config.alloy`.
- **Use the OTel Engine**: Run `docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d` to load the equivalent pipeline from `config-otel.yaml` instead of River syntax.
- **Promote more resource attributes**: Edit `otlp.promote_resource_attributes` in `prom-config.yaml`.

## Troubleshoot common problems

Diagnose container startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `app`, `alloy`, or `prometheus`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No metrics appear after a few minutes

The `app` container runs `pip install` on first start, which can take up to a minute.
Run `docker compose logs app` and check that you see `Starting OTLP metrics generator...`.
Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
In Grafana, select the **Prometheus** data source in **Explore** and run `app_requests_total`.

### Port conflicts with other services

Ports 3000 for Grafana, 9090 for Prometheus, 12345 for Alloy, and 4317 and 4318 for OTLP must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `otel-metrics-pipeline` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `otelcol.processor.transform` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.transform/
- Prometheus OTLP receiver: https://prometheus.io/docs/guides/opentelemetry/
- More examples: https://github.com/grafana/alloy-scenarios
