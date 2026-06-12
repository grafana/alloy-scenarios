# App Instrumentation — OpenTelemetry SDK Tracing across languages

This scenario shows how to emit **distributed-tracing spans with the OpenTelemetry SDK** from five languages and collect them through a single Grafana Alloy pipeline. Each service plays a role in a fictional polyglot online store, instruments itself with its language's OTel tracing SDK, and **pushes** spans to Alloy over OTLP. Alloy forwards them to Tempo, where you explore them with Traces Drilldown.

Each service emits **standalone traces** — it traces its own work rather than calling the other services. This keeps the focus on *how each language creates spans, attributes, events, and errors*. (For a cross-service distributed trace, see the [`trace-delivery`](../../../trace-delivery/) and [`game-of-tracing`](../../../game-of-tracing/) scenarios.)

## 🎯 Objectives

- **One telemetry type, many languages**: see idiomatic OTel span creation in Python, Node.js, Go, Java, and C#.
- **The OTLP push model for traces**: applications export spans to Alloy; Alloy batches and forwards to Tempo.
- **Service graphs and span metrics**: Tempo's metrics generator turns the spans into RED metrics and a service graph in Prometheus.

## The store and its services

Each app is standalone — it produces one trace per ~1 second loop and never calls the others.

| Language | Service role | `service.name` | OTel tracing SDK | OTLP transport |
|----------|-------------|----------------|------------------|----------------|
| **Python** | Checkout / payments | `checkout` | `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-grpc` | gRPC → `alloy:4317` |
| **Node.js** | Product catalog / search | `catalog` | `@opentelemetry/sdk-trace-node` + `exporter-trace-otlp-http` | HTTP → `alloy:4318` |
| **Go** | Inventory / warehouse | `inventory` | `go.opentelemetry.io/otel/sdk/trace` + `otlptracegrpc` | gRPC → `alloy:4317` |
| **Java** | Orders | `orders` | `opentelemetry-sdk` + `opentelemetry-exporter-otlp` (autoconfigure) | gRPC → `alloy:4317` |
| **C#** | Shipping / fulfillment | `shipping` | `OpenTelemetry` + `OpenTelemetry.Exporter.OpenTelemetryProtocol` | gRPC → `alloy:4317` |

> **Why two transports?** Same reason as the metrics scenario: gRPC for four languages, OTLP/HTTP for Node.js. Alloy listens on both 4317 and 4318, and each app reads its endpoint/protocol from `OTEL_EXPORTER_OTLP_*` env vars.

Each trace follows the same shape — a root span with two or three nested children, attributes, one span event, and an occasional error:

| Service | Root → children | Error (~15%) |
|---------|-----------------|--------------|
| checkout | `process_checkout` → `validate_payment` → `charge_card` | declined card |
| catalog | `search_products` → `query_index` → `rank_results` | index timeout |
| inventory | `reserve_stock` → `check_warehouse` → `decrement_stock` | out of stock |
| orders | `place_order` → `reserve_inventory` → `create_invoice` | inventory unavailable |
| shipping | `dispatch_shipment` → `select_carrier` → `print_label` | carrier API failure |

## Directory structure

```
traces/opentelemetry-sdk/
├── config.alloy              # OTLP receiver → batch → Tempo OTLP exporter
├── tempo-config.yaml         # Tempo + metrics generator (service graphs, span metrics)
├── prom-config.yaml          # stores the generated service-graph / span metrics
├── docker-compose.yml        # 5 apps + Alloy + Tempo + Prometheus + Grafana
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
cd alloy-scenarios/app-instrumentation/traces/opentelemetry-sdk

docker compose up --build -d
```

Or from the repo root with pinned image versions:

```bash
cd app-instrumentation/traces/opentelemetry-sdk
docker compose --env-file ../../../image-versions.env up --build -d
```

This starts:
- **5 language services** pushing OTLP traces every ~1 second
- **Alloy** receiving OTLP and forwarding to Tempo
- **Tempo** storing traces and generating service-graph / span metrics
- **Prometheus** storing those generated metrics
- **Grafana** with the Traces Drilldown app

## 🔎 Explore the traces

- Open **Traces Drilldown**: http://localhost:3000/a/grafana-exploretraces-app
- You'll see five services (`checkout`, `catalog`, `inventory`, `orders`, `shipping`). Drill into rate, errors, and duration per service.
- In **Explore → Tempo**, use the **Search** tab to find traces (filter by `status = error` to see the simulated failures) and the **Service Graph** tab to see the generated graph.
- The Alloy pipeline UI is at http://localhost:12345.

## 🔧 How it works

The Alloy config (`config.alloy`) receives OTLP and forwards to Tempo:

```alloy
otelcol.receiver.otlp "default" {
  grpc { }   // Python, Go, Java, C#
  http { }   // Node.js
  output { traces = [otelcol.processor.batch.default.input] }
}
otelcol.processor.batch "default" {
  output { traces = [otelcol.exporter.otlp.tempo.input] }
}
otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
    tls { insecure = true }
  }
}
```

Tempo's `metrics_generator` (configured in `tempo-config.yaml`) remote-writes `service-graphs` and `span-metrics` to Prometheus, which powers the service graph and RED metrics in Grafana.

## Customize

- **Add a language**: drop a new app dir, add a service to `docker-compose.yml` with `OTEL_SERVICE_NAME` and the `OTEL_EXPORTER_OTLP_*` env vars.
- **Tail sample**: add an `otelcol.processor.tail_sampling` before the exporter to keep only error or slow traces (see the [`otel-tail-sampling`](../../../otel-tail-sampling/) scenario).
- **Generate span metrics in Alloy** instead of Tempo: add the `otelcol.connector.spanmetrics` component (see [`otel-span-metrics`](../../../otel-span-metrics/)).
