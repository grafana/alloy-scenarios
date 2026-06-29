# Monitor Windows metrics and logs

This scenario shows how to collect Windows performance metrics and event logs with Grafana Alloy installed natively on a Windows host.
Alloy remote-writes metrics to Prometheus and pushes processed event log entries to Loki through `config.alloy`.
You run Grafana, Loki, and Prometheus in Docker on the same machine, then install Alloy as a Windows service and copy the scenario configuration into place.

## Before you begin

Ensure you have the following:

- [Git][git] to clone the repository.
- [Docker Desktop for Windows][docker-desktop] or another Docker engine on the Windows host where you run the backends.
- A Windows Server or Windows desktop machine with administrator access to install Alloy and read the Application and System event logs.
- Ports 3000 for Grafana, 3100 for Loki, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

You can also run Grafana, Loki, and Prometheus on a Linux server or as native Windows installs.
Point the endpoints in `config.alloy` at those hosts if you don't use the included `docker-compose.yml`.

[git]: https://git-scm.com/downloads
[docker-desktop]: https://docs.docker.com/desktop/setup/install/windows-install/

## Compare with a related scenario

| Aspect         | [`linux/`](../linux/)                         | `windows/`                                           |
| -------------- | --------------------------------------------- | ---------------------------------------------------- |
| Host OS        | Linux                                         | Windows Server or desktop                            |
| Metrics source | `prometheus.exporter.unix`                    | `prometheus.exporter.windows`                        |
| Logs source    | systemd journal and files under `/var/log`    | Application and System Windows event logs            |
| Alloy runtime  | Docker container in the Linux scenario        | Native Windows service on the monitored host         |
| Backends       | Prometheus, Loki, and Grafana in Docker       | Prometheus, Loki, and Grafana in Docker              |
| Scenario focus | Full Linux host metrics and logs              | Windows performance counters and event log pipelines |

Use [`linux/`](../linux/) for Linux host observability with journal and file logs.
Use this scenario when you need Windows performance counters and event logs through Alloy on the host itself.

## Understand the architecture

Alloy runs on the Windows host and sends telemetry to backends that listen on `localhost` in this layout.
Docker Compose starts Grafana, Loki, and Prometheus on the same machine.

```text
+----------------+     +-------+     +-------------+     +---------+
| Windows host   |     |       |---->| Prometheus  |---->|         |
| perf counters  |---->| Alloy |     +-------------+     | Grafana |
| + event logs   |     |       |---->|    Loki     |---->|         |
+----------------+     +-------+     +-------------+     +---------+
```

- **Windows host**: Source of performance counters through the Windows exporter and of Application and System event log entries.
- **Alloy**: Runs as a Windows service with `config.alloy` from this directory.
  The metrics path remote-writes to Prometheus.
  The logs path parses JSON event payloads, promotes metadata, and pushes to Loki.
- **Prometheus**: Stores metrics from `prometheus.remote_write.demo` with the remote write receiver enabled.
- **Loki**: Stores event log entries from `loki.write.endpoint`.
- **Grafana**: Anonymous administrator access on port 3000 with provisioned Prometheus and Loki data sources.

## Run the scenario

1. Clone the repository on the Windows host:

   ```sh
   git clone https://github.com/grafana/alloy-scenarios.git
   ```

2. Start Grafana, Loki, and Prometheus from the scenario directory:

   ```sh
   cd alloy-scenarios/windows
   docker compose up -d
   ```

   From the repository root you can also run `./run-example.sh windows` to use pinned image versions from `image-versions.env`.

3. Check that the containers are running:

   ```sh
   docker ps
   ```

