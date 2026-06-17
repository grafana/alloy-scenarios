# Collect logs from Kafka

This scenario shows how to use Grafana Alloy to consume logs from a Kafka topic and forward them to Loki.
A `kafka-producer` container runs `gen_log.sh`, which creates random JSON log entries every two seconds and publishes them to the `alloy-logs` topic.
Alloy reads from that topic, parses, restructures, and forwards the processed JSON payload to Loki for visualization in Grafana.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 9092 for Kafka, 3000 for Grafana, 3100 for Loki, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------------+     +-------+     +-------+     +-------+     +---------+
| Kafka producer |---->| Kafka |---->| Alloy |---->| Loki  |---->| Grafana |
+----------------+     +-------+     +-------+     +-------+     +---------+
```

- **Kafka producer**: The `kafka-producer` service runs `gen_log.sh` and publishes JSON log entries to the `alloy-logs` topic every two seconds.
- **Kafka**: A single-node KRaft broker that runs the official `apache/kafka` image and stores messages in the `alloy-logs` topic.
- **Alloy**: Consumes messages from the Kafka topic, parses and restructures the JSON payload, and forwards processed entries to Loki.
- **Loki**: Stores the processed log entries.
- **Grafana**: Visualizes the logs.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/kafka`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, and Alloy.

   - Deploy the scenario: `./run-example.sh kafka`

3. From the `kafka` directory, confirm all containers are up: `docker compose ps`
   Wait until the `kafka` container is healthy before you query logs in Grafana.

## Explore the services

- **Grafana** at http://localhost:3000: Dashboards and **Explore**, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.
- **Kafka** at localhost:9092: Broker endpoint mapped from the `kafka` service.

## Understand the Alloy pipeline

The `config.alloy` pipeline has three components: `loki.source.kafka.kafka`, `loki.process.log_data`, and `loki.write.local`.

1. **`loki.source.kafka.kafka`**: Connects to the Kafka broker at `kafka:9092`, subscribes to the `alloy-logs` topic with Kafka protocol version `3.8.0`, and attaches `source="kafka"` and `component="loki.source.kafka"` labels to each message before Alloy forwards entries to `loki.process.log_data`.
2. **`loki.process.log_data`**: Runs four pipeline stages to restructure the payload.
   - The first `stage.json` extracts `level`, `msg`, and the nested `app` object from the raw message and drops entries that aren't valid JSON.
   - The second `stage.json` runs against the extracted `app` field and maps `name` to `app_name` and `version` to `app_version`.
   - `stage.template` writes a new JSON log line to the `new_json` field from the four extracted values.
   - `stage.output` sends the `new_json` value as the final log line to `loki.write.local`.
3. **`loki.write.local`**: Pushes the processed entries to Loki at `http://loki:3100/loki/api/v1/push`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

The two-pass JSON extraction is the key design decision here.
The raw payload nests `app` as an object inside the top-level JSON, so a single `stage.json` pass can't extract both the top-level fields and the nested fields in one step.
A second `stage.json` with `source = "app"` targets only the previously extracted `app` value and makes the nested fields available for the template stage.

## Try it out

1. Open Grafana at http://localhost:3000 and navigate to **Explore**.

2. Select the **Loki** data source and run `{source="kafka"}`.
   You should see a stream of JSON log entries arrive every two seconds.
   Each entry contains `level`, `msg`, `app_name`, and `app_version` fields.

3. Filter by log level with `{source="kafka"} | json | level="error"`.
   This query parses the JSON log line and filters to error-level entries only.

4. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `loki.source.kafka.kafka` or `loki.process.log_data` from the component graph to use live debug.

## Customize the scenario

- **Use a different Kafka topic**: Change the `topics` value in `loki.source.kafka.kafka` in `config.alloy` and update the `--topic` argument in the `kafka-console-producer.sh` command in `gen_log.sh` to match.
- **Add label extraction**: Add a `stage.labels` block to `loki.process.log_data` in `config.alloy` to promote `level` or `app_name` to Loki labels, which makes filters faster at query time.
- **Connect to another Kafka cluster**: Update the `brokers` value in `loki.source.kafka.kafka` in `config.alloy` to point at your broker addresses and remove the `kafka` and `kafka-producer` services from `docker-compose.yml`.
- **Adjust the message rate**: Edit the `sleep 2` value in `gen_log.sh` to produce messages more or less frequently.

## Troubleshoot common problems

Diagnose container startup failures, missing Grafana data, port conflicts, and Kafka broker readiness.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `kafka`, `kafka-producer`, or `alloy`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `loki.source.kafka.kafka` and use live debug to check that messages arrive from the broker.
If the component shows a connection error, check that the `kafka` container is healthy with `docker compose ps`.
The broker can take up to about a minute to become ready on first start.
If Alloy exited on startup, check `docker compose logs alloy`.
Alloy builds its Kafka client when the config loads, so the broker must be healthy before Alloy starts.

### Port conflicts with other services

Ports 9092 for Kafka, 3000 for Grafana, 3100 for Loki, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `kafka` directory.
Run `docker compose down -v` from the `kafka` directory to remove the Kafka data volume as well.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `loki.source.kafka` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kafka/
- `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- More examples: https://github.com/grafana/alloy-scenarios
