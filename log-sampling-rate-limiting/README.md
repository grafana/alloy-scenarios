# Sampling and rate-limiting 

This scenario cuts log volume and cost with `loki.process` sampling and rate limiting keep all WARN/ERROR lines, sample DEBUG/INFO down 
to a fraction, and cap throughput per stream — before `loki.write`.



## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000, 3100, and 12345 free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +-----------------------------------------+       +------+       +---------+
|  message-logger  | file  | Alloy                                   | push  |      | query |         |
|  (writes logs)   |------>| (local.file_match ---> loki.source.file |------>| Loki |<------| Grafana |
|                  |       |  ---> loki.process)                     |       |      |       |         |
+------------------+       +-----------------------------------------+       +------+       +---------+
```

- **message-logger**: A Python app in `app/main.py` that writes log lines to `/logs/app.log` on a shared Docker volume.
- **Alloy**: Tails the shared log file, cuts log volume with `loki.process`, and pushes the sampled logs to Loki.
- **Loki**: Stores the sampled and rate-limited log entries.
- **Grafana**: Visualizes and queries logs to verify log volume has decreased.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

    - Navigate to this scenario: `cd alloy-scenarios/log-sampling-rate-limiting`
    - Deploy the scenario: `docker compose up -d`

3. From the `log-sampling-rate-limiting` directory, confirm all containers are up: `docker compose ps`

   You should see `message-logger`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.
- **message-logger**: Runs in the background with no exposed port. Check output with `docker compose logs -f message-logger`.

## Understand the Alloy pipeline

The `config.alloy` pipeline has four stages:

1. **`local.file_match.logs`**: Discovers log files at `/tmp/logs/app/*.log`.
2. **`loki.source.file`**: Forwards log entries to `loki.process.filtered.receiver`.
3. **`loki.process`**: It parse the JSON log lines using `stage.json` and promotes the string to a real Loki label using `stage.labels`. 
                       It then matches the level with the help of `stage.match` and then if the log is DEBUG/INFO it samples it at 0.1 rate using `stage.sampling`.
                       If the log is WARN/ERROR, it skips the sampling phase. After that it rate-limits whatever log lines survive using `stage.limit`.
4. **`loki.write.default`**: Forwards logs to Loki at `http://loki:3100/loki/api/v1/push`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

The demo app writes to ./logs:/tmp/logs/app on the host, which Alloy reads from `/tmp/logs/app/app.log` inside the container through a shared volume mount.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**. Select the **Loki** data source.

   Run a query to see the effect of sampling directly. In the Label filter section, select `level` and choose a value (`DEBUG`, `INFO`, `WARN`, or `ERROR`). 
   In Operations, add `count_over_time` with the range set to `5m`. Choose **Instant** to get a single number, or **Range** to see it as a graph over time.

   For example, running `count_over_time({level="DEBUG"}[5m])` and `count_over_time({level="ERROR"}[5m])` as instant queries shows the sampling effect clearly.
   Since the demo app emits DEBUG lines roughly 6x more often than ERROR lines (weights of 60 vs 10), you'd expect DEBUG's stored count to be far higher if nothing were sampled. 
   Instead, because DEBUG/INFO are sampled down to ~10% while WARN/ERROR pass through untouched, the stored counts end up close to each other — in one test run, DEBUG (172), INFO (55), WARN (299), and ERROR (277) 
   all normalized to roughly the same per-weight rate (~28) once divided by their emission weight. That inversion — DEBUG ending up lower than WARN despite being emitted far more often — is the sampling stage working as intended.

2. To inspect the pipeline in real time, open the Alloy UI at http://localhost:12345. Select `loki.source.file.logs`, `loki.process.filtered`, or `loki.write.default` from the component graph to use live debug.

## Customize the scenario

- **Change the sampling rate**: Edit `rate` in `stage.sampling` in `loki.process.filtered` in `config.alloy` to get a different sampling rate.
- **Change the rate limit**: Edit `rate` and `burst` in `stage.limit` in `loki.process.filtered` in `config.alloy` to get a different rate limit.
- **Change the level weights**: Edit the `weights` list in `app/main.py` to change the different level log lines.
- **Change which level gets sampled**: Set `selector` regex in `loki.process.filtered` in `config.alloy` to change the levels getting sampled.
- **Adjust file discovery**: Change `sync_period` in `local.file_match.logs` if you add or rotate log files at runtime.

## Troubleshoot common problems

Diagnose container startup failures, docker compose logs showing stale history, missing logs in Grafana, log file collection issues, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `loki.source.file` and use live debug to check that log entries pass through the pipeline.
If the pipeline looks healthy but Grafana shows nothing, check that you select the **Loki** data source in **Explore** and run a query`.

### Port conflicts with other services

Ports 3000 for Grafana, 3100 for Loki, and 12345 for the Alloy UI must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `log-sampling-rate-limiting` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `loki.process` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process
- More examples: https://github.com/grafana/alloy-scenarios
