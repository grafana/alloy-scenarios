# Collect JSON logs over TCP

This scenario shows how to receive JSON log lines over TCP with Grafana Alloy's `loki.source.api` component and forward them to Loki.
A Python simulator opens a TCP connection to Alloy and sends HTTP POST requests with JSON payloads to the `/loki/api/v1/raw` endpoint every 3–8 seconds.
Alloy parses each line with `loki.process`, promotes `service_name` to a Loki label, stores `code_line` and `server` as structured metadata, and pushes entries to Loki.
Grafana includes a provisioned Loki data source for querying the logs.

When you start the stack, the `simulator` container runs automatically.
It mimics applications that ship JSON logs over a long-lived TCP connection instead of writing files to disk.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

| Aspect     | [`logs-file/`](../logs-file/)      | `logs-tcp/`                                                      |
| ---------- | ---------------------------------- | ---------------------------------------------------------------- |
| Log source | Files on a shared Docker volume    | TCP client sends JSON log payloads over HTTP                     |
| Ingestion  | `local.file_match` glob on `*.log` | `loki.source.api` listener on port 9999                          |
| Processing | Direct tail and forward            | `loki.process` parses JSON and extracts fields                   |
| Demo app   | Python script writes to `app.log`  | Simulator sends structured JSON logs over TCP to Alloy port 9999 |

Use `logs-file/` when Alloy should discover and tail files from disk.
Use this scenario when applications push JSON logs over the network instead.

For Loki push API JSON with stream labels, see [`log-api-gateway/`](../log-api-gateway/).

## Understand the architecture

```text
+------------------+  TCP + HTTP POST  +--------------------------+  push  +------+  query  +---------+
| simulator        |  /loki/api/v1/raw | Alloy                    |------->| Loki |<--------| Grafana |
| (Python script)  |----------------->| loki.source.api + process |        |      |         |         |
+------------------+  port 9999       +---------------------------+        +------+         +---------+
```

- **simulator**: A Python script in `simulator.py` that opens a TCP socket to `alloy:9999` and sends HTTP POST requests with JSON bodies to `/loki/api/v1/raw`.
  Each payload includes `service_name`, `severity`, `body`, `code_line`, `server_id`, and `region`.
- **Alloy**: Receives raw JSON log lines through `loki.source.api`, parses them with `loki.process.labels`, and forwards entries to Loki.
- **Loki**: Stores the processed log entries.
- **Grafana**: Visualizes logs from the provisioned Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/logs-tcp`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, and Alloy.

   - Deploy the scenario: `./run-example.sh logs-tcp`

3. From the `logs-tcp` directory, check that all containers are up: `docker compose ps`

   You should see `simulator`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Alloy raw API** at `alloy:9999/loki/api/v1/raw` inside the Docker network: Endpoint the simulator posts to.
  Add a port mapping in `docker-compose.yml` if you want to send logs from the host.
- **Loki** at http://localhost:3100: Log storage backend.
- **simulator**: Runs in the background with no exposed port. Check output with `docker compose logs -f simulator`.

## Understand the Alloy pipeline

The `config.alloy` pipeline has four components:

1. **`loki.source.api.loki_push_api`**: Listens on `0.0.0.0:9999` for incoming requests at `/loki/api/v1/raw`.
   Each request body is treated as a log line for downstream processing.
2. **`loki.process.labels`**: Parses the JSON payload and enriches entries.
   - `stage.json` extracts `service_name`, `code_line`, and `server_id` from the log line.
   - `stage.labels` promotes `service_name` to an indexed Loki label.
   - `stage.structured_metadata` stores `code_line` and `server` as structured metadata.
3. **`loki.write.local`**: Forwards processed logs to Loki at `http://loki:3100/loki/api/v1/push`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

The simulator sends JSON log lines like this:

```json
{
  "timestamp": "2024-06-01T12:00:00Z",
  "severity": "INFO",
  "body": "User login successful",
  "service_name": "AuthService",
  "code_line": 42,
  "region": "us-east-1",
  "server_id": "srv-101"
}
```

The pipeline indexes `service_name` and keeps `code_line` and `server` as structured metadata.
Fields such as `severity`, `body`, and `region` remain in the log line and are queryable with `| json`.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Loki** data source and run these LogQL queries:

   ```logql
   {service_name="AuthService"}

   {service_name="PaymentService"}

   {service_name=~".+"} | json | severity="ERROR"
   ```

   You should see JSON log lines arrive every 3–8 seconds from the simulator.

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `loki.source.api.loki_push_api`, `loki.process.labels`, or `loki.write.local` from the component graph to use live debug.

## Customize the scenario

- **Change the listen port**: Edit `listen_port` in the `http` block of `loki.source.api.loki_push_api` in `config.alloy` and update `TARGET_PORT` in `docker-compose.yml` for the simulator.
- **Extract more fields**: Add expressions to `stage.json` in `loki.process.labels` in `config.alloy`, then promote them in `stage.labels` or `stage.structured_metadata`.
- **Simulate different services**: Edit the `service_names`, `messages`, and `log_levels` lists in `simulator.py`.
- **Point clients at a remote gateway**: Set `TARGET_HOST` and `TARGET_PORT` in `docker-compose.yml`, or send HTTP POST requests with JSON bodies to `/loki/api/v1/raw` on your Alloy host.

## Troubleshoot common problems

Diagnose container startup failures, missing logs in Grafana, simulator connection errors, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `simulator`, `alloy`, or `loki`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `loki.source.api.loki_push_api` and use live debug to check that requests pass through the pipeline.
If the pipeline looks healthy but Grafana shows nothing, check that you select the **Loki** data source in **Explore** and run `{service_name=~".+"}`.

### Simulator isn't sending logs

The `simulator` container posts to `http://alloy:9999/loki/api/v1/raw` over TCP inside the Docker network.
The simulator retries with exponential backoff until Alloy binds port 9999, but Alloy must be healthy before logs flow.
Run `docker compose logs simulator` and check that you see `Connected to alloy:9999` without repeated errors.
If errors persist, restart the simulator after Alloy is healthy: `docker compose restart simulator`.

### Port conflicts with other services

Ports 3000 for Grafana, 3100 for Loki, and 12345 for the Alloy UI must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `logs-tcp` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `loki.source.api` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.api/
- `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- File tailing alternative: [`logs-file/`](../logs-file/)
- Loki push API gateway: [`log-api-gateway/`](../log-api-gateway/)
- More examples: https://github.com/grafana/alloy-scenarios
