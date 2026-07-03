# Jaeger and Zipkin trace receivers

This scenario shows how Alloy ingests traces from apps that speak the Jaeger or Zipkin wire protocols instead of OTLP.
A Jaeger client sends Thrift-over-HTTP spans and a Zipkin client sends Zipkin v2 JSON spans, both straight to Alloy.
`otelcol.receiver.jaeger` and `otelcol.receiver.zipkin` in `config.alloy` accept the native formats, batch the spans, and forward everything to Tempo over OTLP, so you don't have to touch the app's tracing code to point it at Alloy.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, 12345 for the Alloy UI, 14268 and 14250 for Jaeger, and 9411 for Zipkin free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------------+      Thrift/HTTP       +-------+       +-------+         +---------+
| jaeger-client  |----------------------->|       |       |       |         |         |
+----------------+                        | Alloy |------>| Tempo |-------->| Grafana |
+----------------+     Zipkin v2 JSON     |       | OTLP  |       |         |         |
| zipkin-client  |----------------------->|       |       |       |         |         |
+----------------+                        +-------+       +-------+         +---------+
                                               ^
                                               |
                                          +------------+
                                          | Prometheus |
                                          +------------+
```

- **jaeger-client**: Python script that creates spans with the OpenTelemetry SDK and exports them as Jaeger Thrift over HTTP to `alloy:14268/api/traces`.
- **zipkin-client**: Python script that creates spans with the OpenTelemetry SDK and exports them as Zipkin v2 JSON to `alloy:9411/api/v2/spans`.
- **Alloy**: Receives Jaeger and Zipkin spans, batches them, and forwards them to Tempo over OTLP.
- **Tempo**: Stores traces. Only its OTLP receiver is enabled, because Alloy already normalizes both trace formats before they arrive.
- **Prometheus**: Scrapes Alloy's own metrics, including per-receiver span counts.
- **Grafana**: Explores traces through the provisioned Tempo data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-jaeger-zipkin-receiver`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Tempo, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh otel-jaeger-zipkin-receiver`

3. From the `otel-jaeger-zipkin-receiver` directory, check that all containers are up: `docker compose ps`

   You should see `jaeger-client`, `zipkin-client`, `alloy`, `tempo`, `prometheus`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Tempo data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph and component health.
- **Tempo** at http://localhost:3200: Trace storage backend.
- **Prometheus** at http://localhost:9090: Alloy self-metrics, including per-receiver span counts.

## Understand the configuration

The `config.alloy` pipeline has four components:

1. **`otelcol.receiver.jaeger.default`**: Listens for Jaeger spans over Thrift HTTP and gRPC, then forwards them to the batch processor. The client in this scenario uses Thrift HTTP.
2. **`otelcol.receiver.zipkin.default`**: Listens for Zipkin v2 JSON spans on its default endpoint, then forwards them to the batch processor.
3. **`otelcol.processor.batch.default`**: Groups spans from both receivers to reduce export requests, then forwards them to the Tempo exporter.
4. **`otelcol.exporter.otlp.tempo`**: Sends spans to Tempo at `tempo:4317` with TLS disabled for the local demo.

`tempo-config.yaml` only enables the `otlp` receiver on `distributor.receivers`, because Alloy already converts Jaeger and Zipkin spans to OTLP before Tempo sees them.

The `jaeger-client` and `zipkin-client` containers are self-contained Python scripts, not instrumented web apps.
Each one builds a small trace with the OpenTelemetry SDK, exports it with a protocol-specific exporter, and repeats every 5 seconds:

- `app/jaeger-client/client.py` uses `opentelemetry-exporter-jaeger-thrift`, pinned to version 1.21.0, to send a `place-order` trace with `charge-card` and `reserve-stock` child spans.
- `app/zipkin-client/client.py` uses `opentelemetry-exporter-zipkin-json`, pinned to version 1.43.0, to send a `checkout` trace with `apply-discount` and `send-confirmation-email` child spans.

Both exporter packages are deprecated in favor of native OTLP support, but they still emit correct Jaeger Thrift and Zipkin JSON on the wire, which is what this scenario needs to exercise Alloy's receivers.

## Try it out

1. Open Grafana at http://localhost:3000, go to **Explore**, select the **Tempo** data source, and open the **Search** tab.
   Run these TraceQL queries:

   - `{resource.service.name="jaeger-demo-client"}`: Traces that arrived over the Jaeger Thrift HTTP receiver
   - `{resource.service.name="zipkin-demo-client"}`: Traces that arrived over the Zipkin receiver
   - `{name="place-order"}`: The Jaeger client's root span
   - `{name="checkout"}`: The Zipkin client's root span

   Open a trace from each service and check that the root span has two child spans.

2. Open Grafana's **Explore**, select the **Prometheus** data source, and run these PromQL queries:

   - `otelcol_receiver_accepted_spans_total{component_id="otelcol.receiver.jaeger.default"}`: Spans accepted over Jaeger Thrift HTTP
   - `otelcol_receiver_accepted_spans_total{component_id="otelcol.receiver.zipkin.default"}`: Spans accepted over Zipkin v2 JSON

   Both counters should climb every 5 seconds as the clients emit new traces.

3. To inspect the Alloy pipeline, open the Alloy UI at http://localhost:12345 and select `otelcol.receiver.jaeger.default`, `otelcol.receiver.zipkin.default`, `otelcol.processor.batch.default`, or `otelcol.exporter.otlp.tempo` from the component graph.

## Customize the scenario

- **Enable Jaeger's UDP protocols**: Add `thrift_binary {}` or `thrift_compact {}` inside the `protocols` block of `otelcol.receiver.jaeger` in `config.alloy`, then publish the matching UDP port in `docker-compose.yml`.
- **Add attribute processing**: Insert an `otelcol.processor.attributes` or `otelcol.processor.transform` component between the receivers and `otelcol.processor.batch.default` to normalize resource attributes from legacy clients.
- **Point a real Jaeger or Zipkin app at Alloy**: Replace `jaeger-client` or `zipkin-client` with your own service and set its collector endpoint to `http://alloy:14268/api/traces` or `http://alloy:9411/api/v2/spans`.

## Troubleshoot common problems

Diagnose container startup failures, missing traces, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `jaeger-client`, `zipkin-client`, or `alloy`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No traces appear in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that `otelcol.receiver.jaeger.default` and `otelcol.receiver.zipkin.default` show a healthy status.
Run `docker compose logs jaeger-client` or `docker compose logs zipkin-client` to check that the client installed its dependencies and is running without errors.
In Grafana, select the **Tempo** data source in **Explore** and search for `{resource.service.name="jaeger-demo-client"}` or `{resource.service.name="zipkin-demo-client"}`.

### Port conflicts with other services

Ports 3000, 3200, 9090, 12345, 14268, 14250, and 9411 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `otel-jaeger-zipkin-receiver` directory.

## Next steps

- `otelcol.receiver.jaeger` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.receiver.jaeger/
- `otelcol.receiver.zipkin` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.receiver.zipkin/
- OpenTelemetry basic tracing scenario: https://github.com/grafana/alloy-scenarios/tree/main/otel-basic-tracing
- More examples: https://github.com/grafana/alloy-scenarios
