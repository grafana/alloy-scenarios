# NGINX Monitoring with Grafana Alloy

End-to-end NGINX observability with a single Alloy pipeline:

- **Logs** — `loki.source.file` tails NGINX access and error logs; `loki.process` parses the combined log format and promotes `method` and `status` to labels.
- **Metrics** — `prometheus.scrape` scrapes `nginx-prometheus-exporter` (which itself reads NGINX's built-in `stub_status`) and remote-writes to Prometheus.

## Architecture

- **NGINX** — the monitored web server (`/nginx_status` enabled, access/error logs written to a shared volume)
- **nginx-prometheus-exporter** — translates `stub_status` into Prometheus metrics on `:9113`
- **loadgen** — small `curl` loop that hits NGINX once per second so the demo has visible activity (200s and 404s)
- **Grafana Alloy** — the pipeline above, exposed at `:12345`
- **Loki / Prometheus / Grafana** — backends and visualization, with Loki and Prometheus datasources auto-provisioned

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root using centralized image versions
./run-example.sh nginx-monitoring
```

## Accessing

- **Grafana**: http://localhost:3000 (no login required)
- **Alloy UI**: http://localhost:12345 — verify components are healthy and inspect the live data flow
- **Prometheus**: http://localhost:9090
- **NGINX**: http://localhost:8080 — `/` returns "ok", `/nginx_status` returns connection counters

## Trying it out

The `loadgen` container hits NGINX once per second (alternating a 200 response and a 404). Within ~30 seconds you should see:

### Logs (Loki)

```logql
# All access logs
{job="nginx", log_type="access"}

# Just 4xx
{job="nginx", log_type="access", status=~"4.."}

# Error log
{job="nginx", log_type="error"}
```

The combined-log regex extracts `remote_addr`, `time_local`, `method`, `path`, `status`, and `bytes_sent`. Of those, `method` and `status` are promoted to Loki labels for fast filtering; the rest stay in the line text.

### Metrics (Prometheus)

```promql
# Active connections
nginx_connections_active

# Accepted-since-start counter (per second)
rate(nginx_connections_accepted[1m])

# Total HTTP requests
nginx_http_requests_total
```

## Customization

- **Different log format**: edit the regex in `config.alloy` under `loki.process.nginx`. The default expects NGINX's built-in `combined` format.
- **Different exporter target**: change the `--nginx.scrape-uri` flag on `nginx-exporter` in `docker-compose.yml`.
- **More log sources**: add entries to `local.file_match.nginx.path_targets`.

## Stopping

```bash
docker compose down -v
```

The `-v` removes the shared `nginx-logs` volume so the next run starts with a clean log file.
