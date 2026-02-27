# MySQL Monitoring with Grafana Alloy

This scenario demonstrates how to monitor a MySQL database using Grafana Alloy's `prometheus.exporter.mysql` component. Alloy scrapes MySQL metrics and remote-writes them to Prometheus, which Grafana queries for visualization.

## Prerequisites

- Docker and Docker Compose installed

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/mysql-monitoring
docker compose up -d
```

## Access Points

| Service    | URL                          |
|------------|------------------------------|
| Grafana    | http://localhost:3000        |
| Alloy UI   | http://localhost:12345       |
| Prometheus | http://localhost:9090        |

## What to Expect

Once the stack is running, Alloy connects to the MySQL instance and exposes metrics via the `prometheus.exporter.mysql` component. These metrics are scraped every 15 seconds and forwarded to Prometheus using remote write.

Open Grafana at http://localhost:3000, navigate to **Explore**, select the **Prometheus** datasource, and query for `mysql_` prefixed metrics (e.g., `mysql_up`, `mysql_global_status_connections`, `mysql_global_status_threads_connected`).

You can also inspect the Alloy pipeline at http://localhost:12345 to verify that the exporter, scrape, and remote write components are healthy. Live debugging is enabled for real-time pipeline inspection.

## Stopping the Scenario

```bash
docker compose down
```
