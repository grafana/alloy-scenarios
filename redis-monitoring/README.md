# Redis Monitoring with Grafana Alloy

This scenario demonstrates how to monitor a Redis instance using Grafana Alloy's built-in `prometheus.exporter.redis` component.

## Architecture

- **Redis** - The monitored Redis instance
- **Grafana Alloy** - Collects Redis metrics via `prometheus.exporter.redis` and remote writes them to Prometheus
- **Prometheus** - Stores the scraped metrics
- **Grafana** - Visualizes Redis metrics (auto-provisioned with Prometheus datasource)

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root using centralized image versions
./run-example.sh redis-monitoring
```

## Accessing

- **Grafana**: http://localhost:3000 (no login required)
- **Alloy UI**: http://localhost:12345
- **Prometheus**: http://localhost:9090

## Key Metrics

Once running, you can query Redis metrics in Grafana or Prometheus. Some useful metrics include:

- `redis_up` - Whether Redis is reachable
- `redis_connected_clients` - Number of connected clients
- `redis_used_memory_bytes` - Memory usage
- `redis_commands_total` - Total commands processed
- `redis_keyspace_hits_total` / `redis_keyspace_misses_total` - Cache hit ratio

## Stopping

```bash
docker compose down
```
