# MongoDB monitoring

This scenario shows how to collect MongoDB metrics with Grafana Alloy's `prometheus.exporter.mongodb` component.
Alloy scrapes the embedded Percona `mongodb_exporter`, remote-writes samples to Prometheus, and Grafana includes a provisioned Prometheus data source for visualization.

MongoDB runs as a single-node replica set so replication and oplog metrics are exposed alongside op-counter and connection-pool metrics.
The `mongo-load` container initiates the replica set and inserts a document into `alloy.events` every second so op-counters keep incrementing.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 27017 for MongoDB, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------+     +-------+     +-------------+     +---------+
| mongo +    |     | Alloy |     | Prometheus  |     | Grafana |
| mongo-load |---->| scrape|---->| remote write|---->|         |
+------------+     +-------+     +-------------+     +---------+
```

- **mongo**: A single-member replica set started with `--replSet rs0` on port 27017.
- **mongo-load**: Initiates the replica set, waits for a writable primary, then inserts documents every second into `alloy.events`.
- **Alloy**: Runs `prometheus.exporter.mongodb` against `mongodb://mongo:27017/`, scrapes every 15 seconds, and remote-writes samples to Prometheus.
- **Prometheus**: Stores metrics at `http://prometheus:9090` with the remote write receiver enabled.
- **Grafana**: Queries metrics through a provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/mongodb-monitoring`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh mongodb-monitoring`

3. From the `mongodb-monitoring` directory, check that all containers are up: `docker compose ps`

   You should see `mongo`, `mongo-load`, `alloy`, `prometheus`, and `grafana`.

   Wait until `mongo-load` logs `primary ready - generating insert load` before you query metrics in Grafana.

## Explore the services

- **Grafana** at http://localhost:3000: Query metrics in **Explore** with the Prometheus data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **MongoDB** at mongodb://localhost:27017: Database endpoint mapped from the `mongo` service.

## Understand the Alloy pipeline

The `config.alloy` pipeline has three components:

1. **`prometheus.exporter.mongodb.default`**: Connects to `mongodb://mongo:27017/` with `direct_connect = true`.
   Sets `compatible_mode = true` and `collect_all = true` so legacy names such as `mongodb_op_counters_total` appear alongside modern `mongodb_ss_*` names and every collector, including replica-set status, is enabled.
2. **`prometheus.scrape.mongodb`**: Scrapes the exporter every 15 seconds and forwards samples to `prometheus.remote_write.default`.
3. **`prometheus.remote_write.default`**: Sends metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

Replica-set metrics such as `mongodb_mongod_replset_*` only appear when MongoDB runs as a replica set.
A standalone `mongod` does not expose them.
This scenario uses a single-member replica set so member state, member count, and oplog window metrics are available.
The per-member replication lag series `mongodb_mongod_replset_member_replication_lag` is only emitted for secondary members, so it does not appear with one member.
Add a secondary `mongod` to the set to observe real lag.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Prometheus** data source and run these PromQL queries:

   - `rate(mongodb_op_counters_total{type="insert"}[1m])`: Insert throughput from the load generator
   - `mongodb_connections{state="current"}`: Current open connections
   - `mongodb_mongod_replset_my_state`: Replica-set member state, where `1` means primary
   - `mongodb_mongod_replset_number_of_members`: Replica-set member count
   - `mongodb_mongod_replset_oplog_head_timestamp - mongodb_mongod_replset_oplog_tail_timestamp`: Oplog window in seconds

   The `mongo-load` container inserts into `alloy.events` every second, so `mongodb_op_counters_total{type="insert"}` climbs steadily.
   That rising counter is the scenario's success signal.

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `prometheus.exporter.mongodb.default`, `prometheus.scrape.mongodb`, or `prometheus.remote_write.default` from the component graph to use live debug.

## Customize the scenario

- **Monitor a different MongoDB host**: Update `mongodb_uri` in `prometheus.exporter.mongodb.default` in `config.alloy`.
- **Toggle legacy metric names**: Set `compatible_mode` in `prometheus.exporter.mongodb.default` in `config.alloy`.
- **Limit collectors**: Set `collect_all = false` and enable specific collectors if you want fewer metric series.
- **Adjust scrape frequency**: Edit `scrape_interval` in `prometheus.scrape.mongodb` in `config.alloy`.
- **Observe replication lag**: Add a secondary `mongod` member to the replica set in `docker-compose.yml`.

## Troubleshoot common problems

Diagnose container startup failures, missing metrics in Grafana, replica-set initialization delays, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `mongo`, `mongo-load`, `alloy`, or `prometheus`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `prometheus.scrape.mongodb` and use live debug to check that samples pass through the pipeline.
Run `docker compose logs mongo-load` and check that the container reached `primary ready - generating insert load`.
In Grafana, select the **Prometheus** data source in **Explore** and run `rate(mongodb_op_counters_total{type="insert"}[1m])`.
If the query is flat, the replica set may not be initialized yet or `mongo-load` may have stopped inserting.

### Port conflicts with other services

Ports 27017 for MongoDB, 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `mongodb-monitoring` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `prometheus.exporter.mongodb` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.mongodb/
- Percona MongoDB exporter: https://github.com/percona/mongodb_exporter
- More examples: https://github.com/grafana/alloy-scenarios
