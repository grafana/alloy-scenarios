# OpenTelemetry service graphs

This scenario shows how to generate service graphs from OpenTelemetry traces with Grafana Alloy's `otelcol.connector.servicegraph` component and send the metrics to Prometheus over OTLP/HTTP.
A Python Flask demo app generates traces, Alloy derives service-graph metrics and forwards traces to Tempo, and Grafana visualizes both traces and the service map.

This approach uses Alloy for service graph generation instead of the built-in service-graph metrics processor in Tempo.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +----------------------+       +-------+       +---------+
| demo-app         | OTLP  | Alloy                | OTLP  |       |       |         |
| Flask + OTel SDK |------>| +------------------+ |------>| Tempo |------>| Grafana |
+------------------+       | | servicegraph     | |       |       |       |         |
                           | +--------+---------+ |       +-------+       +---------+
                           |          |           |                           ^
                           +----------|-----------+                           |
                                      | OTLP HTTP                             |
                                      v                                       |
                                 +------------+                               |
                                 | Prometheus |-------------------------------+
                                 +------------+
```

- **demo-app**: Flask app on port 8080 that creates spans and exports them to Alloy over OTLP.
- **Alloy**: Batches traces, generates service-graph metrics with `otelcol.connector.servicegraph`, sends metrics to Prometheus, and forwards traces to Tempo.
- **Prometheus**: Ingests service-graph metrics through its native OTLP receiver.
- **Tempo**: Stores traces. The Tempo configuration enables only the `local-blocks` metrics processor, not service-graph generation.
- **Memcached**: Query cache for Tempo.
- **Grafana**: Queries Tempo for traces and Prometheus for the service graph through linked data sources.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-tracing-service-graphs`
   - Build and deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Tempo, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh otel-tracing-service-graphs`

3. From the `otel-tracing-service-graphs` directory, check that all containers are up: `docker compose ps`

   You should see `demo-app`, `alloy`, `tempo`, `prometheus`, `memcached`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: Home page with links to trace-generating endpoints.
- **Grafana** at http://localhost:3000: **Explore** and **Traces Drilldown**, with no login required. Open **Traces Drilldown** at http://localhost:3000/a/grafana-exploretraces-app.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Tempo** at http://localhost:3200: Trace storage backend.
- **Prometheus** at http://localhost:9090: Service-graph metrics from Alloy.

## Understand the Alloy pipeline

The `config.alloy` pipeline has these components:

1. **`otelcol.receiver.otlp.default`**: Receives OTLP traces over gRPC and HTTP.
2. **`otelcol.processor.batch.default`**: Batches traces and forwards them to the service graph connector and Tempo exporter.
3. **`otelcol.connector.servicegraph.default`**: Derives service-graph metrics with `metrics_flush_interval = "10s"` and dimensions `service.name` and `http.method`.
4. **`otelcol.exporter.otlphttp.prometheus`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/otlp`.
5. **`otelcol.exporter.otlp.tempo`**: Sends traces to Tempo at `tempo:4317`.

The service graph connector stores recent spans in memory with `store.max_items = 5000` and `store.ttl = "30s"` to pair client and server spans.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

Prometheus promotes selected resource attributes such as `service.name` and `deployment.environment` to labels through its OTLP configuration in `prom-config.yaml`.

The connector produces metrics such as:

- `calls_total`: Total calls between services
- `calls_failed_total`: Failed calls between services
- `latency`: Histogram of latencies between services

## Try it out

1. Open the demo app at http://localhost:8080 and generate traffic that spans multiple services.
   Call `/multi-service` or `/chain` several times to build edges in the graph.

2. Open Grafana at http://localhost:3000, select the **Tempo** data source in **Explore**, and open the **Service Graph** tab.
   Wait about a minute after generating traffic for metrics to flush and appear.

3. Select the **Prometheus** data source in **Explore** and run these PromQL queries:

   - `calls_total`: Total calls between services
   - `calls_failed_total`: Failed calls between services
   - `histogram_quantile(0.95, rate(latency_bucket[5m]))`: P95 latency between services

4. Select the **Tempo** data source and run these TraceQL queries in **Search**:

   - `{resource.service.name="trace-demo"}`: Traces from the default demo app service
   - `{status=error}`: Traces that include an error status

5. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345 and select `otelcol.connector.servicegraph.default` from the component graph to use live debug.

### Demo app endpoints

- `/simple`: Single-span trace
- `/nested`: Parent and child spans
- `/error`: Trace that records an exception
- `/chain`: HTTP chain through simulated services B and C
- `/delayed-chain`: Longer chain with high-latency service D
- `/multi-service`: Trace with distinct `service.name` values such as `web-ui` and `api-gateway`

## Customize the scenario

- **Add service graph dimensions**: Edit the `dimensions` list in `otelcol.connector.servicegraph.default` in `config.alloy`.
- **Tune span pairing**: Edit `store.max_items` or `store.ttl` in `otelcol.connector.servicegraph.default` in `config.alloy`.
- **Promote more resource attributes**: Edit `otlp.promote_resource_attributes` in `prom-config.yaml`.
- **Use the OTel Engine**: Run `docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d --build` to load the equivalent pipeline from `config-otel.yaml` instead of River syntax.

## Troubleshoot common problems

Diagnose container startup failures, an empty service graph, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `tempo`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### Service graph is empty

The service graph needs traces that span multiple services with paired client and server spans.
Call `/multi-service` or `/chain` several times, wait at least 10 seconds for the connector flush interval, then open the **Service Graph** tab on the **Tempo** data source.
In Grafana, select the **Prometheus** data source in **Explore** and run `calls_total` to check whether metrics arrived.

### No traces appear in Tempo

Open the Alloy UI at http://localhost:12345 and check that `otelcol.exporter.otlp.tempo` shows a healthy status.
Call `/simple` on the demo app, then search Tempo for `{resource.service.name="trace-demo"}`.

### Port conflicts with other services

Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-tracing-service-graphs` directory.

## Next steps

- `otelcol.connector.servicegraph` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.connector.servicegraph/
- OpenTelemetry span metrics scenario: https://github.com/grafana/alloy-scenarios/tree/main/otel-span-metrics
- Prometheus OTLP receiver: https://prometheus.io/docs/guides/opentelemetry/
- More examples: https://github.com/grafana/alloy-scenarios
