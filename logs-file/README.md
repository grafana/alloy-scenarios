# Collect logs from a file

This scenario shows how to use Grafana Alloy to tail log files on disk and forward them to Loki.
A Python demo app writes sample application logs to a shared volume every five seconds.
Alloy discovers those files with `local.file_match`, tails them with `loki.source.file`, and pushes entries to Loki for querying in Grafana.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

| Aspect     | `logs-file/`                       | [`logs-tcp/`](../logs-tcp/)                                      |
| ---------- | ---------------------------------- | ---------------------------------------------------------------- |
| Log source | Files on a shared Docker volume    | TCP client sends JSON log payloads over HTTP                     |
| Ingestion  | `local.file_match` glob on `*.log` | `loki.source.api` listener on port 9999                          |
| Processing | Direct tail and forward            | `loki.process` parses JSON and extracts fields                   |
| Demo app   | Python script writes to `app.log`  | Simulator sends structured JSON logs over TCP to Alloy port 9999 |

Use this scenario when you need to tail files Alloy can read from disk.
Use `logs-tcp/` when applications push logs over the network instead.

## Understand the architecture

```text
+----------------+         +-------+     +------+     +---------+
| Python demo    |         | Alloy |     |      |     |         |
| app writes to  |-------->| tails |---->| Loki |---->| Grafana |
| app.log        |         | files |     |      |     |         |
+----------------+         +-------+     +------+     +---------+
      |                        ^
      |  shared ./logs volume  |
      +------------------------+
```

- **Python demo app**: The `logs-file` service runs `main.py`, which writes log lines to `/logs/app.log` every five seconds.
- **Alloy**: Discovers log files under `/temp/logs/*.log`, tails them with `loki.source.file`, and forwards entries to Loki.
- **Loki**: Stores the tailed log entries.
- **Grafana**: Visualizes logs from the pre-provisioned Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/logs-file`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, and Alloy.

   - Deploy the scenario: `./run-example.sh logs-file`

3. From the `logs-file` directory, check that all containers are up: `docker compose ps`

   You should see `logs-file`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.

## Understand the Alloy pipeline

The `config.alloy` pipeline has three components: `local.file_match`, `loki.source.file`, and `loki.write`.

1. **`local.file_match.local_files`**: Scans `/temp/logs/*.log` every five seconds and attaches `job="python"` and `hostname` labels from `constants.hostname` to each discovered file.
2. **`loki.source.file.log_scrape`**: Tails the files returned by `local.file_match.local_files` and forwards new lines to `loki.write.local`.
   With `tail_from_end = true`, Alloy reads only new log lines after startup instead of replaying the entire file.
3. **`loki.write.local`**: Pushes log entries to Loki at `http://loki:3100/loki/api/v1/push`.

`livedebugging` is enabled so you can inspect entries as they move through the pipeline in the Alloy UI.

Both the demo app and Alloy mount the host `./logs` directory.
The app writes to `/logs/app.log` inside its container, and Alloy reads the same file at `/temp/logs/app.log`.

## Try it out

1. Open Grafana at http://localhost:3000 and navigate to **Explore**.

2. Select the **Loki** data source and run `{job="python"}`.
   You should see a stream of log lines arrive every five seconds from the demo app.

3. Filter by log level with `{job="python"} |= "error"`.
   The demo app randomly emits info, debug, warning, and error lines.

4. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345.
   Select `local.file_match.local_files` or `loki.source.file.log_scrape` from the component graph to use live debug.

## Customize the scenario

- **Match different files**: Change the `__path__` glob in `local.file_match.local_files` in `config.alloy`, for example to `/temp/logs/**/*.log` for nested directories.
- **Use built-in file discovery**: Replace `local.file_match` with the `file_match` block inside `loki.source.file` for simpler configuration. Refer to the [`loki.source.file` reference](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/) for details.
- **Parse log lines**: Add a `loki.process` block between `loki.source.file` and `loki.write` to extract fields or promote values to labels.
- **Replay existing file content**: Set `tail_from_end = false` in `loki.source.file.log_scrape` to read the full file from the beginning on startup.
- **Change the log rate**: Edit the `time.sleep(5)` value in `main.py` to generate log lines more or less frequently.

## Troubleshoot common problems

Diagnose container startup failures, missing log data, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `logs-file`, `alloy`, or `loki`.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `loki.source.file.log_scrape` and use live debug to check that log lines arrive from `app.log`.
Check that the demo app is running with `docker compose logs -f logs-file`.
The app creates `/logs/app.log` on startup, so allow a few seconds for the first entries to appear.

### Port conflicts with other services

Ports 3000 for Grafana, 3100 for Loki, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `logs-file` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `loki.source.file` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/
- `local.file_match` reference: https://grafana.com/docs/alloy/latest/reference/components/local/local.file_match/
- More examples: https://github.com/grafana/alloy-scenarios
