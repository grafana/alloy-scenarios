# Log API Gateway

This scenario demonstrates using **Grafana Alloy** as a centralized log gateway via the `loki.source.api` component. Instead of scraping logs from files or containers, Alloy exposes a Loki-compatible push API endpoint that applications can send logs to directly.

## Architecture

```
┌─────────────────┐         ┌───────────────────────┐         ┌──────┐         ┌─────────┐
│  log-producer    │──POST──▶│  Alloy (loki.source.  │──push──▶│ Loki │◀─query──│ Grafana │
│  (Python script) │         │  api on :3500)        │         │      │         │         │
└─────────────────┘         └───────────────────────┘         └──────┘         └─────────┘
```

1. **log-producer** - A Python script that simulates multiple microservices (auth, order, notification) pushing structured logs to Alloy's Loki push API endpoint.
2. **Alloy** - Receives logs via `loki.source.api` on port 3500, enriches them with a `gateway=alloy` label, and forwards to Loki.
3. **Loki** - Stores and indexes the logs.
4. **Grafana** - Pre-configured with the Loki datasource for querying logs.

## Running

```bash
# From the repo root (uses centralized image versions)
./run-example.sh log-api-gateway

# Or directly
cd log-api-gateway && docker compose up -d
```

## Exploring

- **Grafana**: [http://localhost:3000](http://localhost:3000) - Query logs in the Explore view using the Loki datasource
- **Alloy UI**: [http://localhost:12345](http://localhost:12345) - Inspect the pipeline graph and component health

### Example LogQL Queries

```logql
# All logs from a specific service
{service_name="auth-service"}

# All logs passing through the gateway
{gateway="alloy"}

# Filter by environment
{environment="demo"}
```

## How It Works

The `loki.source.api` component in Alloy exposes a Loki-compatible HTTP endpoint (`/loki/api/v1/push`) that any application can push logs to. This is useful when:

- Applications already use the Loki push API format
- You want a centralized gateway to enrich, filter, or route logs before they reach Loki
- You need to decouple log producers from the storage backend

The Alloy pipeline in this scenario:

1. **`loki.source.api`** - Listens on port 3500 for incoming log push requests
2. **`loki.process`** - Adds a `gateway=alloy` static label to all received logs
3. **`loki.write`** - Forwards the enriched logs to Loki

## Stopping

```bash
cd log-api-gateway && docker compose down
```
