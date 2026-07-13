# Derive metrics from application logs with Alloy

This scenario uses `loki.process` and its `stage.metrics` block to turn HTTP request log lines into Prometheus metrics while it continues to send the original logs to Loki.
A bundled Python generator writes request logs, so the complete example runs without an external application.
Grafana starts with a dashboard that shows the source logs, request rate, and p95 request latency together.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000, 3100, 9090, and 12345 free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
                         +-------------------> Loki --------+
                         |                    (raw logs)     |
log-generator --> Alloy -+                                   +--> Grafana
   (file)       (regex + |                    (metrics)      |
                metrics) +--> self-scrape --> Prometheus ---+
```

- **log-generator** writes synthetic request lines to a shared file every 500 milliseconds.
- **Alloy** tails the file, extracts `method`, `status`, and `duration`, and updates a counter and histogram.
- **Loki** stores the original request logs with low-cardinality `method` and `status` labels.
- **Prometheus** receives only metrics whose names begin with `log_derived_` through remote write.
- **Grafana** provisions both data sources and a dashboard automatically.

`stage.metrics` exposes generated metrics on Alloy's `/metrics` endpoint.
The `prometheus.scrape` component scrapes that endpoint, a relabel rule keeps only this scenario's derived metrics, and `prometheus.remote_write` sends them to Prometheus.

## Run the scenario

Choose one of these options:

**From the scenario directory**, using image defaults in `docker-compose.yml`:

```bash
cd log-to-metrics
docker compose up -d
```

**From the repository root**, using the versions in `image-versions.env`:

```bash
./run-example.sh log-to-metrics
```

Confirm that all five containers are running:

```bash
docker compose ps
```

## Explore the results

Open Grafana at http://localhost:3000, with no login required, and select the **Metrics derived from logs** dashboard.
Allow about 30 seconds for the first rate and histogram queries to populate.

You can also inspect each signal directly:

- In the Prometheus UI at http://localhost:9090, query `log_derived_requests_total` or `log_derived_request_duration_seconds_bucket`.
- In Grafana Explore, select Loki and query `{job="log-to-metrics"}`.
- In the Alloy UI at http://localhost:12345, inspect `loki.process.requests` and `prometheus.scrape.derived_metrics`.
- Run `docker compose logs -f log-generator` to watch the source request lines.

Each generated line has this form:

```text
2026-01-01T12:00:00+00:00 method=GET path=/api/products status=200 duration=0.083s
```

The regular expression stage extracts fields from that line.
The metrics stage then creates:

- `log_derived_requests_total`, incremented once for every parsed request log.
- `log_derived_request_duration_seconds`, a histogram populated from the `duration` field.

## Adapt the pipeline

Edit `stage.regex` in `config.alloy` to match your application's log format.
Keep metric labels bounded: values such as HTTP method and status code are safe examples, while request paths, user IDs, and trace IDs can create unbounded cardinality.
Change the histogram buckets to match the latency range of your service.

The generated metrics reset when Alloy reloads its configuration and disappear after five minutes without matching logs because `max_idle_duration` is set to `5m`.

## Troubleshoot common problems

### The dashboard has logs but no metrics

Open http://localhost:12345/metrics and search for `log_derived_`.
If the metrics exist there, inspect `prometheus.scrape.derived_metrics` and `prometheus.remote_write.local` in the Alloy UI.
Verify that Prometheus was started with `--web.enable-remote-write-receiver`.

### No logs appear

Run `docker compose logs log-generator` and verify that it emits request lines.
Then inspect `loki.source.file.requests` in the Alloy UI and confirm that `./logs/requests.log` exists in the scenario directory.

### A container exits at startup

Run `docker compose logs <service>` for the failing service.
For Alloy, configuration errors include the component and line number that failed validation.

## Stop the scenario

Run `docker compose down` from the `log-to-metrics` directory.
Add `--volumes` if you also want to remove Docker-managed data.

## Next steps

- [`loki.process` reference](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/)
- [`prometheus.scrape` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/)
- [Logs from file scenario](../logs-file/)
- [OpenTelemetry span metrics scenario](../otel-span-metrics/)