4. Install Alloy on the Windows host.
   Refer to [Install Alloy on Windows](https://grafana.com/docs/alloy/latest/set-up/install/windows/) and install Alloy as a Windows service with the Windows installer.
   Refer to [Configure Alloy](https://grafana.com/docs/alloy/latest/set-up/configuration/) for service layout and file locations.

5. Replace the default Alloy configuration:

   - Stop the **Grafana Alloy** Windows service.
   - Copy `alloy-scenarios/windows/config.alloy` to `C:\Program Files\GrafanaLabs\Alloy\config.alloy`.
   - Start the **Grafana Alloy** service.

6. Confirm the stack is ready:

   - Grafana responds at http://localhost:3000.
   - The Alloy UI responds at http://localhost:12345.

## Access the services

By default the Alloy Windows service listens on `127.0.0.1:12345`.
To open the Alloy UI from another machine on your network, update the service arguments in the registry:

1. Open **Registry Editor**.
2. Go to `HKEY_LOCAL_MACHINE\SOFTWARE\GrafanaLabs\Alloy`.
3. Open **Arguments**.
4. Set the value to:

   ```text
   run
   C:\Program Files\GrafanaLabs\Alloy\config.alloy
   --storage.path=C:\ProgramData\GrafanaLabs\Alloy\data
   --server.http.listen-addr=0.0.0.0:12345
   ```

5. Restart the **Grafana Alloy** service from the Windows **Services** app.

You can then reach the Alloy UI at `http://<windows-host-ip>:12345`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** for metrics and logs, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **Loki** at http://localhost:3100: Log storage backend.

## Understand the configuration

The `config.alloy` file defines separate metrics and logs pipelines.
`livedebugging` is enabled so you can inspect both paths in the Alloy UI.

Metrics path:

1. **`prometheus.exporter.windows.default`**: Enables collectors `cpu`, `cs`, `logical_disk`, `net`, `os`, `service`, `system`, `memory`, `scheduled_task`, and `tcp`.
2. **`prometheus.scrape.example`**: Scrapes the Windows exporter targets and forwards samples to `prometheus.remote_write.demo.receiver`.
3. **`prometheus.remote_write.demo`**: Remote-writes to `http://localhost:9090/api/v1/write`.

Logs path:

1. **`loki.source.windowsevent.application`**: Reads the Application event log with incoming timestamps enabled.
2. **`loki.source.windowsevent.System`**: Reads the System event log with incoming timestamps enabled.
   Both sources forward to `loki.process.endpoint.receiver`.
3. **`loki.process.endpoint`**: Parses JSON fields, extracts nested `execution` metadata, promotes structured metadata such as `channel` and `eventRecordID`, maps `source` to the `service_name` label, decodes the event message, and outputs the final log line.
4. **`loki.write.endpoint`**: Pushes entries to `http://localhost:3100/loki/api/v1/push`.

**Prometheus** in `docker-compose.yml` runs with `--web.enable-remote-write-receiver` so Alloy can remote-write from the Windows host through `localhost:9090`.

**Loki** uses `loki-config.yaml` with structured metadata and volume support enabled for the event log pipeline.

**Grafana** provisions Prometheus at `http://prometheus:9090` and Loki at `http://loki:3100` through its entrypoint script.

## Try it out

1. Open the Alloy UI at http://localhost:12345 and check that `prometheus.scrape.example`, `prometheus.remote_write.demo`, `loki.source.windowsevent.application`, `loki.source.windowsevent.System`, and `loki.write.endpoint` are healthy.

2. Open Grafana at http://localhost:3000/explore/metrics, select the **Prometheus** data source, and run:

   ```promql
   windows_cs_hostname
   ```

   You should see hostname metadata from the Windows exporter.

3. Open Grafana at http://localhost:3000/a/grafana-lokiexplore-app and query event logs with:

   ```logql
   {service_name=~".+"}
   ```

   You should see Application and System channel entries with decoded messages.

4. Filter to the System channel with structured metadata in **Explore** for Loki, or run a narrower query if your Grafana version exposes `channel` as a filterable field from the ingested metadata.

## Customize the scenario

- **Collect additional performance data**: Add collector names to `enabled_collectors` in `prometheus.exporter.windows.default` in `config.alloy`.
- **Ingest other event logs**: Add another `loki.source.windowsevent` block with a different `eventlog_name`, for example `Security`, and forward it to `loki.process.endpoint.receiver`.
- **Point at remote backends**: Change the URLs in `prometheus.remote_write.demo` and `loki.write.endpoint` if Grafana, Loki, and Prometheus run on another host.
- **Use pinned image versions**: Run `./run-example.sh windows` from the repository root to pick up tags from `image-versions.env`.

## Troubleshoot common problems

Diagnose Docker startup failures, Alloy service errors, missing Grafana data, and port conflicts.

### Backend containers didn't start

Run `docker ps` from the `windows` directory.
If a container exited, run `docker compose logs <SERVICE_NAME>` for `grafana`, `loki`, or `prometheus`.
Confirm Docker Desktop is running on the Windows host.

### No metrics in Grafana

Open the Alloy UI at http://localhost:12345 and check `prometheus.scrape.example` and `prometheus.remote_write.demo` for errors.
Confirm Prometheus responds at http://localhost:9090 and that the remote write receiver flag is enabled in `docker-compose.yml`.
Restart the **Grafana Alloy** service after you change `config.alloy`.

### No event logs in Grafana

Check `loki.source.windowsevent.application` and `loki.source.windowsevent.System` in the Alloy UI with live debug.
The Alloy service account must be able to read the Windows event logs.
Run the service under an account with permission to read the Application and System channels.

### Alloy UI unreachable from another machine

Confirm the service **Arguments** registry value includes `--server.http.listen-addr=0.0.0.0:12345` and that Windows Firewall allows inbound TCP traffic on port 12345.

### Port conflicts with other services

Ports 3000, 3100, 9090, and 12345 must be free on the host.
Edit the port mappings in `docker-compose.yml` or change the Alloy listen address if another process already uses one of these ports.

## Stop the scenario

Run `docker compose down` from the `windows` directory to stop Grafana, Loki, and Prometheus.

Stop the **Grafana Alloy** Windows service separately when you finish testing on the host.

## Next steps

- [`prometheus.exporter.windows` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.windows/)
- [`loki.source.windowsevent` reference](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.windowsevent/)
- [`linux/`](../linux/) for Linux host metrics and logs
- More examples: https://github.com/grafana/alloy-scenarios
