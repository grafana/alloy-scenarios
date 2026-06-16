# Trace Correlation with Exemplars

Click a dot on a latency histogram and land on the exact trace that caused it. This scenario wires up the full [exemplar](https://grafana.com/docs/grafana/latest/fundamentals/exemplars/) path — one of the signature LGTM-stack tricks — end to end:

```
demo app ──OTLP traces──────────────> Alloy ──otlp──> Tempo
   │                                    │                ▲
   └──/metrics (OpenMetrics with        └─remote_write   │ click-through
      trace_id exemplars) <──scrape──┘    (send_exemplars)│
                                          ▼               │
                                      Prometheus ──> Grafana panel with
                                      (exemplar-storage)  exemplar dots
```

Every link in that chain has a setting that must be right, and each one is spelled out in this scenario's files:

| Link | Where | Setting |
|------|-------|---------|
| App embeds trace ID in the histogram | `app/app.py` | `CHECKOUT_LATENCY.observe(value, {"trace_id": ...})`, exposed via **OpenMetrics** exposition (the classic Prometheus text format drops exemplars) |
| Alloy scrapes exemplars | `config.alloy` | `prometheus.scrape` with `scrape_protocols = ["OpenMetricsText1.0.0", ...]` |
| Alloy forwards exemplars | `config.alloy` | `prometheus.remote_write` endpoint with `send_exemplars = true` |
| Prometheus stores exemplars | `docker-compose.yml` | `--enable-feature=exemplar-storage` |
| Grafana links dots to traces | `grafana/datasources/datasources.yaml` | `exemplarTraceIdDestinations: [{name: trace_id, datasourceUid: tempo}]` |

## Prerequisites

- Docker and Docker Compose installed

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/trace-log-correlation-exemplars
docker compose up -d --build
```

## Access Points

| Service    | URL                          |
|------------|------------------------------|
| Grafana    | http://localhost:3000        |
| Alloy UI   | http://localhost:12345       |
| Prometheus | http://localhost:9090        |
| Tempo      | http://localhost:3200        |
| Demo app   | http://localhost:8080/checkout |

## What to Expect

The demo app requests its own `/checkout` endpoint every two seconds; ~10% of requests are deliberately slow.

Open Grafana at http://localhost:3000 → **Dashboards** → **Checkout Latency with Exemplars**. After a minute you'll see the p95/p50 latency lines with **exemplar dots** scattered around them (exemplars are pre-enabled on the panel). Hover a dot — especially a high one — and click **Query with Tempo**: Grafana opens the exact trace whose `checkout.delay_ms` attribute explains the latency you clicked on.

You can verify the chain headlessly too:

```bash
# 1. Pull an exemplar trace ID out of Prometheus...
curl -sG http://localhost:9090/api/v1/query_exemplars \
  --data-urlencode 'query=checkout_duration_seconds_bucket' \
  --data-urlencode "start=$(date -d '-10 min' +%s)" \
  --data-urlencode "end=$(date +%s)" | jq -r '.data[0].exemplars[-1].labels.trace_id'

# 2. ...and fetch that exact trace from Tempo.
curl -s http://localhost:3200/api/traces/<trace_id> | jq '.batches[0].scopeSpans[0].spans[0].name'
```

## Customizing

* Rename the exemplar label in `app.py` — and change `exemplarTraceIdDestinations[0].name` to match.
* Exemplars attach to histogram **bucket** samples: query `checkout_duration_seconds_bucket` (not `_sum`) when using the Prometheus exemplars API.
* Add routes to the app; any histogram observed inside an active span can carry that span's trace ID.

## Stopping the Scenario

```bash
docker compose down
```
