# OpenTelemetry SDK metrics across languages

This scenario shows how to instrument five services with the OpenTelemetry metrics SDK and collect their metrics through Grafana Alloy.
Each service plays a role in a fictional online store, written in a different language, and pushes metrics to Alloy over OTLP.
Alloy batches the metrics and forwards them to Prometheus, where you explore them with **Metrics Drilldown**.
The `config.alloy` file defines the pipeline.

Each service runs on its own and emits metrics in a loop about once a second.
No service calls another.
This scenario is the push half of a pair.
Its sibling, the Prometheus client scenario, instruments the same store with native Prometheus client libraries that Alloy scrapes.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, 12345 for Alloy, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

This scenario and its sibling collect the same store metrics with opposite collection models.

| Scenario                                           | Instrumentation                    | Collection model                          |
| -------------------------------------------------- | ---------------------------------- | ----------------------------------------- |
| OpenTelemetry SDK metrics                          | OpenTelemetry metrics SDK          | Services push over OTLP, Alloy receives   |
| [Prometheus client metrics](../prometheus-client/) | Native Prometheus client libraries | Services expose `/metrics`, Alloy scrapes |

## Understand the architecture

```text
+-------------------+       +-------+       +------------+       +---------+
| 5 store services  |       |       |       |            |       |         |
| OTel metrics SDK  |------>| Alloy |------>| Prometheus |------>| Grafana |
|                   | OTLP  |       | OTLP  |            |       |         |
+-------------------+       +-------+       +------------+       +---------+
```

- **Store services**: Five containers named `python`, `node`, `go`, `java`, and `csharp`. Each instruments a store domain with its language's OpenTelemetry metrics SDK and pushes metrics over OTLP.
- **Alloy**: Receives OTLP metrics on port 4317 for gRPC and 4318 for HTTP, batches them, and forwards them to Prometheus.
- **Prometheus**: Stores the metrics through its native OTLP endpoint.
- **Grafana**: Explores the metrics with **Metrics Drilldown**.

Each service sets its own `service.name` and carries its language as a resource attribute.

| Language | Store role            | Service name | OTLP transport    |
| -------- | --------------------- | ------------ | ----------------- |
| Python   | Checkout and payments | `checkout`   | gRPC on port 4317 |
| Node.js  | Product catalog       | `catalog`    | HTTP on port 4318 |
| Go       | Inventory             | `inventory`  | gRPC on port 4317 |
| Java     | Orders                | `orders`     | gRPC on port 4317 |
| C#       | Shipping              | `shipping`   | gRPC on port 4317 |

Node.js uses OTLP over HTTP because the experimental gRPC packages for OpenTelemetry JavaScript are harder to install reliably.
Alloy listens on both ports, so the pipeline handles either transport.
Each service reads its endpoint and protocol from the `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` environment variables.

Every service emits a counter, a histogram, an up-down counter, and an observable gauge, named for its domain.
The checkout service, for example, emits `checkout.transactions.total`, `checkout.payment.duration.ms`, `checkout.active_carts`, and `checkout.queue_depth`.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/app-instrumentation/metrics/opentelemetry-sdk`

3. Build and deploy the scenario: `docker compose up --build -d`

   To use the pinned image versions from `image-versions.env`, run `docker compose --env-file ../../../image-versions.env up --build -d` instead.

4. Confirm all containers are up: `docker compose ps`
   The first build takes a few minutes because the Java and C# images compile from source.

## Explore the services

- **Grafana** at http://localhost:3000: **Metrics Drilldown** and **Explore**, with no login required. Open **Metrics Drilldown** at http://localhost:3000/a/grafana-metricsdrilldown-app.
- **Prometheus** at http://localhost:9090: Metrics storage backend and query UI.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.

## Understand the configuration

The `config.alloy` pipeline has three components: `otelcol.receiver.otlp "default"`, `otelcol.processor.batch "default"`, and `otelcol.exporter.otlphttp "prometheus"`.

1. **`otelcol.receiver.otlp "default"`**: Listens for OTLP metrics on port 4317 for gRPC and 4318 for HTTP, then forwards them to the batch processor.
2. **`otelcol.processor.batch "default"`**: Groups metrics to reduce the number of export requests, then forwards them to the exporter.
3. **`otelcol.exporter.otlphttp "prometheus"`**: Sends the metrics to the Prometheus OTLP endpoint at `http://prometheus:9090/api/v1/otlp`.

Prometheus runs with the `--web.enable-otlp-receiver` flag so it accepts the OTLP write.
The `prom-config.yaml` file promotes the `service.name` and `language` resource attributes to labels, so you can group metrics by service and by language.

## Try it out

1. Open **Metrics Drilldown** at http://localhost:3000/a/grafana-metricsdrilldown-app.

2. Filter by the `service_name` label to focus on a single service, for example `checkout` or `orders`.

3. Open Prometheus at http://localhost:9090 and run a request-rate query:

   ```promql
   sum by (service_name) (rate(checkout_transactions_total[1m]))
   ```

4. Inspect a latency histogram:

   ```promql
   histogram_quantile(0.95, sum by (le) (rate(orders_processing_duration_ms_bucket[5m])))
   ```

5. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345 and select `otelcol.receiver.otlp.default` to use live debug.

## Customize the scenario

- **Add a language**: Add an app directory, then add a service to `docker-compose.yml` with the `OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_*` environment variables. The new service joins the pipeline with no Alloy change.
- **Switch a service to HTTP**: Set `OTEL_EXPORTER_OTLP_ENDPOINT` to `http://alloy:4318` and `OTEL_EXPORTER_OTLP_PROTOCOL` to `http/protobuf` for that service.
- **Transform metrics in Alloy**: Add an `otelcol.processor.transform` block between `otelcol.processor.batch` and `otelcol.exporter.otlphttp` to rename metrics or add attributes.

## Troubleshoot common problems

Diagnose container startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If a container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace _SERVICE_NAME_ with the service that exited, for example `java` or `alloy`.
For Alloy, the most common cause is a syntax error in `config.alloy`.

### No metrics appear in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `otelcol.receiver.otlp.default` and use live debug to confirm metrics arrive from the services.
The services export every five seconds, so allow a short delay before data appears.

### Port conflicts with other services

Ports 3000, 9090, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up --build -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.
Run `docker compose down -v` to remove stored data as well.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `otelcol.receiver.otlp` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.receiver.otlp/
- Prometheus client metrics scenario: [../prometheus-client/](../prometheus-client/)
- OpenTelemetry language SDKs: https://opentelemetry.io/docs/languages/
