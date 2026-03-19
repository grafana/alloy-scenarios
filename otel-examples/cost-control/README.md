# Telemetry Cost Control

Reduce observability costs by filtering noisy telemetry and applying probabilistic sampling in the Alloy OTel pipeline, before data reaches your backends.

## What This Demonstrates

- **Filter processor** to drop unwanted spans (health checks, readiness probes, metrics endpoints)
- **Filter processor** to drop low-severity logs (DEBUG level)
- **Probabilistic sampler** for head-based trace sampling (keeps 25% of remaining traces)
- **Transform processor** to strip high-cardinality attributes (`http.user_agent`, cookies) that inflate storage

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

## Explore

Open Grafana at [http://localhost:3000](http://localhost:3000).

### Verify filtering is working

1. **Traces (Tempo):** Go to Explore > Tempo. Search for traces from `cost-control-demo`. You should see `/api/order` and `/api/error` spans but **no** `/health`, `/ready`, or `/metrics` spans -- those are dropped by the filter processor.

2. **Logs (Loki):** Go to Explore > Loki. Query `{service_name="cost-control-demo"}`. You should see INFO and ERROR logs but **no** DEBUG logs.

3. **Sampling:** Only ~25% of the remaining (non-filtered) traces make it through. Compare the demo app's request rate with the trace count in Tempo to see the reduction.

### Sample Loki query

```logql
{service_name="cost-control-demo"} | json
```

### Check the Alloy OTel pipeline

Visit the Alloy OTel HTTP server at [http://localhost:8888](http://localhost:8888).

## Key Configuration

The `config-otel.yaml` pipeline applies three cost-control stages:

1. **`filter/traces`** -- Drops spans where `http.target` or `http.route` matches `/health`, `/ready`, or `/metrics`. These high-frequency probes generate enormous trace volume with no diagnostic value.

2. **`filter/logs`** -- Drops log records with `severity_number < 9` (below INFO). DEBUG logs are useful in development but costly at scale.

3. **`probabilistic_sampler`** -- Keeps 25% of remaining traces via consistent head-based sampling. Adjust `sampling_percentage` to trade off between cost and visibility.

4. **`transform/strip`** -- Removes `http.user_agent` and `http.request.header.cookie` attributes from spans. These high-cardinality fields consume significant index and storage space.

## Stop

```bash
docker compose down
```
