# Routing Multi-Tenant

Demonstrates using the OTel Collector **forward connector** and **filter processor** to route logs from different tenants into separate Loki organizations. A single OTLP intake pipeline fans out to per-tenant pipelines, each filtering by a `tenant` resource attribute and exporting with the correct `X-Scope-OrgID` header.

## What This Demonstrates

- **Forward connector** to fan out logs from one pipeline into multiple downstream pipelines
- **Filter processor** to keep only logs matching a specific tenant
- **Resource processor** to enrich logs with per-tenant attributes
- **Multi-tenant Loki** with `auth_enabled: true` and `X-Scope-OrgID` header routing
- Querying isolated tenant data in Grafana using separate datasources

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

The log generator automatically sends logs for both tenants every 2 seconds.

## Explore

1. Open Grafana at [http://localhost:3000](http://localhost:3000) (no login required).
2. Go to **Explore**.

### Query team-a logs

3. Select the **Loki (team-a)** datasource and run:

```logql
{service_name="frontend-service"}
```

You should only see logs from team-a (frontend-service messages).

### Query team-b logs

4. Switch to the **Loki (team-b)** datasource and run:

```logql
{service_name="order-service"}
```

You should only see logs from team-b (order-service messages).

### Verify isolation

5. Confirm that team-a's datasource cannot see team-b's logs and vice versa -- this is enforced by Loki's multi-tenant `X-Scope-OrgID` header.

## Key Configuration

The `config-otel.yaml` uses a three-stage pipeline architecture:

1. **Intake pipeline** (`logs/intake`) -- receives all OTLP logs and exports to two forward connectors (`forward/team-a` and `forward/team-b`).
2. **Per-tenant pipelines** (`logs/team-a`, `logs/team-b`) -- each receives from its forward connector, applies a filter processor that drops logs not matching the tenant, enriches with a resource processor, and exports to a tenant-specific Loki exporter with the appropriate `X-Scope-OrgID` header.

The filter processors use `resource.attributes["tenant"] != "team-a"` (and `team-b`) to drop non-matching logs, effectively routing each tenant's data to its own Loki organization.

## Stop

```bash
docker compose down
```
