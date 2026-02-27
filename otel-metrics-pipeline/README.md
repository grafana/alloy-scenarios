# OTel Metrics Pipeline

Demonstrates a full OpenTelemetry metrics pipeline through Grafana Alloy: a Python application generates OTLP metrics which flow through Alloy (with batching and attribute transformation) into Prometheus, and are visualized in Grafana.

## Overview

The pipeline includes:
- **Python demo app** -- generates counters, histograms, and up-down counters via the OpenTelemetry SDK, sending them as OTLP/gRPC to Alloy.
- **Grafana Alloy** -- receives OTLP metrics, batches them, applies a transform processor (adds a `deployment.environment` resource attribute), and exports via OTLP/HTTP to Prometheus.
- **Prometheus** -- ingests metrics through its native OTLP receiver with native histogram support enabled.
- **Grafana** -- auto-provisioned with a Prometheus datasource for exploring the metrics.

## Running the Demo

1. Clone the repository:
   ```
   git clone https://github.com/grafana/alloy-scenarios.git
   cd alloy-scenarios
   ```

2. Navigate to this example directory:
   ```
   cd otel-metrics-pipeline
   ```

3. Run using Docker Compose:
   ```
   docker compose up -d
   ```

   Or use the centralized image management:
   ```
   cd ..
   ./run-example.sh otel-metrics-pipeline
   ```

4. Access the services:
   - **Grafana**: http://localhost:3000
   - **Alloy UI**: http://localhost:12345
   - **Prometheus**: http://localhost:9090

## What to Expect

After a few seconds the demo app begins emitting metrics. You can explore them in several ways:

- **Prometheus** -- navigate to http://localhost:9090 and query for metrics such as `app_requests_total`, `app_errors_total`, `app_request_duration_milliseconds`, or `app_active_users`. Note that OTLP metric names are translated to Prometheus conventions (dots become underscores, units are appended as suffixes).
- **Grafana Explore** -- open http://localhost:3000/explore, select the Prometheus datasource, and build PromQL queries against the ingested metrics.
- **Alloy pipeline UI** -- visit http://localhost:12345 to inspect the live component graph showing the receiver, batch processor, transform processor, and exporter.

## Metrics Generated

| Metric | Type | Description |
|---|---|---|
| `app.requests.total` | Counter | Total HTTP requests by endpoint, method, and status |
| `app.errors.total` | Counter | Total errors by endpoint |
| `app.request.duration` | Histogram | Request latency in milliseconds |
| `app.active_users` | UpDownCounter | Current active users by region |

## Architecture

```
┌─────────────┐  OTLP/gRPC   ┌───────────────┐  OTLP/HTTP  ┌────────────┐
│  Python App  │─────────────▶│  Grafana Alloy │────────────▶│ Prometheus │
│ (metrics gen)│   :4317      │  (batch +      │   :9090     │            │
└─────────────┘               │   transform)   │             └─────┬──────┘
                              └───────────────┘                    │
                                   :12345                          │
                                 (Alloy UI)                        ▼
                                                             ┌──────────┐
                                                             │ Grafana  │
                                                             │  :3000   │
                                                             └──────────┘
```
