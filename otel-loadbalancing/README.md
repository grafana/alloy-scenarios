# OpenTelemetry Trace-Aware Load Balancing with Grafana Alloy

Tail sampling only works if a single instance sees *every* span of a trace — and a single instance is exactly what you don't want in a highly-available sampling tier. This scenario shows the standard answer: a load-balancer Alloy in front that shards traffic across two tail-sampling Alloys **by trace ID** with [`otelcol.exporter.loadbalancing`](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.exporter.loadbalancing/).

```
                                       ┌──> alloy-downstream-1 ──┐
trace-generator ──OTLP──> alloy-lb ────┤    (tail sampling)      ├──> Tempo ──> Grafana
                       routing_key =   └──> alloy-downstream-2 ──┘
                         "traceID"          (tail sampling)
```

The generator makes the problem real: it exports **every span in its own OTLP request**. A round-robin balancer would scatter the four spans of each trace across both downstreams, and tail sampling would make contradictory half-trace decisions. `routing_key = "traceID"` reassembles the stream so each downstream sees whole traces.

## Prerequisites

- Docker and Docker Compose installed

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/otel-loadbalancing
docker compose up -d --build
```

## Access Points

| Service              | URL                    |
|----------------------|------------------------|
| Grafana              | http://localhost:3000  |
| Alloy UI (LB tier)   | http://localhost:12345 |
| Alloy UI (downstream 1) | http://localhost:12346 |
| Alloy UI (downstream 2) | http://localhost:12347 |
| Prometheus           | http://localhost:9090  |
| Tempo                | http://localhost:3200  |

## What to Expect

The generator emits one `checkout` trace per second with exactly four spans. ~15% carry an error and ~18% are slower than 2 seconds; the downstream tail samplers keep only those (policies: `status_code` + `latency` — deliberately no probabilistic fallback, so every sampling decision is explainable).

**See the split.** In Grafana **Explore → Prometheus**:

```promql
sum by (instance) (rate(otelcol_receiver_accepted_spans_total{job="alloy-downstream"}[2m]))
```

Both downstream instances receive a steady share of spans — that's the load balancer distributing traces.

**See the affinity.** In **Explore → Tempo**, search for traces of service `trace-generator` and open any of them: every sampled trace has all **4/4 spans**. Because each span travelled in its own OTLP request and the sampling policies are deterministic, a complete trace is only possible if the load balancer routed all of its spans to the same downstream instance.

**See the sampling.** Compare span rates entering the downstream tier with spans leaving it for Tempo:

```promql
sum(rate(otelcol_receiver_accepted_spans_total{job="alloy-downstream"}[2m]))
```

```promql
sum(rate(otelcol_exporter_sent_spans_total{job="alloy-downstream"}[2m]))
```

The gap is the healthy, fast traffic tail sampling dropped.

## Scaling the Pattern

* Add a third downstream: one more compose service plus one more hostname in `config-lb.alloy`'s `resolver.static.hostnames` — the consistent hash redistributes automatically.
* On Kubernetes, swap the `static` resolver for the `dns` or `k8s` resolver so the downstream set tracks a headless Service or pod selector.
* `routing_key = "service"` groups by service name instead — useful in front of `otelcol.connector.spanmetrics` rather than tail sampling.

## Stopping the Scenario

```bash
docker compose down
```
