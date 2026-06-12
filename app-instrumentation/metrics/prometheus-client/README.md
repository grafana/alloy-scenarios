# App Instrumentation — Prometheus client metrics across languages

This scenario shows how to expose **application metrics with native Prometheus client libraries** in five languages and collect them by **scraping** with Grafana Alloy. Each service plays a role in a fictional polyglot online store, exposes a `/metrics` endpoint, and Alloy pulls from all of them and remote-writes to Prometheus.

This is the **pull** half of a pair. Its sibling, [`../opentelemetry-sdk/`](../opentelemetry-sdk/), shows the same store instrumented with the **OpenTelemetry SDK** that **pushes** metrics over OTLP — same goal, opposite collection model.

## 🎯 Objectives

- **One telemetry type, many languages**: see idiomatic Prometheus client instrumentation in Python, Node.js, Go, Java, and C#.
- **The scrape (pull) model**: apps expose `/metrics`; Alloy scrapes them on a schedule and remote-writes to Prometheus.
- **Explicit targets**: the Alloy config lists each service by name so the pull relationship is obvious.

## The store and its services

Each app is standalone — it updates its metrics in a ~1 second background loop and serves `/metrics` on port **9100**.

| Language | Service role | `service_name` | Prometheus client library | Scrape target |
|----------|-------------|----------------|---------------------------|---------------|
| **Python** | Checkout / payments | `checkout` | `prometheus-client` | `python:9100` |
| **Node.js** | Product catalog / search | `catalog` | `prom-client` | `node:9100` |
| **Go** | Inventory / warehouse | `inventory` | `client_golang` (`promhttp`) | `go:9100` |
| **Java** | Orders | `orders` | `io.prometheus:prometheus-metrics-core` (1.x) | `java:9100` |
| **C#** | Shipping / fulfillment | `shipping` | `prometheus-net` | `csharp:9100` |

Each service exposes the same conceptual instruments as the OTel sibling, using idiomatic Prometheus names (snake_case, `_total` for counters, seconds for durations):

| Metric kind | Example (checkout) |
|-------------|--------------------|
| Counter | `checkout_transactions_total{status, payment_method}` |
| Histogram | `checkout_payment_duration_seconds` |
| Gauge | `checkout_active_carts` |
| Gauge | `checkout_queue_depth` |

## Directory structure

```
metrics/prometheus-client/
├── config.alloy              # prometheus.scrape (5 static targets) → prometheus.remote_write
├── prom-config.yaml          # minimal; Alloy pushes via remote_write
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
cd alloy-scenarios/app-instrumentation/metrics/prometheus-client

docker compose up --build -d
```

Or from the repo root with pinned image versions:

```bash
cd app-instrumentation/metrics/prometheus-client
docker compose --env-file ../../../image-versions.env up --build -d
```

This starts:
- **5 language services** exposing `/metrics` on port 9100
- **Alloy** scraping all five every 5 seconds and remote-writing to Prometheus
- **Prometheus** storing the metrics (remote-write receiver enabled)
- **Grafana** with the Metrics Drilldown app

## 🔎 Explore the metrics

- Open **Metrics Drilldown**: http://localhost:3000/a/grafana-metricsdrilldown-app
- Filter by the `service_name` label (`checkout`, `catalog`, …) or `language`.
- Query Prometheus at http://localhost:9090, e.g. `sum by (service_name) (rate(checkout_transactions_total[1m]))`.
- Watch the scrape in the Alloy UI at http://localhost:12345 — the `prometheus.scrape` component lists each target's health.

## 🔧 How it works

The Alloy config (`config.alloy`) scrapes five explicit targets and remote-writes the result:

```alloy
prometheus.scrape "store_apps" {
  targets = [
    { "__address__" = "python:9100", "service_name" = "checkout",  "language" = "python" },
    { "__address__" = "node:9100",   "service_name" = "catalog",   "language" = "javascript" },
    { "__address__" = "go:9100",     "service_name" = "inventory", "language" = "go" },
    { "__address__" = "java:9100",   "service_name" = "orders",    "language" = "java" },
    { "__address__" = "csharp:9100", "service_name" = "shipping",  "language" = "csharp" },
  ]
  scrape_interval = "5s"
  forward_to      = [prometheus.remote_write.local.receiver]
}

prometheus.remote_write "local" {
  endpoint { url = "http://prometheus:9090/api/v1/write" }
}
```

The `service_name` and `language` entries on each target become labels on every scraped series. Apps bind `/metrics` to `0.0.0.0:9100` so Alloy can reach them by their compose service name.

## Customize

- **Add a language**: expose `/metrics` on `:9100`, add the app service to `docker-compose.yml`, and add one line to the `targets` list in `config.alloy`.
- **Discover dynamically**: swap the static `targets` for `discovery.docker` + `discovery.relabel` to pick up containers automatically (see the logging scenario for that pattern).
- **Relabel or filter**: add `prometheus.relabel` between the scrape and the remote-write to drop or rename series.
