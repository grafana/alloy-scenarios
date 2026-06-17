# NGINX monitoring

This scenario shows end-to-end NGINX observability with a single Alloy pipeline.

Alloy tails NGINX access and error logs with `loki.source.file`, parses the combined log format with `loki.process`, and ships log lines to Loki with `method` and `status` as labels.
Alloy also scrapes `nginx-prometheus-exporter`, which reads NGINX's built-in `stub_status` endpoint, and remote-writes metrics to Prometheus.
Grafana includes provisioned Loki and Prometheus data sources.

A `loadgen` container hits NGINX once per second so logs and metrics have visible activity.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for NGINX, 9113 for the NGINX exporter, 3000 for Grafana, 3100 for Loki, 9090 for Prometheus, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+---------------+     +-------+     +-------------+     +---------+
| NGINX logs    |     |       |---->| Loki        |---->|         |
| shared volume |---->| Alloy |     +-------------+     | Grafana |
+---------------+     |       |---->| Prometheus  |---->|         |
+---------------+     |       |     +-------------+     +---------+
| nginx-exporter|---->| scrape|
+---------------+     +-------+
```

- **nginx**: Web server on port 8080 with `stub_status` at `/nginx_status` and combined-format access and error logs written to a shared volume.
- **nginx-exporter**: Reads `http://nginx:80/nginx_status` and exposes Prometheus metrics on port 9113.
- **loadgen**: Calls `/` and `/missing-page` in a loop so you get steady 200 and 404 responses.
- **Alloy**: Tails logs from the shared volume, processes access lines, scrapes the exporter every 15 seconds, and forwards logs and metrics to Loki and Prometheus.
- **Loki**: Stores logs at `http://loki:3100`.
- **Prometheus**: Stores metrics at `http://prometheus:9090` with the remote write receiver enabled.
- **Grafana**: Queries logs and metrics through provisioned Loki and Prometheus data sources.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/nginx-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh nginx-monitoring`

3. From the `nginx-monitoring` directory, check that all containers are up: `docker compose ps`

   You should see `nginx`, `nginx-exporter`, `loadgen`, `alloy`, `loki`, `prometheus`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs and metrics in **Explore** with the Loki and Prometheus data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **Loki** at http://localhost:3100: Log backend API.
- **NGINX** at http://localhost:8080: `/` returns `ok`, and `/nginx_status` returns connection counters.

## Understand the Alloy pipeline

The `config.alloy` file defines two pipelines.

### Logs

1. **`local.file_match.nginx`**: Watches `/var/log/nginx-data/access.log` and `/var/log/nginx-data/error.log` with `job="nginx"` and `log_type` labels.
2. **`loki.source.file.nginx`**: Tails matched files with `tail_from_end = true` and forwards lines to `loki.process.nginx`.
3. **`loki.process.nginx`**: Parses access logs with a combined-format regex and promotes `method` and `status` to Loki labels. Error logs pass through unchanged.
4. **`loki.write.local`**: Sends log streams to Loki at `http://loki:3100/loki/api/v1/push`.

The combined-log regex extracts `remote_addr`, `time_local`, `method`, `path`, `status`, and `bytes_sent`.
Only `method` and `status` become labels for fast filtering; the rest stay in the log line text.

### Metrics

1. **`prometheus.scrape.nginx`**: Scrapes `nginx-exporter:9113` every 15 seconds.
2. **`prometheus.remote_write.local`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

NGINX writes logs to `/var/log/nginx-data` instead of the image default under `/var/log/nginx` so Alloy can tail the files from a shared Docker volume across containers.

## Try it out

The `loadgen` container hits NGINX once per second, alternating a 200 response on `/` and a 404 on `/missing-page`.
Within about 30 seconds you should see data in Grafana.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki** data source and run these LogQL queries:

   - `{job="nginx", log_type="access"}`: All access logs
   - `{job="nginx", log_type="access", status=~"4.."}`: Access logs with 4xx status codes
   - `{job="nginx", log_type="error"}`: Error log lines

   Select the **Prometheus** data source and run these PromQL queries:

   - `nginx_connections_active`: Active connections
   - `rate(nginx_connections_accepted[1m])`: Accepted connections per second
   - `nginx_http_requests_total`: Total HTTP requests since exporter start

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select log or metrics components from the graph, such as `loki.source.file.nginx`, `loki.process.nginx`, `prometheus.scrape.nginx`, or `prometheus.remote_write.local`, to use live debug.

## Customize the scenario

- **Different log format**: Edit the regex in `loki.process.nginx` in `config.alloy`. The default expects NGINX's built-in `combined` format.
- **Different exporter target**: Change the `--nginx.scrape-uri` flag on `nginx-exporter` in `docker-compose.yml`.
- **More log sources**: Add entries to `local.file_match.nginx.path_targets` in `config.alloy`.
- **Adjust scrape frequency**: Edit `scrape_interval` in `prometheus.scrape.nginx` in `config.alloy`.

## Troubleshoot common problems

Diagnose container startup failures, missing logs or metrics in Grafana, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `nginx`, `alloy`, `loki`, or `prometheus`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No logs appear in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that `loki.source.file.nginx` and `loki.process.nginx` show a healthy status.
Check that `loadgen` is running and that `nginx` is writing to the shared `nginx-logs` volume.
Because `tail_from_end = true`, Alloy only reads new lines written after it starts.
If you restarted Alloy without generating new traffic, run `docker compose logs loadgen` to check that requests are still flowing.

In Grafana, select the **Loki** data source in **Explore** and run `{job="nginx", log_type="access"}`.

### No metrics appear in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that `prometheus.scrape.nginx` shows a healthy status.
Verify that `nginx-exporter` can reach `http://nginx:80/nginx_status`.
In Grafana, select the **Prometheus** data source in **Explore** and run `nginx_connections_active`.

### Port conflicts with other services

Ports 8080 for NGINX, 9113 for the exporter, 3000 for Grafana, 3100 for Loki, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down -v` from the `nginx-monitoring` directory.

The `-v` flag removes the shared `nginx-logs` volume so the next run starts with a clean log file.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `loki.source.file` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/
- `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- NGINX Prometheus exporter: https://github.com/nginxinc/nginx-prometheus-exporter
- More examples: https://github.com/grafana/alloy-scenarios
