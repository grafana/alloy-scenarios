# Trace correlation with exemplars

This scenario shows how to link latency histogram metrics to individual Tempo traces using [OpenMetrics exemplars](https://grafana.com/docs/grafana/latest/fundamentals/exemplars/) and Grafana Alloy.
A checkout service emits OTLP traces and histogram observations with trace ID exemplars on each request.
Grafana Alloy scrapes those metrics, forwards exemplars to Prometheus, and Grafana links exemplar dots on latency panels back to the matching trace in Tempo.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the checkout service, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Every link in the exemplar chain must be configured correctly.

```text
+--------------------+   OTLP traces   +------------+   OTLP   +------------+
| checkout service   |---------------->|    Alloy   |--------->|   Tempo    |
| /metrics           |                 |            |          |            |
| (OpenMetrics with  |                 |            |          |            |
|  trace_id ex.)     |                 |            |          |            |
+--------+-----------+                 +------+-----+          +-------+----+
         ^                                    |                        ^
         | scrape                             | remote_write           | click-through
         +------------------------------------+                        |
                                              | (send_exemplars)       |
                                              v                        |
                                        +------------+  query    +----------------------+
                                        | Prometheus |---------->| Grafana panel with   |
                                        | exemplar   |           | exemplar dots        |
                                        | storage    |           +----------------------+
                                        +------------+
```

The table below uses the same labels as the diagram and maps each hop to the file that sets it.

| Diagram label      | Path                         | Where                                  | Setting                                                                                                                |
| ------------------ | ---------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `/metrics`         | Inside checkout service      | `app/app.py`                           | `CHECKOUT_LATENCY.observe(..., {"trace_id": ...})` via OpenMetrics exposition. Classic Prometheus text drops exemplars |
| OTLP traces        | checkout service to Alloy    | `config.alloy`                         | `otelcol.receiver.otlp` receives traces from the checkout service                                                      |
| OTLP               | Alloy to Tempo               | `config.alloy`                         | `otelcol.exporter.otlp` sends traces to `tempo:4317`                                                                   |
| scrape             | Alloy to checkout `/metrics` | `config.alloy`                         | `prometheus.scrape` with `scrape_protocols = ["OpenMetricsText1.0.0", ...]`                                            |
| `remote_write`     | Alloy to Prometheus          | `config.alloy`                         | `prometheus.remote_write` with `send_exemplars = true`                                                                 |
| `exemplar-storage` | Inside Prometheus            | `docker-compose.yml`                   | `--enable-feature=exemplar-storage`                                                                                    |
| query              | Prometheus to Grafana        | `grafana/datasources/datasources.yaml` | Prometheus data source with exemplars enabled on the dashboard panel                                                   |
| click-through      | Grafana to Tempo             | `grafana/datasources/datasources.yaml` | `exemplarTraceIdDestinations: [{name: trace_id, datasourceUid: tempo}]`                                                |

- **checkout service**: Flask app on port 8080 with OpenTelemetry service name `checkout-service`.
  Each `/checkout` request produces an OTLP trace and a histogram observation whose exemplar carries that trace ID.
  A built-in load thread requests `/checkout` every 2 seconds.
  The Compose service name is `demo-app`.
- **Alloy**: Runs `config.alloy` with separate trace and metric pipelines.
  Live debugging is enabled.
- **Tempo**: Stores traces at `tempo:4317`.
- **Prometheus**: Stores metrics and exemplars through its remote write receiver with exemplar storage enabled.
- **Grafana**: Provisions Prometheus and Tempo data sources plus the **Checkout Latency with Exemplars** dashboard.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/trace-log-correlation-exemplars`
   - Deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh trace-log-correlation-exemplars`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d --build`

3. From the `trace-log-correlation-exemplars` directory, check that all containers are up: `docker compose ps`

   Expect `alloy`, `tempo`, `prometheus`, `grafana`, and `demo-app`.

## Explore the services

- **Grafana** at http://localhost:3000: Open **Dashboards** and select **Checkout Latency with Exemplars**.
  You don't need to log in.
- **Alloy UI** at http://localhost:12345: Component graph for the trace and metric pipelines.
  Live debugging is enabled in `config.alloy`.
- **Prometheus** at http://localhost:9090: `checkout_duration_seconds` metrics with exemplars from remote write.
- **Tempo** at http://localhost:3200: Traces from `checkout-service` linked from exemplar dots.
- **Checkout service** at http://localhost:8080/checkout: The `/checkout` endpoint that generates traces and exemplars.

## Understand the Alloy pipeline

`config.alloy` defines two pipelines.

### Traces

1. **`otelcol.receiver.otlp`**: Receives OTLP over HTTP and gRPC from the checkout service.
2. **`otelcol.processor.batch`**: Batches spans for export.
3. **`otelcol.exporter.otlp`**: Sends traces to Tempo at `tempo:4317`.

### Metrics with exemplars

1. **`prometheus.scrape`**: Scrapes `demo-app:8080` every 10 seconds with OpenMetrics negotiation first.
2. **`prometheus.remote_write`**: Sends metrics and exemplars to `http://prometheus:9090/api/v1/write` with `send_exemplars = true`.

## Try it out

The checkout service requests its own `/checkout` endpoint every 2 seconds.
About 10% of requests are deliberately slow.

### View exemplars in Grafana

Click a dot on the latency histogram to open the exact trace that produced it.

1. Open Grafana at http://localhost:3000 and go to **Dashboards**.
2. Select **Checkout Latency with Exemplars**.
3. After about a minute you should see p95 and p50 latency lines with exemplar dots scattered around them.
   Exemplars are pre-enabled on the panel.
4. Hover a dot, especially a high one, and click **Query with Tempo**.
   Grafana opens the exact trace whose `checkout.delay_ms` attribute explains the latency you clicked on.

### Verify the chain from the command line

You can confirm the exemplar chain without Grafana by querying Prometheus for a trace ID, then fetching that trace from Tempo.

1. Get the trace ID from the most recent exemplar on `checkout_duration_seconds_bucket`:

   ```bash
   curl -sG http://localhost:9090/api/v1/query_exemplars \
     --data-urlencode 'query=checkout_duration_seconds_bucket' \
     --data-urlencode "start=$(date -d '-10 min' +%s)" \
     --data-urlencode "end=$(date +%s)" | jq -r '.data[0].exemplars[-1].labels.trace_id'
   ```

2. Fetch the trace from Tempo. Replace `<trace_id>` with the value from step 1:

   ```bash
   curl -s http://localhost:3200/api/traces/<trace_id> | jq '.batches[0].scopeSpans[0].spans[0].name'
   ```

A successful response shows the span name for the checkout request that produced the exemplar.

## Customize the scenario

- **Rename the exemplar label**: Edit the label in `app/app.py` and change `exemplarTraceIdDestinations[0].name` in `grafana/datasources/datasources.yaml` to match.
- **Query exemplars through the API**: Exemplars attach to histogram bucket samples.
  Query `checkout_duration_seconds_bucket`, not `_sum`, when you use the Prometheus exemplars API.
- **Add routes**: Any histogram observed inside an active span can carry that span's trace ID.

## Troubleshoot common problems

This section covers startup failures, missing exemplars, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `alloy`, `prometheus`, or `demo-app`.
The checkout service container requires `docker compose up -d --build` on first run.

### No exemplar dots in Grafana

Confirm Prometheus started with `--enable-feature=exemplar-storage`.
Check that Alloy scrapes OpenMetrics from `demo-app:8080` and that `send_exemplars = true` is set in `prometheus.remote_write` in `config.alloy`.
Run the Prometheus exemplars API query in **Try it out** to confirm exemplars are stored.

### Port conflicts with other services

Ports 8080, 3000, 3200, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `trace-log-correlation-exemplars` directory.

## Next steps

- Grafana exemplars documentation: https://grafana.com/docs/grafana/latest/fundamentals/exemplars/
- Alloy `prometheus.remote_write` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/
- More examples: https://github.com/grafana/alloy-scenarios
