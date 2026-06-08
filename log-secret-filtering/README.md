# Filter secrets from logs with Alloy

This scenario shows how Grafana Alloy's `loki.secretfilter` component automatically redacts secrets from log lines before they reach Loki.
A Python application continuously writes log lines to a shared log file.
Some lines contain fake secrets such as AWS keys, database connection strings, GitHub tokens, JWTs, and Slack webhooks.
Alloy tails the file, passes each line through `loki.secretfilter` using built-in Gitleaks patterns, and forwards redacted logs to Loki.
Grafana queries them through a pre-configured Loki data source, with secrets shown as `<REDACTED:$SECRET_NAME>`.

When you start the stack, a secret-logger container runs automatically.
It appends a mix of normal and secret-containing log lines to `/logs/app.log` every 2 seconds.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000, 3100, and 12345 free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +---------------------------+       +------+       +---------+
|  secret-logger   | file  | Alloy                     | push  |      | query |         |
|  (writes logs)   |------>| (file tail +              |------>| Loki |<------| Grafana |
|                  |       |  loki.secretfilter)       |       |      |       |         |
+------------------+       +---------------------------+       +------+       +---------+
```

- **secret-logger**: A Python app in `app/main.py` that writes log lines to `/logs/app.log` on a shared Docker volume.
- **Alloy**: Tails the shared log file, redacts secrets with `loki.secretfilter`, and pushes redacted logs to Loki.
  Runs with `--stability.level=experimental` because `loki.secretfilter` is an experimental component.
- **Loki**: Stores the redacted log entries.
- **Grafana**: Visualizes and queries logs to verify secrets have been removed.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/log-secret-filtering`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, and Alloy.

   - Deploy the scenario: `./run-example.sh log-secret-filtering`

3. Confirm all containers are up: `cd alloy-scenarios/log-secret-filtering && docker compose ps`

   You should see `secret-logger`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.
- **secret-logger**: Runs in the background with no exposed port. Check output with `docker compose logs -f secret-logger`.

## Understand the Alloy pipeline

The `config.alloy` pipeline has four stages:

1. **`local.file_match.app_logs`**: Discovers log files at `/tmp/logs/*.log` and sets `job="secret-app"` on each target.
2. **`loki.source.file.log_scrape`**: Tails matched files with `tail_from_end = true` and forwards log entries to `loki.secretfilter.default`.
3. **`loki.secretfilter.default`**: Redacts secret patterns using `redact_with = "<REDACTED:$SECRET_NAME>"`.
4. **`loki.write.local`**: Forwards redacted logs to Loki at `http://loki:3100/loki/api/v1/push`.

`livedebugging{}` is enabled so you can inspect the pipeline in the Alloy UI without extra configuration.

The demo app writes to `./logs/app.log` on the host, which Alloy reads from `/tmp/logs/app.log` inside the container through a shared volume mount.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.
   Select the **Loki** data source and run:

   ```logql
   {job="secret-app"}
   ```

   You should see log lines where secrets have been replaced, for example:

   - `Found config: <REDACTED:aws-access-token> with secret`
   - `Database connection: <REDACTED:generic-api-key>`

   Normal log lines such as health checks and request timings pass through unchanged.

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `loki.source.file.log_scrape`, `loki.secretfilter.default`, or `loki.write.local` from the component graph to use live debug.

## Customize the scenario

- **Change the redaction format**: Edit `redact_with` in `loki.secretfilter.default` in `config.alloy` to use a different placeholder pattern.
- **Monitor a different log path**: Edit `path_targets` in `local.file_match.app_logs` in `config.alloy` to tail additional files under `/tmp/logs/`.
- **Emit different secrets**: Edit the `secrets` and `normal` lists in `app/main.py` to change the fake credentials and routine log lines the demo app writes.
- **Adjust file discovery**: Change `sync_period` in `local.file_match.app_logs` if you add or rotate log files at runtime.

## Troubleshoot common problems

Diagnose container startup failures, missing logs in Grafana, log file collection issues, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.
This scenario runs Alloy with `--stability.level=experimental` because `loki.secretfilter` requires it.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `loki.source.file.log_scrape` and use live debug to confirm log entries pass through the pipeline.
If the pipeline looks healthy but Grafana shows nothing, confirm that you select the **Loki** data source in **Explore** and run `{job="secret-app"}`.

### Log file isn't being collected

The `secret-logger` container writes to `/logs/app.log` and Alloy reads from `/tmp/logs/app.log` through the shared `./logs` volume in `docker-compose.yml`.
Run `docker compose logs secret-logger` to confirm the app is running.
On the host, check that `./logs/app.log` exists and is growing after the stack starts.

### Port conflicts with other services

Ports 3000 for Grafana, 3100 for Loki, and 12345 for the Alloy UI must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

```sh
docker compose down
```

## Next steps

- loki.secretfilter reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.secretfilter/
- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- More examples: https://github.com/grafana/alloy-scenarios
