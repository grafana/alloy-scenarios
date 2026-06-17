# OpenTelemetry tail sampling

This scenario shows how to filter OpenTelemetry traces with Grafana Alloy's `otelcol.processor.tail_sampling` component.
A Python Flask demo app generates traces in the background and on demand, Alloy applies tail-sampling policies, and sampled traces are stored in Tempo for exploration in Grafana.

Tail sampling decides whether to keep a trace only after Alloy has seen its spans.
That lets you keep errors, slow requests, and traces with specific attributes while dropping most routine traffic.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +-------+       +-------+       +---------+
| demo-app         | OTLP  | Alloy | OTLP  |       |       |         |
| Flask + OTel SDK |------>| tail  |------>| Tempo |------>| Grafana |
|                  |       | sample|       |       |       |         |
+------------------+       +-------+       +---+---+       +---------+
                                               | service graph
                                               v and span metrics
                                          +------------+
                                          | Prometheus |
                                          +------------+
```

- **demo-app**: Flask app on port 8080 that generates traces in a background thread and through HTTP endpoints.
- **Alloy**: Receives OTLP traces, applies tail-sampling policies, batches sampled spans, and exports them to Tempo.
- **Tempo**: Stores sampled traces and generates service-graph and span metrics that it remote-writes to Prometheus.
- **Prometheus**: Stores metrics from Tempo's metrics generator.
- **Grafana**: Explores traces through Tempo and service graphs through Prometheus.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/otel-tail-sampling`
   - Build and deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Tempo, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh otel-tail-sampling`

3. From the `otel-tail-sampling` directory, check that all containers are up: `docker compose ps`

   You should see `demo-app`, `alloy`, `tempo`, `prometheus`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: Home page with links to trace-generating endpoints. The app also generates traces automatically in the background.
- **Grafana** at http://localhost:3000: **Explore** and **Traces Drilldown**, with no login required. Open **Traces Drilldown** at http://localhost:3000/a/grafana-exploretraces-app.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Tempo** at http://localhost:3200: Trace storage backend.
- **Prometheus** at http://localhost:9090: Service-graph and span metrics from Tempo.

## Understand the Alloy pipeline

The `config.alloy` pipeline has four components in this order:

1. **`otelcol.receiver.otlp.default`**: Receives OTLP traces over gRPC and HTTP.
2. **`otelcol.processor.tail_sampling.default`**: Buffers spans per trace and applies sampling policies after `decision_wait = "10s"`.
3. **`otelcol.processor.batch.default`**: Batches sampled spans before export.
4. **`otelcol.exporter.otlp.tempo`**: Sends kept traces to Tempo at `tempo:4317`.

Tail sampling runs before batching so spans reach the sampler as early as possible.
If batching ran first, spans from the same trace could arrive too late for a correct decision.

`livedebugging` is enabled so you can inspect sampling decisions in the Alloy UI.

### Tail-sampling policies

`otelcol.processor.tail_sampling.default` in `config.alloy` defines six policies:

1. **test-attribute-policy**: Keeps traces with `test_attr_key_1 = test_attr_val_1`.
2. **error-policy**: Keeps traces that contain a span with `ERROR` status.
3. **latency-policy**: Keeps traces with end-to-end latency above 5000 ms.
4. **numeric-policy**: Keeps traces where numeric attribute `key1` is between 70 and 100.
5. **url-filter-policy**: Drops traces whose `http.url` is `/health` or `/metrics`. All other URLs pass through to later policies.
6. **probabilistic-policy**: Keeps 10% of remaining traces as a baseline sample.

The processor also sets `num_traces = 100` and `expected_new_traces_per_sec = 10` to size its in-memory trace buffer.

### Trace types the demo app generates

The background generator and HTTP endpoints produce:

- Simple single-span traces
- Nested parent-child traces
- Error traces
- High-latency traces with 3 to 10 second delays
- Delayed-chain traces where service D adds 3 to 4 seconds of latency
- Multi-service traces with distinct `service.name` values such as `web-ui` and `api-gateway`

Manual endpoints include `/simple`, `/nested`, `/error`, `/high-latency`, `/chain`, `/delayed-chain`, `/multi-service`, and `/batch`.

## Try it out

1. Open the demo app at http://localhost:8080 and wait for background trace generation to start, or call an endpoint such as `/error` or `/high-latency`.

2. Open Grafana at http://localhost:3000, go to **Explore**, select the **Tempo** data source, and open the **Search** tab.
   Run these TraceQL queries:

   - `{resource.service.name="trace-demo-tail-sampled"}`: Traces from the demo app
   - `{status=error}`: Traces that include an error status
   - `{duration>5s}`: Traces longer than five seconds
   - `{span.test_attr_key_1="test_attr_val_1"}`: Traces matched by the attribute policy
   - `{span.service.latency="high" && span.latency.category="bottleneck"}`: Traces with a high-latency service D bottleneck

3. To view the service graph, select the **Tempo** data source in **Explore** and open the **Service Graph** tab after several minutes of background traffic.

4. To inspect sampling in real time, open the Alloy UI at http://localhost:12345 and select `otelcol.processor.tail_sampling.default` to use live debug.

## Customize the scenario

- **Adjust policies**: Edit policy blocks in `otelcol.processor.tail_sampling.default` in `config.alloy`.
- **Change decision timing**: Edit `decision_wait`, `num_traces`, or `expected_new_traces_per_sec` in `config.alloy` to balance memory use against complete trace visibility.
- **Use the OTel Engine**: Run `docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d --build` to load the equivalent pipeline from `config-otel.yaml` instead of River syntax.

## Troubleshoot common problems

Diagnose container startup failures, missing traces, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `tempo`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No traces appear in Grafana after a few minutes

Open the demo app at http://localhost:8080 and call `/error` or `/high-latency` to generate a trace that tail sampling should keep.
Tail sampling waits up to 10 seconds before deciding, so allow a short delay before searching.
Open the Alloy UI at http://localhost:12345 and check that `otelcol.processor.tail_sampling.default` shows a healthy status.
In Grafana, select the **Tempo** data source in **Explore** and search for `{resource.service.name="trace-demo-tail-sampled"}`.

### Most traces seem to be missing

That is expected. Tail sampling drops most routine traffic and keeps errors, slow traces, attribute matches, and about 10% of the remainder.
Compare kept trace counts with the sampling policies in `config.alloy`.

### Port conflicts with other services

Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, 12345 for Alloy, and 4317 and 4318 for OTLP must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-tail-sampling` directory.

## Next steps

- `otelcol.processor.tail_sampling` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.tail_sampling/
- OpenTelemetry load balancing scenario: https://github.com/grafana/alloy-scenarios/tree/main/otel-loadbalancing
- Live debugging in Alloy: https://grafana.com/docs/alloy/latest/troubleshoot/debug/
- More examples: https://github.com/grafana/alloy-scenarios
