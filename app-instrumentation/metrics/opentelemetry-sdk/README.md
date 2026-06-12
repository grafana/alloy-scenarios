# App Instrumentation — OpenTelemetry SDK Metrics across languages

This scenario shows how to emit **application metrics with the OpenTelemetry SDK** from five languages and collect them through a single Grafana Alloy pipeline. Each service plays a role in a fictional polyglot online store, instruments itself with its language's OTel metrics SDK, and **pushes** metrics to Alloy over OTLP. Alloy forwards everything to Prometheus, where you explore it with Metrics Drilldown.

This is the **push** half of a pair. Its sibling, [`../prometheus-client/`](../prometheus-client/), shows the same store instrumented with native **Prometheus client libraries** that Alloy **scrapes** — same goal, opposite collection model.

## 🎯 Objectives

- **One telemetry type, many languages**: see idiomatic OTel metrics instrumentation in Python, Node.js, Go, Java, and C#.
- **The OTLP push model**: applications export metrics to Alloy; Alloy batches and forwards to Prometheus' OTLP endpoint.
- **A single, language-agnostic pipeline**: the Alloy config doesn't care which language sent the metrics.

## The store and its services

Each app is standalone — it simulates its own domain in a ~1 second loop and never calls the others.

| Language | Service role | `service.name` | OTel metrics SDK | OTLP transport |
|----------|-------------|----------------|------------------|----------------|
| **Python** | Checkout / payments | `checkout` | `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-grpc` | gRPC → `alloy:4317` |
| **Node.js** | Product catalog / search | `catalog` | `@opentelemetry/sdk-metrics` + `exporter-metrics-otlp-http` | HTTP → `alloy:4318` |
| **Go** | Inventory / warehouse | `inventory` | `go.opentelemetry.io/otel/sdk/metric` + `otlpmetricgrpc` | gRPC → `alloy:4317` |
| **Java** | Orders | `orders` | `opentelemetry-sdk` + `opentelemetry-exporter-otlp` (autoconfigure) | gRPC → `alloy:4317` |
| **C#** | Shipping / fulfillment | `shipping` | `OpenTelemetry` + `OpenTelemetry.Exporter.OpenTelemetryProtocol` | gRPC → `alloy:4317` |

> **Why two transports?** gRPC is the cleanest default for Python, Go, Java, and C#. Node.js uses OTLP/HTTP because the experimental `@opentelemetry/*-grpc` packages are fiddly to install reliably. Alloy listens on **both** 4317 (gRPC) and 4318 (HTTP), so the pipeline is identical regardless of how a service speaks. Each app reads its endpoint and protocol from the `OTEL_EXPORTER_OTLP_*` environment variables — nothing is hardcoded.

Each service emits the same four instrument kinds, named for its domain:

| Instrument kind | Example (checkout) |
|-----------------|--------------------|
| Counter | `checkout.transactions.total{status, payment_method}` |
| Histogram | `checkout.payment.duration.ms` |
| UpDownCounter | `checkout.active_carts` |
| Observable (async) Gauge | `checkout.queue_depth` |

## Directory structure

```
metrics/opentelemetry-sdk/
├── config.alloy              # OTLP receiver → batch → Prometheus OTLP exporter
├── prom-config.yaml          # promotes resource attributes (service.name, language) to labels
├── docker-compose.yml        # 5 apps + Alloy + Prometheus + Grafana
├── docker-compose.coda.yml   # just the 5 app services
├── python/   (app.py, requirements.txt, Dockerfile)
├── node/     (app.js, package.json, Dockerfile)
├── go/       (main.go, go.mod, Dockerfile)
├── java/     (pom.xml, src/main/java/store/App.java, Dockerfile)
├── csharp/   (App.csproj, Program.cs, Dockerfile)
└── README.md
```

## 🚀 Quick start

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/app-instrumentation/metrics/opentelemetry-sdk

# Build and start the five apps + Alloy + Prometheus + Grafana
docker compose up --build -d
```

Or, from the repo root with pinned image versions:

```bash
cd app-instrumentation/metrics/opentelemetry-sdk
docker compose --env-file ../../../image-versions.env up --build -d
```

This starts:
- **5 language services** pushing OTLP metrics every ~5 seconds
- **Alloy** receiving OTLP and forwarding to Prometheus
- **Prometheus** storing the metrics (OTLP receiver enabled)
- **Grafana** with the Metrics Drilldown app

## 🔎 Explore the metrics

- Open **Metrics Drilldown**: http://localhost:3000/a/grafana-metricsdrilldown-app
- Filter by the `service_name` label (`checkout`, `catalog`, `inventory`, `orders`, `shipping`) or `language` to compare how each app reports.
- Or query Prometheus directly at http://localhost:9090, e.g.:
  - `sum by (service_name) (rate(checkout_transactions_total[1m]))`
  - `histogram_quantile(0.95, sum by (le) (rate(orders_processing_duration_ms_bucket[5m])))`
- The Alloy pipeline UI is at http://localhost:12345 (use **Live debugging** to watch metrics flow).

## 🔧 How it works

The Alloy config (`config.alloy`) is three components:

```alloy
otelcol.receiver.otlp "default" {
  grpc { }   // Python, Go, Java, C#
  http { }   // Node.js
  output { metrics = [otelcol.processor.batch.default.input] }
}
otelcol.processor.batch "default" {
  output { metrics = [otelcol.exporter.otlphttp.prometheus.input] }
}
otelcol.exporter.otlphttp "prometheus" {
  client {
    endpoint = "http://prometheus:9090/api/v1/otlp"
    tls { insecure = true }
  }
}
```

Prometheus runs with `--web.enable-otlp-receiver` so it accepts the OTLP write at `/api/v1/otlp`. `prom-config.yaml` promotes the `service.name`, `language`, and other resource attributes to labels so you can group by them.

## Customize

- **Add a language**: drop a new app dir, add a service to `docker-compose.yml` with `OTEL_SERVICE_NAME` and the `OTEL_EXPORTER_OTLP_*` env vars, and it joins the pipeline automatically.
- **Switch a service to HTTP**: set `OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318` and `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`.
- **Process metrics in Alloy**: add an `otelcol.processor.transform` between the batch processor and the exporter to rename metrics or add attributes.
