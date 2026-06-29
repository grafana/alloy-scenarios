# Elasticsearch monitoring

This scenario shows how Grafana Alloy monitors an Elasticsearch cluster with `prometheus.exporter.elasticsearch`.
Alloy scrapes node and cluster health metrics, then remote-writes them to Prometheus.
Grafana queries the provisioned Prometheus data source.
The `config.alloy` file defines the pipeline.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, 9200 for Elasticsearch, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Alloy scrapes Elasticsearch through the embedded exporter and forwards metrics to Prometheus.

```text
+---------------+     +-------+     +-------------+     +---------+
| Elasticsearch |     |       |     |             |     |         |
|    :9200      |---->| Alloy |---->| Prometheus  |---->| Grafana |
|  single-node  |     |       |     |             |     |         |
+---------------+     +-------+     +-------------+     +---------+
```

- **Elasticsearch**: Single-node cluster with security disabled on port 9200.
- **Alloy**: Exposes Elasticsearch metrics through `prometheus.exporter.elasticsearch` and remote-writes them every 30 seconds.
- **Prometheus**: Stores metrics from remote write with the receiver enabled.
- **Grafana**: Visualizes Elasticsearch metrics through a provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/elasticsearch-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh elasticsearch-monitoring`

3. Check that all containers are up: `cd alloy-scenarios/elasticsearch-monitoring && docker compose ps`

   Expect `alloy`, `elasticsearch`, `prometheus`, and `grafana`.
   Elasticsearch can take a minute to become ready on first start.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph and component health.
- **Prometheus** at http://localhost:9090: Query Elasticsearch metrics directly.
- **Elasticsearch** at http://localhost:9200: Cluster HTTP API.

## Understand the configuration

The `config.alloy` pipeline has three components:

1. **`prometheus.exporter.elasticsearch "default"`**: Connects to Elasticsearch at `http://elasticsearch:9200` and exposes exporter metrics.
2. **`prometheus.scrape "elasticsearch"`**: Scrapes the exporter every 30 seconds and forwards samples to `prometheus.remote_write.default`.
3. **`prometheus.remote_write "default"`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

By default, the exporter collects cluster health and node-level stats for the connected node.
It does not enable per-index metrics unless you set `indices = true` on the exporter block.

Metrics are scraped every 30 seconds.
Adjust `scrape_interval` on `prometheus.scrape "elasticsearch"` if you need a different resolution.

## Key metrics

Once the stack is running, query these metrics in Grafana or Prometheus:

- `elasticsearch_cluster_health_status`: cluster health with a `color` label for green, yellow, or red
- `elasticsearch_cluster_health_number_of_nodes`: number of nodes in the cluster
- `elasticsearch_indices_docs_total`: total document count per index. Requires `indices = true`.
- `elasticsearch_indices_store_size_bytes`: index store size in bytes. Requires `indices = true`.
- `elasticsearch_jvm_memory_used_bytes`: JVM memory usage by area
- `elasticsearch_process_cpu_percent`: process CPU usage
- `elasticsearch_breakers_tripped`: circuit breaker trip count

## Try it out

1. Open Grafana **Explore**, select the **Prometheus** data source, and try these PromQL queries:

   - `elasticsearch_cluster_health_status{color="green"}`: returns `1` when the cluster is in that health state
   - `elasticsearch_jvm_memory_used_bytes{area="heap"}`: JVM heap usage
   - `elasticsearch_process_cpu_percent`: process CPU usage
   - `elasticsearch_cluster_health_number_of_nodes`: number of nodes in the cluster
   - `elasticsearch_breakers_tripped`: circuit breaker trip count

   `elasticsearch_cluster_health_status` uses a `color` label with separate series for green, yellow, and red.

2. Open the Alloy UI at http://localhost:12345 and check that `prometheus.exporter.elasticsearch` and `prometheus.scrape.elasticsearch` are healthy.

## Customize the scenario

Change `scrape_interval` on `prometheus.scrape "elasticsearch"` to adjust how often metrics are collected.

To export per-index document counts and store size, add `indices = true` to `prometheus.exporter.elasticsearch "default"`.
You can also set `all = true` to collect stats from every node in the cluster through the connected node.

## Troubleshoot common problems

Use these steps when Elasticsearch is slow to start or ports conflict.

### Elasticsearch is not ready yet

On first start, Elasticsearch can take up to a minute to accept connections.
Check container logs with `docker compose logs elasticsearch` and wait until the cluster reports healthy before you query metrics.

### Port conflicts with other services

Ports 3000, 9090, 9200, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `prometheus.exporter.elasticsearch` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.elasticsearch/
- Elasticsearch exporter metrics list: https://github.com/prometheus-community/elasticsearch_exporter/blob/master/metrics.md
