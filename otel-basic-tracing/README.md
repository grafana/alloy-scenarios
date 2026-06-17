# OpenTelemetry basic tracing

This scenario shows how to collect and visualize OpenTelemetry traces with Grafana Alloy and Tempo.
A Python Flask demo app generates traces with the OpenTelemetry SDK and sends them to Alloy over OTLP.
Alloy batches spans and forwards them to Tempo, which generates service-graph and span metrics and remote-writes them to Prometheus for visualization in Grafana.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +-------+       +-------+         +---------+
| demo-app         |       |       |       |       |         |         |
| Flask + OTel SDK |------>| Alloy |------>| Tempo |-------->| Grafana |
|                  | OTLP  |       | OTLP  |       |         |         |
+------------------+       +-------+       +---+---+         +---------+
                                               | service graph    ^
                                               v and span metrics |
                                          +------------+          |
                                          | Prometheus |----------+
                                          +------------+
```

- **demo-app**: Flask app on port 8080 that creates spans with the OpenTelemetry SDK and exports them to Alloy at `alloy:4317` over gRPC.
- **Alloy**: Receives OTLP traces, batches them, and forwards them to Tempo.
- **Tempo**: Stores traces and runs the metrics generator with service-graph, span-metrics, and local-blocks processors. Uses Memcached as a query cache.
- **Prometheus**: Stores the metrics Tempo generates for service graphs and RED metrics.
- **Grafana**: Explores traces through the provisioned Tempo data source and service graphs through Prometheus.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-basic-tracing`
   - Build and deploy the scenario: `docker compose up --build -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Tempo, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh otel-basic-tracing`

3. From the `otel-basic-tracing` directory, check that all containers are up: `docker compose ps`

   You should see `demo-app`, `alloy`, `tempo`, `prometheus`, `memcached`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: Home page with links to trace-generating endpoints.
- **Grafana** at http://localhost:3000: **Explore** and the **Traces Drilldown** app, with no login required. Open **Traces Drilldown** at http://localhost:3000/a/grafana-exploretraces-app.
- **Alloy UI** at http://localhost:12345: Pipeline graph and component health.
- **Tempo** at http://localhost:3200: Trace storage backend.
- **Prometheus** at http://localhost:9090: Stores service-graph and span metrics from Tempo.

## Understand the Alloy pipeline

The `config.alloy` pipeline has three components:

1. **`otelcol.receiver.otlp.default`**: Listens for OTLP traces over gRPC and HTTP, then forwards spans to the batch processor.
2. **`otelcol.processor.batch.default`**: Groups spans to reduce export requests, then forwards them to the Tempo exporter.
3. **`otelcol.exporter.otlp.tempo`**: Sends spans to Tempo at `tempo:4317` with TLS disabled for the local demo.

The `tempo-config.yaml` file enables the metrics generator with `service-graphs`, `span-metrics`, and `local-blocks` processors.
Tempo remote-writes the generated metrics to Prometheus, which powers the service graph and request, error, and duration views in Grafana.

## Try it out

1. Open the demo app at http://localhost:8080 and call these endpoints to generate traces:

   - `/simple`: A single-span trace
   - `/nested`: Parent and child spans with a grandchild span
   - `/error`: A trace that records an exception
   - `/chain`: A chain of HTTP calls through simulated services B and C
   - `/delayed-chain`: A longer chain where service D adds high latency

2. Open Grafana at http://localhost:3000, go to **Explore**, select the **Tempo** data source, and open the **Search** tab.
   Run these TraceQL queries:

   - `{resource.service.name="trace-demo"}`: Traces from the demo app
   - `{status=error}`: Traces that include an error status
   - `{name="chain-root"}`: Traces from the `/chain` endpoint

3. To view the service graph, select the **Tempo** data source in **Explore** and open the **Service Graph** tab.
   Generate traffic with `/chain` or `/delayed-chain` first so Tempo has enough spans to build the graph.

4. To inspect the Alloy pipeline, open the Alloy UI at http://localhost:12345 and select `otelcol.receiver.otlp.default`, `otelcol.processor.batch.default`, or `otelcol.exporter.otlp.tempo` from the component graph.

## Customize the scenario

- **Add processors or exporters**: Edit `config.alloy` to add sampling, attribute filtering, or additional exporters.
- **Use the OTel Engine**: Run `docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d` to load the equivalent pipeline from `config-otel.yaml` instead of River syntax.
- **Change trace retention**: Edit `compactor.compaction.block_retention` in `tempo-config.yaml`.

## Troubleshoot common problems

Diagnose container startup failures, missing traces, an empty service graph, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `tempo`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No traces appear in Grafana after a few minutes

Open the demo app at http://localhost:8080 and call `/simple` to generate a trace.
Open the Alloy UI at http://localhost:12345 and check that `otelcol.receiver.otlp.default` and `otelcol.exporter.otlp.tempo` show a healthy status.
In Grafana, select the **Tempo** data source in **Explore** and search for `{resource.service.name="trace-demo"}`.

### Service graph is empty

The service graph needs multiple spans across related operations.
Call `/chain` or `/delayed-chain` several times, wait about a minute for Tempo to generate metrics, then open the **Service Graph** tab on the **Tempo** data source.

### Port conflicts with other services

Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `otel-basic-tracing` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `otelcol.receiver.otlp` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.receiver.otlp/
- Tempo metrics generator: https://grafana.com/docs/tempo/latest/metrics-generator/
- More examples: https://github.com/grafana/alloy-scenarios
