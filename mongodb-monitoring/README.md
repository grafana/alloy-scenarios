# MongoDB Monitoring with Grafana Alloy

This scenario demonstrates how to monitor a MongoDB database using Grafana Alloy's `prometheus.exporter.mongodb` component. Alloy scrapes MongoDB metrics and remote-writes them to Prometheus, which Grafana queries for visualization.

MongoDB runs as a single-node **replica set** so that replication and oplog metrics are exposed alongside the op-counter and connection-pool metrics. A small load generator continuously inserts documents so the op-counters keep incrementing.

## Prerequisites

- Docker and Docker Compose installed

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/mongodb-monitoring
docker compose up -d
```

## Access Points

| Service    | URL                          |
|------------|------------------------------|
| Grafana    | http://localhost:3000        |
| Alloy UI   | http://localhost:12345       |
| Prometheus | http://localhost:9090        |
| MongoDB    | mongodb://localhost:27017    |

## What to Expect

Once the stack is running, Alloy connects to the MongoDB instance and exposes metrics via the `prometheus.exporter.mongodb` component. These metrics are scraped every 15 seconds and forwarded to Prometheus using remote write.

Alloy embeds the Percona `mongodb_exporter`. The component's `compatible_mode` and `collect_all` arguments both default to `true`, so the legacy metric names (for example `mongodb_op_counters_total`) are emitted alongside the modern `mongodb_ss_*` names, and every collector — including replica-set status — is enabled.

Open Grafana at http://localhost:3000, navigate to **Explore**, select the **Prometheus** datasource, and try these queries:

| What you're watching | Query |
|----------------------|-------|
| Insert throughput (op-counters) | `rate(mongodb_op_counters_total{type="insert"}[1m])` |
| Current open connections | `mongodb_connections{state="current"}` |
| Replica-set member state (1 = primary) | `mongodb_mongod_replset_my_state` |
| Replica-set member count | `mongodb_mongod_replset_number_of_members` |
| Oplog window (seconds) | `mongodb_mongod_replset_oplog_head_timestamp - mongodb_mongod_replset_oplog_tail_timestamp` |

The `mongo-load` container inserts a document into `alloy.events` every second, so `mongodb_op_counters_total{type="insert"}` climbs steadily — this is the scenario's success signal.

> **Note on replication metrics:** replica-set metrics (`mongodb_mongod_replset_*`) only appear when MongoDB runs as a replica set — a standalone `mongod` does not expose them. This scenario runs a single-member replica set, which surfaces the member state, member count, and oplog window shown above. The per-member replication-lag series `mongodb_mongod_replset_member_replication_lag` is only emitted for **secondary** members, so it does not appear with a single member; add a secondary `mongod` to the set to observe real lag.

You can also inspect the Alloy pipeline at http://localhost:12345 to verify that the exporter, scrape, and remote write components are healthy. Live debugging is enabled for real-time pipeline inspection.

## Stopping the Scenario

```bash
docker compose down
```
