# OTel Span Metrics (RED Metrics from Traces)

This scenario demonstrates how to generate **RED metrics** (Request rate, Error rate, Duration) from OpenTelemetry traces using Grafana Alloy's `otelcol.connector.spanmetrics` component.

## Overview

Instead of relying on Tempo's built-in metrics generator, this approach uses Alloy's spanmetrics connector to derive metrics directly from trace spans in the telemetry pipeline. This gives you fine-grained control over which dimensions are extracted and how histograms are configured.

### Architecture

```
Flask App ---(OTLP/gRPC)---> Alloy ---> Tempo (traces)
                                |
                                +---> spanmetrics connector ---> Prometheus (RED metrics)
```

### What Gets Generated

The `otelcol.connector.spanmetrics` component produces the following metrics from every span:

- **`duration_milliseconds`** - Histogram of span durations (for latency/duration analysis)
- **`calls`** - Counter of span calls, with `status_code` label (for request rate and error rate)

Additional dimensions extracted: `http.method`, `http.status_code`.

## Running

```bash
# From repo root
./run-example.sh otel-span-metrics

# Or directly
cd otel-span-metrics && docker compose up -d
```

## Accessing the UIs

| Service    | URL                        |
|------------|----------------------------|
| Grafana    | http://localhost:3000      |
| Alloy      | http://localhost:12345     |
| Prometheus | http://localhost:9090      |
| Tempo      | http://localhost:3200      |
| Demo App   | http://localhost:5000      |

## Exploring the Metrics

Once the scenario is running and the load generator has been active for a minute or so, open Grafana and navigate to the **Explore** page with the **Prometheus** datasource. Try these queries:

```promql
# Request rate by service and span name
rate(duration_milliseconds_count[5m])

# Error rate (spans with error status)
rate(calls{status_code="STATUS_CODE_ERROR"}[5m])

# P95 latency by span name
histogram_quantile(0.95, rate(duration_milliseconds_bucket[5m]))
```

## Stopping

```bash
cd otel-span-metrics && docker compose down
```
