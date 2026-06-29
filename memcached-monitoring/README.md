# Monitor Memcached

This scenario shows how to collect Memcached metrics with Grafana Alloy's built-in `prometheus.exporter.memcached` component.
Alloy scrapes the exporter, remote-writes samples to Prometheus, and Grafana includes a provisioned Prometheus data source for visualization.

When you start the stack, a Memcached container runs automatically on port 11211.
Alloy connects to it at `memcached:11211` inside the Docker network.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 11211 for Memcached, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-----------+     +-------+     +-------------+     +---------+
| Memcached |     | Alloy |     | Prometheus  |     | Grafana |
| :11211    |---->| scrape|---->| remote write|---->|         |
+-----------+     +-------+     +-------------+     +---------+
```

- **Memcached**: The monitored cache instance exposed on port 11211.
- **Alloy**: Runs `prometheus.exporter.memcached` against `memcached:11211`, scrapes the exporter with `prometheus.scrape`, and remote-writes samples to Prometheus.
- **Prometheus**: Stores metrics at `http://prometheus:9090` with the remote write receiver enabled.
- **Grafana**: Queries metrics through a provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/memcached-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh memcached-monitoring`

3. From the `memcached-monitoring` directory, check that all containers are up: `docker compose ps`

   You should see `memcached`, `alloy`, `prometheus`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query metrics in **Explore** with the Prometheus data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **Memcached** at localhost:11211: Cache endpoint mapped from the `memcached` service.

## Understand the Alloy pipeline

The `config.alloy` pipeline has three components:

1. **`prometheus.exporter.memcached.default`**: Connects to `memcached:11211` and exposes Memcached metrics for scraping.
2. **`prometheus.scrape.memcached`**: Scrapes the exporter targets and forwards samples to `prometheus.remote_write.default`.
3. **`prometheus.remote_write.default`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Prometheus** data source and run these PromQL queries:

   - `memcached_up`: Whether Alloy can reach Memcached
   - `memcached_current_connections`: Number of active client connections
   - `memcached_current_bytes`: Bytes currently stored in the cache
   - `memcached_current_items`: Items currently stored in the cache
   - `memcached_commands_total`: Total commands by type such as get and set
   - `memcached_items_evicted_total`: Total number of evicted items
   - `rate(memcached_read_bytes_total[5m])`: Read throughput over the last five minutes
   - `rate(memcached_written_bytes_total[5m])`: Write throughput over the last five minutes

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `prometheus.exporter.memcached.default`, `prometheus.scrape.memcached`, or `prometheus.remote_write.default` from the component graph to use live debug.

## Customize the scenario

- **Monitor a different Memcached host**: Update the `address` value in `prometheus.exporter.memcached.default` in `config.alloy`.
- **Adjust scrape frequency**: Add a `scrape_interval` to `prometheus.scrape.memcached` in `config.alloy`.
- **Point at your own Prometheus**: Update the `url` in `prometheus.remote_write.default` in `config.alloy` and remove the in-cluster Prometheus service if you no longer need it.

## Troubleshoot common problems

Diagnose container startup failures, missing metrics in Grafana, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `memcached`, `alloy`, or `prometheus`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `prometheus.scrape.memcached` and use live debug to check that samples pass through the pipeline.
In Grafana, select the **Prometheus** data source in **Explore** and run `memcached_up`.
If the query returns `0`, check that the `memcached` container is running and that Alloy can reach `memcached:11211`.

### Port conflicts with other services

Ports 11211 for Memcached, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `memcached-monitoring` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `prometheus.exporter.memcached` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.memcached/
- Memcached exporter metrics: https://github.com/prometheus/memcached_exporter
- More examples: https://github.com/grafana/alloy-scenarios
