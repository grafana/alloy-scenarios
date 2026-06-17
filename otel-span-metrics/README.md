# OpenTelemetry span metrics

This scenario shows how to generate RED metrics — request rate, error rate, and duration — from OpenTelemetry traces with Grafana Alloy's `otelcol.connector.spanmetrics` component.

Instead of relying on Tempo's built-in metrics generator, Alloy derives metrics directly from trace spans in the pipeline.
That gives you control over which dimensions are extracted and how histograms are configured.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 5000 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------+       +-------+       +-------------+       +---------+
| app   | OTLP  | Alloy | OTLP  | Prometheus  |       |         |
| load  |------>| batch | HTTP  | RED metrics |------>| Grafana |
+-------+       |       |       +-------------+       |         |
                |       |------>| Tempo       |------>|         |
                |       | OTLP  | traces      |       |         |
                +-------+       +-------------+       +---------+
```

- **app**: Flask demo app on port 5000 that creates spans and exports them to Alloy over OTLP.
- **load**: Python script that continuously calls app endpoints to generate trace traffic.
- **Alloy**: Receives traces, batches them, forwards spans to Tempo, and generates RED metrics with `otelcol.connector.spanmetrics`.
- **Prometheus**: Ingests span metrics through its native OTLP receiver.
- **Tempo**: Stores traces. This scenario does not enable Tempo's metrics generator.
- **Grafana**: Queries Prometheus for RED metrics and Tempo for traces.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-span-metrics`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Tempo, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh otel-span-metrics`

3. From the `otel-span-metrics` directory, check that all containers are up: `docker compose ps`

   You should see `app`, `load`, `alloy`, `prometheus`, `tempo`, `memcached`, and `grafana`.

   The `app` and `load` containers install Python dependencies on first start, so metrics may take a minute to appear.

## Explore the services

- **Demo app** at http://localhost:5000: Flask endpoints that generate traces.
- **Grafana** at http://localhost:3000: **Explore** with Prometheus and Tempo data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: RED metrics from the spanmetrics connector.
- **Tempo** at http://localhost:3200: Trace storage backend.

## Understand the Alloy pipeline

The `config.alloy` pipeline has these components:

1. **`otelcol.receiver.otlp.default`**: Receives OTLP traces over gRPC and HTTP.
2. **`otelcol.processor.batch.default`**: Batches traces and forwards them to both the spanmetrics connector and Tempo.
3. **`otelcol.connector.spanmetrics.default`**: Derives RED metrics from spans with `http.method` and `http.status_code` dimensions and a 5-second flush interval.
4. **`otelcol.exporter.otlphttp.prometheus`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/otlp`.
5. **`otelcol.exporter.otlp.tempo`**: Sends traces to Tempo at `tempo:4317`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

The spanmetrics connector produces these metrics from every span:

- `duration_milliseconds`: Histogram of span durations
- `calls`: Counter of span calls with a `status_code` label

## Try it out

Once the load generator has been active for about a minute, open Grafana at http://localhost:3000 and go to **Explore**.
Select the **Prometheus** data source and run these PromQL queries:

- `rate(duration_milliseconds_count[5m])`: Request rate by service and span name
- `rate(calls{status_code="STATUS_CODE_ERROR"}[5m])`: Error rate for spans with error status
- `histogram_quantile(0.95, rate(duration_milliseconds_bucket[5m]))`: P95 latency by span name

To inspect traces, select the **Tempo** data source and search for `{resource.service.name="demo-app"}`.

To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345 and select `otelcol.connector.spanmetrics.default` or other components from the component graph to use live debug.

## Customize the scenario

- **Add span dimensions**: Add `dimension` blocks to `otelcol.connector.spanmetrics.default` in `config.alloy`.
- **Change histogram buckets**: Edit the `histogram.explicit` block in `otelcol.connector.spanmetrics.default` in `config.alloy`.
- **Use the OTel Engine**: Run `docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d` to load the equivalent pipeline from `config-otel.yaml` instead of River syntax.

## Troubleshoot common problems

Diagnose container startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `app`, `load`, `alloy`, or `prometheus`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No metrics appear after a few minutes

The `app` and `load` containers run `pip install` on first start, which can take up to a minute.
Run `docker compose logs load` to check that the load generator is calling app endpoints.
Open the Alloy UI at http://localhost:12345 and check that `otelcol.connector.spanmetrics.default` shows a healthy status.
In Grafana, select the **Prometheus** data source in **Explore** and run `rate(duration_milliseconds_count[5m])`.

### Port conflicts with other services

Ports 5000 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, 12345 for Alloy, and 4317 and 4318 for OTLP must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `otel-span-metrics` directory.

## Next steps

- `otelcol.connector.spanmetrics` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.connector.spanmetrics/
- OpenTelemetry basic tracing scenario: https://github.com/grafana/alloy-scenarios/tree/main/otel-basic-tracing
- More examples: https://github.com/grafana/alloy-scenarios
