# Collect StatsD metrics with Grafana Alloy

This scenario shows how to bring metrics from a legacy StatsD application into Prometheus without changing the application.
The bundled sender emits a counter, gauge, and timer to Alloy over UDP.
Alloy's `prometheus.exporter.statsd` component maps those packets to Prometheus metrics, `prometheus.scrape` collects them, and `prometheus.remote_write` stores them in Prometheus.

## Before you begin

Ensure that [Docker][docker] and [Docker Compose][docker-compose] are installed, and that ports 3000, 8125/UDP, 9090, and 12345 are available.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+---------------+  StatsD/UDP   +--------------------------------+  remote write  +------------+     +---------+
| legacy sender |-------------->| Alloy                          |--------------->| Prometheus |<----| Grafana |
+---------------+               | StatsD exporter -> scrape     |                +------------+     +---------+
                                +--------------------------------+
```

- **Sender** emits representative StatsD counter, gauge, and timer packets.
- **Alloy** receives UDP packets on port 8125 and applies the mappings in `statsd-mapping.yaml`.
- **Prometheus** receives the scraped samples through its remote-write receiver.
- **Grafana** includes a provisioned Prometheus data source for queries.

## Run the scenario

From the repository root, start the scenario with one of these options:

```sh
cd statsd-metrics
docker compose up -d
```

Or use the repository's pinned image versions:

```sh
./run-example.sh statsd-metrics
cd statsd-metrics
```

Verify that all four services are running:

```sh
docker compose ps
```

## Explore the metrics

Open Grafana at http://localhost:3000 or Prometheus at http://localhost:9090, then run these PromQL queries:

- `legacy_checkout_requests_total` — monotonically increasing request counter.
- `legacy_checkout_queue_depth` — current queue depth gauge.
- `legacy_checkout_request_duration_seconds_bucket` — histogram buckets produced from the StatsD timer.
- `histogram_quantile(0.95, sum by (le) (rate(legacy_checkout_request_duration_seconds_bucket[5m])))` — 95th-percentile checkout latency.

The Alloy UI is available at http://localhost:12345. Use live debugging to inspect `prometheus.exporter.statsd.legacy_app` and `prometheus.scrape.statsd`.

## Understand the mapping

`statsd-mapping.yaml` converts dot-separated StatsD names into stable Prometheus names:

| StatsD packet | Prometheus metric |
| --- | --- |
| `legacy.checkout.requests:1|c` | `legacy_checkout_requests_total` |
| `legacy.checkout.queue_depth:42|g` | `legacy_checkout_queue_depth` |
| `legacy.checkout.request_duration:125|ms` | `legacy_checkout_request_duration_seconds` histogram |

StatsD timers are converted from milliseconds to seconds. The explicit histogram buckets make latency percentile queries possible.

## Send metrics from another application

The UDP port is exposed on the host, so an application outside Compose can send StatsD packets to `localhost:8125`.
Update `statsd-mapping.yaml` before sending new metric names, then restart Alloy:

```sh
docker compose restart alloy
```

## Troubleshoot

If the metrics do not appear, check the sender and Alloy logs:

```sh
docker compose logs sender alloy
```

Confirm that Alloy is listening on UDP port 8125 and that the metric name matches a mapping rule exactly.
If a custom sender runs on the host, use `localhost:8125`; services in the Compose network should send to `alloy:8125`.

## Stop the scenario

Run this from the scenario directory:

```sh
docker compose down
```

## Next steps

- [`prometheus.exporter.statsd` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.statsd/)
- [`prometheus.scrape` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/)
- [`prometheus.remote_write` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/)
