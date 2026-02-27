# Memcached Monitoring with Grafana Alloy

This scenario demonstrates how to monitor a Memcached instance using Grafana Alloy's built-in `prometheus.exporter.memcached` component.

## Architecture

- **Memcached** - The monitored Memcached instance
- **Grafana Alloy** - Collects Memcached metrics via `prometheus.exporter.memcached` and remote writes them to Prometheus
- **Prometheus** - Stores the scraped metrics
- **Grafana** - Visualizes Memcached metrics (auto-provisioned with Prometheus datasource)

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root using centralized image versions
./run-example.sh memcached-monitoring
```

## Accessing

- **Grafana**: http://localhost:3000 (no login required)
- **Alloy UI**: http://localhost:12345
- **Prometheus**: http://localhost:9090

## Key Metrics

Once running, you can query Memcached metrics in Grafana or Prometheus. Some useful metrics include:

- `memcached_up` - Whether Memcached is reachable
- `memcached_current_connections` - Number of current connections
- `memcached_current_bytes` - Current number of bytes stored
- `memcached_current_items` - Current number of items stored
- `memcached_commands_total` - Total commands by command type (get, set, etc.)
- `memcached_items_evicted_total` - Total number of items evicted
- `memcached_read_bytes_total` / `memcached_written_bytes_total` - Network throughput

## Stopping

```bash
docker compose down
```
