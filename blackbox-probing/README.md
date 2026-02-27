# Blackbox Probing

This scenario demonstrates **synthetic monitoring** and **HTTP endpoint probing** using Grafana Alloy's `prometheus.exporter.blackbox` component.

## Overview

Blackbox probing (also known as synthetic monitoring) tests the availability and responsiveness of services from an external perspective. Instead of instrumenting applications to export metrics, the blackbox exporter actively probes endpoints and reports whether they are reachable, how long they take to respond, and other HTTP-level details.

This scenario probes two targets:
- **nginx** — a simple web server running on port 80
- **prometheus** — the Prometheus server running on port 9090

## Architecture

```
Alloy (blackbox exporter) --probes--> nginx:80
                          --probes--> prometheus:9090
                          --writes--> Prometheus (remote write)
Grafana --queries--> Prometheus
```

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root
./run-example.sh blackbox-probing
```

## Accessing the Stack

| Service    | URL                        |
|------------|----------------------------|
| Grafana    | http://localhost:3000       |
| Alloy UI   | http://localhost:12345      |
| Prometheus | http://localhost:9090       |
| nginx      | http://localhost:8080       |

## Key Metrics

Once running, you can query these metrics in Grafana or Prometheus:

- `probe_success` — 1 if the probe succeeded, 0 if it failed
- `probe_duration_seconds` — total time the probe took
- `probe_http_status_code` — HTTP status code returned by the target
- `probe_http_duration_seconds` — duration of each phase of the HTTP request (resolve, connect, tls, processing, transfer)

## Stopping

```bash
docker compose down
```
