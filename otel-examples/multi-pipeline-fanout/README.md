# Multi-Pipeline Fan-Out

Demonstrates sending the same traces to multiple backends with different processing per destination using the OpenTelemetry forward connector. Full-fidelity traces go to a primary Tempo instance, while sampled and attribute-stripped traces go to a secondary instance. This is a common pattern for migrations and tiered storage strategies.

## What This Demonstrates

- **Forward connector**: The `forward/sampled` connector duplicates trace data from one pipeline into another
- **Fan-out pattern**: A single intake pipeline fans out to two export pipelines with independent processing
- **Probabilistic sampling**: The secondary pipeline only keeps 10% of traces
- **Attribute stripping**: The secondary pipeline removes sensitive/large attributes (user agent, cookies, request body) and truncates remaining attributes to 128 characters
- **Dual Tempo instances**: Two independent Tempo backends receiving different subsets and fidelity levels of the same trace data

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

## Explore

Open Grafana at [http://localhost:3000](http://localhost:3000).

### Compare Primary vs Secondary

1. Go to **Explore** and select **Tempo Primary** datasource
2. Search for traces from `fanout-demo-app`
3. Pick a trace and note the attributes: full `http.request.header.user_agent`, `http.request.header.cookie`, `http.request.body` values
4. Switch datasource to **Tempo Secondary**
5. Search for the same service -- you will see far fewer traces (only ~10%)
6. On traces that do appear, the user agent, cookie, and request body attributes are gone, and remaining attributes are truncated to 128 characters

### What to Look For

| Aspect              | Tempo Primary                  | Tempo Secondary                  |
|---------------------|-------------------------------|----------------------------------|
| Trace volume        | 100% of traces                | ~10% of traces                   |
| Attribute fidelity  | Full (all attributes present) | Stripped (no UA, cookies, body)  |
| Attribute length    | Unlimited                     | Truncated to 128 chars           |

## Key Configuration

The `config-otel.yaml` defines three pipelines:

1. **`traces/intake`**: Receives OTLP, batches, then exports to both `otlp/tempo-primary` and `forward/sampled`
2. **`traces/sampled`**: Receives from the forward connector, applies probabilistic sampling (10%), strips attributes, and exports to `otlp/tempo-secondary`

The forward connector (`forward/sampled`) acts as the bridge that duplicates data from the intake pipeline to the sampled pipeline.

## Stop

```bash
docker compose down
```
