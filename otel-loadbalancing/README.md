# OpenTelemetry trace-aware load balancing

Tail sampling only works if a single instance sees every span of a trace — and a single instance is exactly what you don't want in a highly available sampling tier.
This scenario shows the standard answer: a load-balancer Alloy in front that shards traffic across two tail-sampling Alloys by trace ID with [`otelcol.exporter.loadbalancing`](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.loadbalancing/).

The generator makes the problem real: it exports every span in its own OTLP request.
A round-robin balancer would scatter the four spans of each trace across both downstreams, and tail sampling would make contradictory half-trace decisions.
`routing_key = "traceID"` reassembles the stream so each downstream sees whole traces.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, 12345 for the load-balancer Alloy UI, 12346 and 12347 for the downstream Alloy UIs, and 4317 and 4318 for OTLP on the load-balancer tier free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +----------+       +---------------------+       +-------+       +---------+
| trace-generator  | OTLP  | alloy-lb |------>| alloy-downstream-1  |------>|       |       |         |
| 1 trace / sec    |------>| traceID  |       | tail sampling       |       | Tempo |------>| Grafana |
| 4 spans / trace  |       | routing  |------>| alloy-downstream-2  |------>|       |       |         |
+------------------+       +----------+       +---------------------+       +-------+       +---------+
```

- **trace-generator**: Emits one `checkout` trace per second with exactly four spans and exports each span in its own OTLP request to `alloy-lb:4317`.
- **alloy-lb**: Receives OTLP traces and forwards them with `otelcol.exporter.loadbalancing` using `routing_key = "traceID"` and a static resolver for the two downstream hosts.
- **alloy-downstream-1** and **alloy-downstream-2**: Identical tail-sampling tiers that keep error traces and traces slower than 2 seconds, then forward sampled spans to Tempo.
- **Tempo**: Shared trace backend for both downstream instances.
- **Prometheus**: Scrapes all three Alloy instances so you can compare span rates per downstream.
- **Grafana**: Queries Tempo for traces and Prometheus for Alloy metrics.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-loadbalancing`
   - Build and deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Tempo, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh otel-loadbalancing`

3. From the `otel-loadbalancing` directory, check that all containers are up: `docker compose ps`

   You should see `trace-generator`, `alloy-lb`, `alloy-downstream-1`, `alloy-downstream-2`, `tempo`, `prometheus`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with Tempo and Prometheus data sources, with no login required.
- **Alloy UI, load-balancer tier** at http://localhost:12345: Pipeline for `config-lb.alloy`.
- **Alloy UI, downstream 1** at http://localhost:12346: Tail-sampling pipeline for `config-downstream.alloy`.
- **Alloy UI, downstream 2** at http://localhost:12347: Same downstream pipeline on the second instance.
- **Prometheus** at http://localhost:9090: Alloy self-metrics scraped from each instance.
- **Tempo** at http://localhost:3200: Trace storage backend.

## Understand the Alloy pipeline

This scenario uses two Alloy configurations.

### Load-balancer tier

`config-lb.alloy` defines:

1. **`otelcol.receiver.otlp.default`**: Receives OTLP traces over gRPC and HTTP on the load-balancer tier.
2. **`otelcol.exporter.loadbalancing.default`**: Routes spans to `alloy-downstream-1:4317` or `alloy-downstream-2:4317` using consistent hashing on `routing_key = "traceID"`.

### Downstream tier

Both downstream instances run `config-downstream.alloy`:

1. **`otelcol.receiver.otlp.default`**: Receives the trace shard from the load balancer.
2. **`otelcol.processor.tail_sampling.default`**: Buffers spans for `decision_wait = "5s"`, then keeps traces with an error status or end-to-end latency above 2000 ms. There is no probabilistic fallback, so every sampling decision is explainable.
3. **`otelcol.processor.batch.default`**: Batches sampled spans before export.
4. **`otelcol.exporter.otlp.tempo`**: Sends kept traces to Tempo at `tempo:4317`.

`livedebugging` is enabled on both tiers.

The generator emits about 15% error traces and about 18% slow traces among the remainder.
Healthy fast traces are dropped by tail sampling.

## Try it out

The generator emits one `checkout` trace per second with exactly four spans: `checkout`, `auth`, `inventory`, and `payment`.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Prometheus** data source and run these PromQL queries:

   - `sum by (instance) (rate(otelcol_receiver_accepted_spans_total{job="alloy-downstream"}[2m]))`: Span intake split across downstream instances
   - `sum(rate(otelcol_receiver_accepted_spans_total{job="alloy-downstream"}[2m]))`: Total spans entering the downstream tier
   - `sum(rate(otelcol_exporter_sent_spans_total{job="alloy-downstream"}[2m]))`: Spans tail sampling forwarded to Tempo

   Both downstream instances should receive a steady share of spans.
   The gap between received and sent span rates is the healthy fast traffic tail sampling dropped.

2. Select the **Tempo** data source in **Explore** and open the **Search** tab.

   - `{resource.service.name="trace-generator"}`: Traces from the generator
   - `{status=error}`: Error traces kept by the status-code policy

   Open any sampled trace and check that it contains all four spans.
   Because each span travels in its own OTLP request and the sampling policies are deterministic, a complete trace in Tempo means the load balancer routed all of its spans to the same downstream instance.

3. To inspect the pipelines, open the Alloy UIs at http://localhost:12345, http://localhost:12346, and http://localhost:12347.
   Select components such as `otelcol.exporter.loadbalancing.default` or `otelcol.processor.tail_sampling.default` to use live debug.

## Customize the scenario

- **Add a third downstream**: Add another compose service and append its hostname to `resolver.static.hostnames` in `config-lb.alloy`. The consistent hash redistributes automatically.
- **Use Kubernetes service discovery**: Replace the `static` resolver with the `dns` or `k8s` resolver so the downstream set tracks a headless Service or pod selector.
- **Route by service name**: Set `routing_key = "service"` to group spans by service name instead of trace ID. That pattern is useful in front of `otelcol.connector.spanmetrics` rather than tail sampling.
- **Adjust sampling policies**: Edit `otelcol.processor.tail_sampling.default` in `config-downstream.alloy`.

## Troubleshoot common problems

Diagnose container startup failures, uneven downstream load, incomplete traces, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `trace-generator`, `alloy-lb`, or `alloy-downstream-1`.
For Alloy specifically, the most common cause is a syntax error in `config-lb.alloy` or `config-downstream.alloy`.

### Downstream span rates look uneven or zero

Open the Alloy UI at http://localhost:12345 and check that `otelcol.exporter.loadbalancing.default` is healthy.
Check that `trace-generator` is running and sending to `alloy-lb:4317`.
In Grafana, run `sum by (instance) (rate(otelcol_receiver_accepted_spans_total{job="alloy-downstream"}[2m]))` on the **Prometheus** data source.

### Sampled traces in Tempo are missing spans

This usually means spans from one trace reached different downstream instances.
Check that `routing_key = "traceID"` is set in `config-lb.alloy` and that both downstream hostnames in the static resolver are reachable.
Open a trace in Tempo and check whether it has fewer than four spans.

### Port conflicts with other services

Ports 3000, 3200, 9090, 12345, 12346, 12347, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-loadbalancing` directory.

## Next steps

- `otelcol.exporter.loadbalancing` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.loadbalancing/
- `otelcol.processor.tail_sampling` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.tail_sampling/
- OpenTelemetry tail sampling scenario: https://github.com/grafana/alloy-scenarios/tree/main/otel-tail-sampling
- More examples: https://github.com/grafana/alloy-scenarios
