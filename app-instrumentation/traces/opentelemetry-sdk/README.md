# OpenTelemetry SDK traces across languages

This scenario shows how to instrument five services with the OpenTelemetry tracing SDK and collect their traces through Grafana Alloy.
Each service plays a role in a fictional online store, written in a different language, and pushes spans to Alloy over OTLP.
Alloy forwards the spans to Tempo, where you explore them with **Traces Drilldown**.
The `config.alloy` file defines the pipeline.

Each service runs on its own and emits one trace in a loop about once a second.
A service traces its own work rather than calling other services, which keeps the focus on how each language creates spans, attributes, events, and errors.
For a trace that spans several services, refer to the [Distributed tracing](../../../trace-delivery/) and [Game of tracing](../../../game-of-tracing/) scenarios.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, 3200 for Tempo, 12345 for Alloy, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------------------+       +-------+       +-------+       +---------+
| 5 store services  |       |       |       |       |       |         |
| OTel tracing SDK  |------>| Alloy |------>| Tempo |------>| Grafana |
|                   | OTLP  |       | OTLP  |       |       |         |
+-------------------+       +-------+       +---+---+       +---------+
                                               | service graph
                                               v and span metrics
                                          +------------+
                                          | Prometheus |
                                          +------------+
```

- **Store services**: Five containers named `python`, `node`, `go`, `java`, and `csharp`. Each instruments a store domain with its language's OpenTelemetry tracing SDK and pushes spans over OTLP.
- **Alloy**: Receives OTLP spans on port 4317 for gRPC and 4318 for HTTP, batches them, and forwards them to Tempo.
- **Tempo**: Stores the traces and generates service-graph and span metrics that it remote-writes to Prometheus.
- **Prometheus**: Stores the generated metrics that power the service graph and request, error, and duration metrics.
- **Grafana**: Explores the traces with **Traces Drilldown**.

Each service sets its own `service.name` and carries its language as a resource attribute.

| Language | Store role | Service name | OTLP transport |
| -------- | ---------- | ------------ | -------------- |
| Python | Checkout and payments | `checkout` | gRPC on port 4317 |
| Node.js | Product catalog | `catalog` | HTTP on port 4318 |
| Go | Inventory | `inventory` | gRPC on port 4317 |
| Java | Orders | `orders` | gRPC on port 4317 |
| C# | Shipping | `shipping` | gRPC on port 4317 |

Node.js uses OTLP over HTTP because the experimental gRPC packages for OpenTelemetry JavaScript are harder to install reliably.
Alloy listens on both ports, so the pipeline handles either transport.
Each service reads its endpoint and protocol from the `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` environment variables.

Every trace has the same shape: a root span with two or three nested child spans, several attributes, and one span event.
About 15 percent of traces record an exception on a child span and set that span's status to error.
The checkout service, for example, traces `process_checkout`, `validate_payment`, and `charge_card`, and records a declined-card error.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/app-instrumentation/traces/opentelemetry-sdk`

3. Build and deploy the scenario: `docker compose up --build -d`

   To use the pinned image versions from `image-versions.env`, run `docker compose --env-file ../../../image-versions.env up --build -d` instead.

4. Confirm all containers are up: `docker compose ps`
   The first build takes a few minutes because the Java and C# images compile from source.

## Explore the services

- **Grafana** at http://localhost:3000: **Traces Drilldown** and **Explore**, with no login required. Open **Traces Drilldown** at http://localhost:3000/a/grafana-exploretraces-app.
- **Tempo** at http://localhost:3200: Trace storage backend.
- **Prometheus** at http://localhost:9090: Stores the service-graph and span metrics that Tempo generates.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.

## Understand the configuration

The `config.alloy` pipeline has three components: `otelcol.receiver.otlp`, `otelcol.processor.batch`, and `otelcol.exporter.otlp`.

1. **`otelcol.receiver.otlp`**: Listens for OTLP spans on port 4317 for gRPC and 4318 for HTTP, then forwards them to the batch processor.
2. **`otelcol.processor.batch`**: Groups spans to reduce the number of export requests, then forwards them to the exporter.
3. **`otelcol.exporter.otlp`**: Sends the spans to Tempo at `tempo:4317`.

The `tempo-config.yaml` file enables the metrics generator with the `service-graphs` and `span-metrics` processors.
Tempo remote-writes the generated metrics to Prometheus, which powers the service graph and the request, error, and duration metrics in Grafana.

## Try it out

1. Open **Traces Drilldown** at http://localhost:3000/a/grafana-exploretraces-app.
   You see five services. Drill into the rate, errors, and duration for each one.

2. To find the simulated failures, open **Explore**, select the **Tempo** data source, and run a TraceQL query in **Search**:

   ```text
   {status=error}
   ```

3. To view the dependency graph, open **Service Graph** on the **Tempo** data source.
   The graph populates from the metrics that Tempo generates.

4. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345 and select `otelcol.receiver.otlp.default` to use live debug.

## Customize the scenario

- **Add a language**: Add an app directory, then add a service to `docker-compose.yml` with the `OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_*` environment variables. The new service joins the pipeline with no Alloy change.
- **Sample traces**: Add an `otelcol.processor.tail_sampling` block before the exporter to keep only error or slow traces. The [OpenTelemetry tail sampling](../../../otel-tail-sampling/) scenario shows this pattern.
- **Generate span metrics in Alloy**: Add an `otelcol.connector.spanmetrics` block to generate request, error, and duration metrics in Alloy instead of Tempo. The [OpenTelemetry span metrics](../../../otel-span-metrics/) scenario shows this pattern.

## Troubleshoot common problems

Diagnose container startup failures, missing traces, an empty service graph, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If a container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace _SERVICE_NAME_ with the service that exited, for example `java` or `alloy`.
For Alloy, the most common cause is a syntax error in `config.alloy`.

### No traces appear in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `otelcol.receiver.otlp.default` and use live debug to confirm spans arrive from the services.
Then check that the `tempo` container is healthy with `docker compose ps`.

### The service graph is empty

The service graph populates from metrics that Tempo generates and remote-writes to Prometheus.
Allow a minute or two after the first traces arrive for the metrics to appear.
Check that the `prometheus` and `tempo` containers are healthy with `docker compose ps`.

### Port conflicts with other services

Ports 3000, 9090, 3200, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up --build -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.
Run `docker compose down -v` to remove stored data as well.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `otelcol.exporter.otlp` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.otlp/
- Distributed tracing scenario: [../../../trace-delivery/](../../../trace-delivery/)
- OpenTelemetry language SDKs: https://opentelemetry.io/docs/languages/
