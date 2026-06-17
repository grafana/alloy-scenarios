# Use Alloy as a log API gateway

This scenario shows how to use Grafana Alloy as a centralized log gateway with the `loki.source.api` component.
Instead of scraping logs from files or containers, Alloy exposes a Loki-compatible push API endpoint that applications can send logs to directly.
Alloy enriches incoming logs with a `gateway=alloy` label and forwards them to Loki.
Grafana includes a provisioned Loki data source for querying the logs.

When you start the stack, a log-producer container runs automatically.
It simulates `auth-service`, `order-service`, and `notification-service`, posting logs to Alloy every 0.5–2 seconds.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000, 3100, 3500, and 12345 free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

| Aspect          | `log-api-gateway/`                        | [`logs-file/`](../logs-file/)                    |
| --------------- | ----------------------------------------- | ------------------------------------------------ |
| Ingestion model | Applications push logs to Alloy over HTTP | Alloy tails log files from disk                  |
| Alloy component | `loki.source.api`                         | `local.file_match` and `loki.source.file`        |
| Processing      | Adds a static `gateway=alloy` label       | Direct forward with no processing stage          |
| Demo app        | Python producer POSTs Loki push JSON      | Python script writes to a shared log file        |
| Use case        | Central gateway for many push clients     | Monitor files Alloy can read from the filesystem |

Use this scenario when applications already send logs with the Loki push API format.
Use `logs-file/` when Alloy should discover and tail files instead.

## Understand the architecture

```text
+------------------+       +-----------------------+       +------+       +---------+
|  log-producer    | POST  | Alloy                 | push  |      | query |         |
|  (Python script) |------>| (loki.source.api      |------>| Loki |<------| Grafana |
|                  |       |  on :3500)            |       |      |       |         |
+------------------+       +-----------------------+       +------+       +---------+
```

- **log-producer**: A Python script in `app/producer.py` that POSTs Loki push API JSON to `http://alloy:3500/loki/api/v1/push`.
  Each request includes stream labels `service_name` (one of the three demo services) and `environment="demo"`.
- **Alloy**: Receives logs via `loki.source.api` on port 3500, adds a `gateway=alloy` label in `loki.process.enrich`, and forwards them to Loki.
- **Loki**: Stores and indexes the log entries.
- **Grafana**: Visualizes logs from the provisioned Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/log-api-gateway`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, and Alloy.

   - Deploy the scenario: `./run-example.sh log-api-gateway`

3. From the `log-api-gateway` directory, confirm all containers are up: `docker compose ps`

   You should see `log-producer`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Alloy push API** at http://localhost:3500/loki/api/v1/push: Endpoint for incoming log push requests.
- **Loki** at http://localhost:3100: Log storage backend.
- **log-producer**: Runs in the background with no exposed port. Check output with `docker compose logs -f log-producer`.

## Understand the Alloy pipeline

The `loki.source.api` component in Alloy exposes a Loki-compatible HTTP endpoint (`/loki/api/v1/push`) that any application can push logs to.
This is useful when:

- Applications already use the Loki push API format
- You want a centralized gateway to enrich, filter, or route logs before they reach Loki
- You need to decouple log producers from the storage backend

The `config.alloy` pipeline in this scenario has a single logs path with three stages:

1. **`loki.source.api.default`**: Listens on `0.0.0.0:3500` for incoming push requests at `/loki/api/v1/push`.
2. **`loki.process.enrich`**: Adds a static `gateway=alloy` label via `stage.static_labels`.
3. **`loki.write.local`**: Forwards enriched logs to Loki at `http://loki:3100/loki/api/v1/push`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.
This scenario runs Alloy with `--stability.level=experimental` because `loki.source.api` requires it.

The demo producer sends logs in Loki push API format.
Each request includes a `streams` array with label sets and timestamped log lines:

```json
{
  "streams": [{
    "stream": {
      "service_name": "auth-service",
      "environment": "demo"
    },
    "values": [
      ["1717584000000000000", "User login attempt from IP 10.0.1.50"]
    ]
  }]
}
```

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Loki** data source and run these LogQL queries:

   ```logql
   # All logs from a specific service
   {service_name="auth-service"}

   # All logs passing through the gateway
   {gateway="alloy"}

   # Filter by environment
   {environment="demo"}
   ```

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `loki.source.api.default`, `loki.process.enrich`, or `loki.write.local` from the component graph to use live debug.

## Customize the scenario

- **Add gateway labels**: Edit the `stage.static_labels` block in `loki.process.enrich` in `config.alloy` to add labels such as `region` or `cluster`.
- **Change the listen port**: Edit `listen_port` in the `http` block of `loki.source.api.default` in `config.alloy` and update the port mapping in `docker-compose.yml` if you expose the API on a different host port.
- **Simulate different services**: Edit the `services` list in `app/producer.py` to change service names, log messages, or stream labels that the demo producer sends.
- **Point producers at a remote gateway**: Update `ALLOY_URL` in `app/producer.py`, or your application config, to send logs to `http://<ALLOY_HOST>:3500/loki/api/v1/push`.

## Troubleshoot common problems

Diagnose container startup failures, missing logs in Grafana, log producer connection errors, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.
This scenario runs Alloy with `--stability.level=experimental` because `loki.source.api` requires it.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `loki.source.api.default` and use live debug to check that push requests pass through the pipeline.
If the pipeline looks healthy but Grafana shows nothing, check that you select the **Loki** data source in **Explore**.

### Port conflicts with other services

Ports 3000 for Grafana, 3100 for Loki, 3500 for the Alloy push API, and 12345 for the Alloy UI must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

### Log producer isn't sending logs

The `log-producer` container posts to `http://alloy:3500/loki/api/v1/push` inside the Docker network.
If Alloy isn't ready when the producer starts, you may see connection errors in the producer logs.
Run `docker compose logs log-producer` and check that you see `Starting log producer...` without repeated errors.
If errors persist, restart the producer after Alloy is healthy: `docker compose restart log-producer`.

## Stop the scenario

Run `docker compose down` from the `log-api-gateway` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `loki.source.api` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.api/
- Loki push API: https://grafana.com/docs/loki/latest/reference/loki-http-api/#ingest-logs
- File tailing alternative: [`logs-file/`](../logs-file/)
- More examples: https://github.com/grafana/alloy-scenarios
