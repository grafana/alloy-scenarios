# Route logs to Loki tenants

This scenario routes logs from a single intake to different Loki tenants based on log content and origin.
It models an OpenShift cluster log forwarder that sends application and audit logs from test and production clusters to one Alloy instance.
Alloy sets the Loki tenant from the `hostname` field and the nested `message.logger` field, then pushes to a multi-tenant Loki backend backed by MinIO.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3005 for the Alloy UI, 3015 for the Alloy log push API, 3100 for Loki, and 9000 and 9001 for MinIO free on the host.
- A `.customData` directory in the scenario folder. Create it before you start the stack if MinIO fails on first boot: `mkdir -p .customData`

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+  push   +-------+  tenant push   +------+  query  +---------+
| Promtail |-------->| Alloy |--------------->| Loki |-------->| Grafana |
| OCP sim  |         |       |                |      |         |         |
+----------+         +-------+                +---+--+         +---------+
                                                  |
                                              +-------+
                                              | MinIO |
                                              +-------+
```

Promtail simulates an OpenShift log forwarder.
It tails a local file and pushes logs to Alloy over HTTP.
Alloy receives logs on `loki.source.api`, adds a static `source=grafana-alloy` label, and routes by tenant before writing to Loki.
Loki stores data in MinIO with multi-tenant isolation through `X-Scope-OrgID`.
Grafana provisions one data source per tenant so you can query each tenant separately.

Tenant routing in `config.alloy`:

| Origin                     | Logger in nested `message` | Loki tenant       |
| -------------------------- | -------------------------- | ----------------- |
| `hostname` matches `tos.*` | `app`                      | `test_loki_app`   |
| `hostname` matches `tos.*` | `audit`                    | `test_loki_audit` |
| All other hostnames        | `app`                      | `loki_app`        |
| All other hostnames        | `audit`                    | `loki_audit`      |

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the digest-pinned image tags in `docker-compose.yaml`.

   - Go to the scenario: `cd alloy-scenarios/routing`
   - Create local data directories if needed: `mkdir -p .customData`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   - Deploy the scenario: `./run-example.sh routing`

3. From the `routing` directory, check that all containers are up: `docker compose ps`

   Expect `minio`, `loki`, `grafana`, `alloy`, and `promtail`.

## Explore the services

- **Grafana** at http://localhost:3000: Log in with `admin` / `admin`, then open **Explore**. Five Loki data sources are provisioned for different tenants.
- **Alloy UI** at http://localhost:3005: Component graph for `loki.source.api`, `loki.process`, and `loki.write`.
- **Loki** at http://localhost:3100: Multi-tenant log storage with `auth_enabled: true`.
- **MinIO** at http://localhost:9001: Object storage console for the Loki bucket. Credentials are `myuser` / `mypass`.
- **Promtail** at http://localhost:9080: Tails `support/promtail/myCustomLog.txt` and pushes to Alloy at `http://alloy:3005/loki/api/v1/push`.

## Understand the Alloy pipeline

`config.alloy` defines the pipeline:

1. **`loki.source.api`**: Listens on port 3005 for incoming log pushes.
2. **`loki.process.default_values`**: Adds the static label `source=grafana-alloy`.
3. **`loki.process.redirect_env`**: Parses JSON, extracts `hostname`, and routes logs to the correct tenant:
   - Hostnames matching `tos.*` go to the test tenants.
   - All other hostnames go to the production tenants.
   - Within each environment, nested `message.logger` value `audit` routes to the audit tenant. All other logger values stay on the default app tenant.
4. **`loki.write.loki_default`**: Pushes logs to Loki with the tenant set by `stage.tenant`.

Before you start the stack, set the `loki.write` endpoint URL in `config.alloy` to `http://loki:3100/loki/api/v1/push`. The checked-in file uses placeholder host and port values.

## Try it out

1. Add log lines with newline endings to `support/promtail/myCustomLog.txt`.

   Promtail tails the file and forwards new lines to Alloy automatically.

2. Open Grafana at http://localhost:3000, log in with `admin` / `admin`, and go to **Explore**.

   Select the data source that matches the tenant you expect, then run:

   - `{job="myApp"}`: Logs from the Promtail scrape job

   Depending on the log content, results appear in **Loki test app**, **Loki test audit**, **Loki app**, or **Loki audit**.

   Only `hostname` and the `logger` field inside the stringified `message` JSON affect routing. Other fields can vary.

   Test cluster line, routes to **Loki test app**:

   ```json
   {"hostname":"tos-worker-002.tos.example.come","message":"{\"logger\":\"app\",\"message\":\"[START]\"}"}
   ```

   Production cluster audit line, routes to **Loki audit**:

   ```json
   {"hostname":"pos-worker-001.pos.example.come","message":"{\"logger\":\"audit\",\"message\":\"[START]\"}"}
   ```

## Customize the scenario

- **Change tenant names**: Edit the `stage.tenant` values in `loki.process.redirect_env` in `config.alloy` and match them in `support/grafana/datasources.yml`.
- **Change cluster detection**: Edit the `hostnameLabel` selectors in `loki.process.redirect_env` in `config.alloy`.
- **Point Promtail at another intake**: Update the client URL in `support/promtail/promtail-config.yml`.

## Troubleshoot common problems

This section covers startup failures, missing logs, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `minio`, `loki`, or `alloy`.

If MinIO fails on first boot, create the data directory: `mkdir -p .customData`

### Loki fails to load configuration

`docker-compose.yaml` mounts `./support/loki/server.yml`, but the file on disk is `support/loki/server.yaml`.
Rename the file or update the volume mount so Loki can read its configuration.

### No logs in the expected tenant

Check that the `loki.write` endpoint in `config.alloy` points to `http://loki:3100/loki/api/v1/push`.
Open the Alloy UI at http://localhost:3005 and verify that `loki.source.api` receives pushes from Promtail.
In Grafana **Explore**, select the data source that matches the tenant table above before you run `{job="myApp"}`.

### Port conflicts with other services

Ports 3000, 3005, 3015, 3100, 9000, and 9001 must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yaml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `routing` directory.

## Next steps

- Alloy `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/
- Alloy `loki.source.api` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.api/
- More examples: https://github.com/grafana/alloy-scenarios
