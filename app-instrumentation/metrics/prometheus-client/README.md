# Prometheus client metrics across languages

This scenario shows how to expose metrics with native Prometheus client libraries in five languages and collect them by scraping with Grafana Alloy.
Each service plays a role in a fictional online store, written in a different language, and serves a `/metrics` endpoint.
Alloy scrapes all five endpoints and remote-writes the samples to Prometheus, where you explore them with **Metrics Drilldown**.
The `config.alloy` file defines the pipeline.

Each service runs on its own and updates its metrics in a loop about once a second.
No service calls another.
This scenario is the pull half of a pair.
Its sibling, the OpenTelemetry SDK scenario, instruments the same store with the OpenTelemetry SDK, which pushes metrics over OTLP.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

This scenario and its sibling collect the same store metrics with opposite collection models.

| Scenario | Instrumentation | Collection model |
| -------- | --------------- | ---------------- |
| Prometheus client metrics | Native Prometheus client libraries | Services expose `/metrics`; Alloy scrapes |
| [OpenTelemetry SDK metrics](../opentelemetry-sdk/) | OpenTelemetry metrics SDK | Services push over OTLP; Alloy receives |

## Understand the architecture

```text
+-------------------+         +-------+       +------------+       +---------+
| 5 store services  |<--------|       |       |            |       |         |
| Prometheus client | scrape  | Alloy |------>| Prometheus |------>| Grafana |
| /metrics on :9100 |         |       | write |            |       |         |
+-------------------+         +-------+       +------------+       +---------+
```

- **Store services**: Five containers named `python`, `node`, `go`, `java`, and `csharp`. Each instruments a store domain with its language's Prometheus client library and serves `/metrics` on port 9100.
- **Alloy**: Scrapes all five endpoints every five seconds and remote-writes the samples to Prometheus.
- **Prometheus**: Stores the samples through its remote-write endpoint.
- **Grafana**: Explores the metrics with **Metrics Drilldown**.

Alloy lists the five targets statically and attaches a `service_name` and a `language` label to each one.

| Language | Store role | Service name | Scrape target |
| -------- | ---------- | ------------ | ------------- |
| Python | Checkout and payments | `checkout` | `python:9100` |
| Node.js | Product catalog | `catalog` | `node:9100` |
| Go | Inventory | `inventory` | `go:9100` |
| Java | Orders | `orders` | `java:9100` |
| C# | Shipping | `shipping` | `csharp:9100` |

Every service exposes a counter, a histogram, and two gauges, named for its domain with idiomatic Prometheus names.
The checkout service, for example, exposes `checkout_transactions_total`, `checkout_payment_duration_seconds`, `checkout_active_carts`, and `checkout_queue_depth`.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/app-instrumentation/metrics/prometheus-client`

3. Build and deploy the scenario: `docker compose up --build -d`

   To use the pinned image versions from `image-versions.env`, run `docker compose --env-file ../../../image-versions.env up --build -d` instead.

4. Confirm all containers are up: `docker compose ps`
   The first build takes a few minutes because the Java and C# images compile from source.

## Explore the services

- **Grafana** at http://localhost:3000: **Metrics Drilldown** and **Explore**, with no login required. Open **Metrics Drilldown** at http://localhost:3000/a/grafana-metricsdrilldown-app.
- **Prometheus** at http://localhost:9090: Metrics storage backend and query UI.
- **Alloy UI** at http://localhost:12345: Pipeline graph, scrape target health, and live debug views.

## Understand the configuration

The `config.alloy` pipeline has two components: `prometheus.scrape` and `prometheus.remote_write`.

1. **`prometheus.scrape`**: Lists the five services as static targets, one per container, and scrapes each `/metrics` endpoint every five seconds. The `service_name` and `language` entries on each target become labels on every scraped series. The component forwards the samples to `prometheus.remote_write`.
2. **`prometheus.remote_write`**: Pushes the samples to Prometheus at `http://prometheus:9090/api/v1/write`.

Prometheus runs with the `--web.enable-remote-write-receiver` flag so it accepts the write.
Each service binds `/metrics` to `0.0.0.0:9100`, so Alloy can reach it by the container name on the Compose network.

## Try it out

1. Open **Metrics Drilldown** at http://localhost:3000/a/grafana-metricsdrilldown-app.

2. Filter by the `service_name` label to focus on a single service, for example `checkout` or `inventory`.

3. Open Prometheus at http://localhost:9090 and check that every target is healthy:

   ```promql
   up
   ```

   Each of the five targets returns `1`.

4. Run a request-rate query:

   ```promql
   sum by (service_name) (rate(checkout_transactions_total[1m]))
   ```

5. To inspect the scrape in real time, open the Alloy UI at http://localhost:12345 and select `prometheus.scrape.store_apps` to view target health and use live debug.

## Customize the scenario

- **Add a language**: Serve `/metrics` on port 9100, add the service to `docker-compose.yml`, and add one target to the `targets` list in `prometheus.scrape` in `config.alloy`.
- **Discover targets dynamically**: Replace the static `targets` list with `discovery.docker` and `discovery.relabel` to pick up containers automatically. The [Popular logging frameworks](../../logging/popular-logging-frameworks/) scenario uses that pattern.
- **Drop or rename series**: Add a `prometheus.relabel` block between `prometheus.scrape` and `prometheus.remote_write` to filter or relabel the scraped samples.

## Troubleshoot common problems

Diagnose container startup failures, unhealthy scrape targets, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If a container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace _SERVICE_NAME_ with the service that exited, for example `java` or `alloy`.
For Alloy, the most common cause is a syntax error in `config.alloy`.

### A scrape target shows as down

Open the Alloy UI at http://localhost:12345 and select `prometheus.scrape.store_apps` to check which target is down.
A target is down when its service failed to start or doesn't serve `/metrics` on port 9100.
Run `docker compose logs <SERVICE_NAME>` for the matching service to read the failure reason.

### Port conflicts with other services

Ports 3000, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up --build -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.
Run `docker compose down -v` to remove stored data as well.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `prometheus.scrape` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/
- OpenTelemetry SDK metrics scenario: [../opentelemetry-sdk/](../opentelemetry-sdk/)
- Prometheus client libraries: https://prometheus.io/docs/instrumenting/clientlibs/
