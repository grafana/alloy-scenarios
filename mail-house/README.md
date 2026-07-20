# Parse structured logs into labels and structured metadata

This scenario shows how to split JSON log fields between Loki labels and structured metadata with Grafana Alloy.
Three Python simulators represent mail depots that send delivery JSON over TCP to Alloy's `loki.source.api` endpoint on port 9999.
Alloy parses each payload with `loki.process`, promotes low-cardinality fields to indexed labels, keeps higher-cardinality fields as structured metadata, and forwards entries to Loki.
Grafana queries them through a provisioned Loki data source.

When you start the stack, three `mail-house` containers run automatically.
Each posts JSON package events every second with a distinct `mail_house_id` of `DEPOT-01`, `DEPOT-02`, or `DEPOT-03`.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

| Aspect              | `mail-house/`                                                           | [`logs-tcp/`](../logs-tcp/)                       |
| ------------------- | ----------------------------------------------------------------------- | ------------------------------------------------- |
| Demo domain         | Mail depot package tracking                                             | Generic microservice JSON logs                    |
| Producers           | Three depots with distinct `mail_house_id` values                       | One simulator with rotating `service_name` values |
| Label strategy      | Static `service_name` plus `state`, `package_size`, and `mail_house_id` | `service_name` parsed from JSON                   |
| Structured metadata | `package_status` and `package_id`                                       | `code_line` and `server`                          |
| Timestamp handling  | `stage.timestamp` parses RFC3339 from JSON                              | Uses ingest time from the raw API                 |

Use this scenario to learn which fields belong in labels versus structured metadata.
Use `logs-tcp/` for a simpler JSON-over-TCP pipeline with fewer processing stages.

## Understand the architecture

```text
+---------------+  TCP + HTTP POST  +---------------------------+  push  +------+  query  +---------+
| mail-house-01 |  /loki/api/v1/raw | Alloy                     |------->| Loki |<--------| Grafana |
| mail-house-02 |------------------>| loki.source.api + process |        |      |         |         |
| mail-house-03 |  port 9999        +---------------------------+        +------+         +---------+
+---------------+
```

- **mail-house simulators**: Python apps in `main.py` that POST JSON delivery events to `alloy:9999/loki/api/v1/raw` over TCP.
  Each container sets `MAIL_HOUSE_ID` to `DEPOT-01`, `DEPOT-02`, or `DEPOT-03`.
- **Alloy**: Receives raw JSON through `loki.source.api`, parses timestamps and fields with `loki.process.labels`, and forwards entries to Loki.
- **Loki**: Stores entries with indexed labels and structured metadata.
  `loki-config.yaml` sets `allow_structured_metadata: true` so Loki accepts metadata from the pipeline.
- **Grafana**: Visualizes logs from the provisioned Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/mail-house`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, and Alloy.

   - Deploy the scenario: `./run-example.sh mail-house`

3. From the `mail-house` directory, check that all containers are up: `docker compose ps`

   You should see `mail-house-01`, `mail-house-02`, `mail-house-03`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Alloy raw API** at `alloy:9999/loki/api/v1/raw` inside the Docker network: Endpoint the simulators post to.
- **Loki** at http://localhost:3100: Log storage backend.
- **mail-house simulators**: Run in the background with no exposed ports. Check output with `docker compose logs -f mail-house-01`.

## Understand the Alloy pipeline

The `config.alloy` pipeline shows how to separate indexed labels from structured metadata:

1. **`loki.source.api.loki_push_api`**: Listens on `0.0.0.0:9999` for incoming requests at `/loki/api/v1/raw`.
2. **`loki.process.labels`**: Parses and enriches each JSON log line.
   - `stage.json` extracts `timestamp`, `state`, `package_size`, `package_status`, `package_id`, and `mail_house_id`.
   - `stage.timestamp` parses the extracted `timestamp` field as RFC3339.
   - `stage.labels` promotes `state`, `package_size`, and `mail_house_id` to indexed Loki labels for fast filtering.
   - `stage.structured_metadata` stores `package_status` and `package_id` as structured metadata to limit label cardinality.
   - `stage.static_labels` adds `service_name="Delivery World"` to every entry.
3. **`loki.write.local`**: Forwards processed logs to Loki at `http://loki:3100/loki/api/v1/push`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

Indexed labels are `service_name`, `state`, `package_size`, and `mail_house_id`.
Structured metadata includes `package_status` and `package_id`.
Other JSON fields such as `city`, `note`, and nested `sender` or `receiver` objects remain in the raw payload and are not promoted to labels or structured metadata.

The simulators send JSON like this:

```json
{
  "timestamp": "2024-06-01T12:00:00.123456Z",
  "state": "California",
  "city": "Los Angeles",
  "package_id": "PKG12345",
  "package_type": "Electronics",
  "package_size": "Large",
  "package_status": "info",
  "note": "In transit",
  "mail_house_id": "DEPOT-01"
}
```

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Loki** data source and run these LogQL queries:

   - `{service_name="Delivery World"}`: All delivery events from the demo service
   - `{service_name="Delivery World", package_size="Large"}`: Large packages only
   - `{service_name="Delivery World", mail_house_id="DEPOT-01"}`: Events from the first depot
   - `{service_name="Delivery World", state="Texas"}`: Events destined for Texas

   You should see delivery events arrive every second from all three depots.

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `loki.source.api.loki_push_api`, `loki.process.labels`, or `loki.write.local` from the component graph to use live debug.

## Customize the scenario

- **Change label promotion**: Move fields between `stage.labels` and `stage.structured_metadata` in `loki.process.labels` in `config.alloy` to experiment with cardinality trade-offs.
- **Add depots**: Copy a `mail-house` service block in `docker-compose.yml` with a new `MAIL_HOUSE_ID` value.
- **Change the service name**: Edit the `service_name` value in `stage.static_labels` in `config.alloy`.
- **Simulate different events**: Edit `STATES_CITIES`, `PACKAGE_SIZES`, and related lists in `main.py`.
- **Change the listen port**: Edit `listen_port` in the `http` block of `loki.source.api.loki_push_api` in `config.alloy` and set `TARGET_PORT` on the simulator services.

## Troubleshoot common problems

Diagnose container startup failures, missing logs in Grafana, simulator connection errors, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `mail-house-01`, `alloy`, or `loki`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `loki.source.api.loki_push_api` and use live debug to check that requests pass through the pipeline.
If the pipeline looks healthy but Grafana shows nothing, check that you select the **Loki** data source in **Explore** and run `{service_name="Delivery World"}`.

### Simulators aren't sending logs

Each mail-house container posts to `alloy:9999/loki/api/v1/raw` over TCP inside the Docker network.
Run `docker compose logs mail-house-01` and check for connection errors.
If a simulator exited after a socket error, restart it after Alloy is healthy: `docker compose restart mail-house-01`.

### Port conflicts with other services

Ports 3000 for Grafana, 3100 for Loki, and 12345 for the Alloy UI must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `mail-house` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `loki.source.api` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.api/
- `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- JSON over TCP example: [`logs-tcp/`](../logs-tcp/)
- More examples: https://github.com/grafana/alloy-scenarios
