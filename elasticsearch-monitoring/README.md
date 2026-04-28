# Elasticsearch Monitoring with Grafana Alloy

This scenario demonstrates how to monitor an Elasticsearch instance using Grafana Alloy's built-in `prometheus.exporter.elasticsearch` component.

## Architecture

- **Elasticsearch** - The monitored Elasticsearch instance (single-node, security disabled)
- **Grafana Alloy** - Collects Elasticsearch metrics via `prometheus.exporter.elasticsearch` and remote writes them to Prometheus
- **Prometheus** - Stores the scraped metrics
- **Grafana** - Visualizes Elasticsearch metrics (auto-provisioned with Prometheus datasource)

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root using centralized image versions
./run-example.sh elasticsearch-monitoring
```

## Accessing

- **Grafana**: http://localhost:3000 (no login required)
- **Alloy UI**: http://localhost:12345
- **Prometheus**: http://localhost:9090
- **Elasticsearch**: http://localhost:9200

## Key Metrics

Once running, you can query Elasticsearch metrics in Grafana or Prometheus. Some useful metrics include:

- `elasticsearch_cluster_health_status` - Cluster health (green/yellow/red)
- `elasticsearch_cluster_health_number_of_nodes` - Number of nodes in the cluster
- `elasticsearch_indices_docs_total` - Total number of documents
- `elasticsearch_indices_store_size_bytes` - Total store size
- `elasticsearch_jvm_memory_used_bytes` - JVM memory usage
- `elasticsearch_process_cpu_percent` - CPU usage
- `elasticsearch_breakers_tripped` - Circuit breaker trip count

Metrics are scraped every 30s by default — adjust `scrape_interval` in `config.alloy` if you need finer or coarser resolution.

## Stopping

```bash
docker compose down
```
