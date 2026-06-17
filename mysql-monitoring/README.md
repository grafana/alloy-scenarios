# MySQL monitoring

This scenario shows how to collect MySQL metrics with Grafana Alloy's `prometheus.exporter.mysql` component.
Alloy scrapes the embedded MySQL exporter, remote-writes samples to Prometheus, and Grafana includes a provisioned Prometheus data source for visualization.

When you start the stack, a MySQL container runs automatically on port 3306 with the `alloy` database created.
Alloy connects using the credentials in `config.alloy`.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3306 for MySQL, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------+     +-------+     +-------------+     +---------+
| MySQL |     | Alloy |     | Prometheus  |     | Grafana |
| :3306 |---->| scrape|---->| remote write|---->|         |
+-------+     +-------+     +-------------+     +---------+
```

- **mysql**: MySQL 9 with root password `alloy` and database `alloy` on port 3306.
- **Alloy**: Runs `prometheus.exporter.mysql` against `mysql:3306`, scrapes every 15 seconds, and remote-writes samples to Prometheus.
- **Prometheus**: Stores metrics at `http://prometheus:9090` with the remote write receiver enabled.
- **Grafana**: Queries metrics through a provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/mysql-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh mysql-monitoring`

3. From the `mysql-monitoring` directory, check that all containers are up: `docker compose ps`

   You should see `mysql`, `alloy`, `prometheus`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query metrics in **Explore** with the Prometheus data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **MySQL** at localhost:3306: Database endpoint mapped from the `mysql` service.

## Understand the Alloy pipeline

The `config.alloy` pipeline has three components:

1. **`prometheus.exporter.mysql.default`**: Connects with `data_source_name = "root:alloy@(mysql:3306)/"` and exposes MySQL metrics for scraping.
2. **`prometheus.scrape.mysql`**: Scrapes the exporter every 15 seconds and forwards samples to `prometheus.remote_write.default`.
3. **`prometheus.remote_write.default`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Prometheus** data source and run these PromQL queries:

   - `mysql_up`: Whether Alloy can reach MySQL
   - `mysql_global_status_connections`: Total connection attempts since server start
   - `mysql_global_status_threads_connected`: Currently open client connections
   - `mysql_global_status_queries`: Total query count by command type
   - `mysql_global_status_uptime`: Server uptime in seconds
   - `rate(mysql_global_status_bytes_received[5m])`: Inbound network throughput over the last five minutes
   - `rate(mysql_global_status_bytes_sent[5m])`: Outbound network throughput over the last five minutes

   Metrics use the `mysql_` prefix.
   If `mysql_up` returns `1`, the exporter is connected and the scenario is working.

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `prometheus.exporter.mysql.default`, `prometheus.scrape.mysql`, or `prometheus.remote_write.default` from the component graph to use live debug.

## Customize the scenario

- **Monitor a different MySQL host**: Update `data_source_name` in `prometheus.exporter.mysql.default` in `config.alloy`.
- **Adjust scrape frequency**: Edit `scrape_interval` in `prometheus.scrape.mysql` in `config.alloy`.
- **Point at your own Prometheus**: Update the `url` in `prometheus.remote_write.default` in `config.alloy` and remove the in-cluster Prometheus service if you no longer need it.

## Troubleshoot common problems

Diagnose container startup failures, missing metrics in Grafana, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `mysql`, `alloy`, or `prometheus`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `prometheus.scrape.mysql` and use live debug to check that samples pass through the pipeline.
In Grafana, select the **Prometheus** data source in **Explore** and run `mysql_up`.
If the query returns `0`, check that the `mysql` container is healthy and that the credentials in `config.alloy` match `MYSQL_ROOT_PASSWORD` in `docker-compose.yml`.

### Port conflicts with other services

Ports 3306 for MySQL, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `mysql-monitoring` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `prometheus.exporter.mysql` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.mysql/
- MySQL exporter metrics: https://github.com/prometheus/mysqld_exporter
- More examples: https://github.com/grafana/alloy-scenarios
