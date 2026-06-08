# Monitor a Linux host

This scenario shows how to collect system metrics and logs from a Linux host with Grafana Alloy.
Alloy uses the `prometheus.exporter.unix` component to collect CPU, memory, disk, and network metrics.
It also collects logs from the systemd journal and from common log files under `/var/log`.
Alloy forwards metrics to Prometheus and log entries to Loki.
Grafana includes pre-configured Prometheus and Loki data sources.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- A Linux host or Linux virtual machine where you run Docker.
  This scenario runs Alloy in Docker and mounts your `config.alloy` file into the container.
  It doesn't mount `/proc`, `/sys`, or `/var/log` from the host filesystem.
- Ports 3000, 9090, 3100, and 12345 free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------------+     +-------+     +-------------+     +---------+
|             |     |       |---->| Prometheus  |---->|         |
| Linux host  |---->| Alloy |     +-------------+     | Grafana |
|             |     |       |---->|    Loki     |---->|         |
+-------------+     +-------+     +-------------+     +---------+
```

- **Linux host**: The machine where you run Docker.
  Alloy uses `prometheus.exporter.unix` and the log sources in `config.alloy` to read metrics and logs from the environment available to the container.
- **Alloy**: Scrapes Node Exporter metrics from the host, tails log files and the systemd journal, and remote-writes both signals to their respective backends.
- **Prometheus**: Stores the scraped system metrics.
- **Loki**: Stores the log entries.
- **Grafana**: Visualizes metrics and logs.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/linux`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Loki, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh linux`

3. Confirm all containers are up: `cd alloy-scenarios/linux && docker compose ps`

## Explore the services

- **Grafana** at http://localhost:3000: Dashboards and **Explore**, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **Loki** at http://localhost:3100: Log storage backend.

## Understand the Alloy pipeline

The `config.alloy` pipeline runs two parallel paths: one for metrics and one for logs.

Metrics path:

1. **`prometheus.exporter.unix`**: Exposes Node Exporter metrics for the host.
   The configuration disables the `ipvs`, `btrfs`, `infiniband`, `xfs`, and `zfs` collectors, and enables the `meminfo` collector.
2. **`discovery.relabel`**: Adds `instance` and `job` labels to all metric targets before Alloy scrapes them.
3. **`prometheus.scrape`**: Scrapes the exporter every 15 seconds and forwards samples to `prometheus.remote_write.local`.
4. **`prometheus.remote_write`**: Sends all metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

Logs path:

The logs path has two parallel sources that both forward to `loki.write`.

Journal source:

1. **`discovery.relabel`**: Defines relabel rules for journal entries and promotes `unit`, `boot_id`, `instance`, `machine_id`, `transport`, and `level` as Loki labels.
2. **`loki.source.journal`**: Reads the systemd journal for the last 24 hours with `max_age = "24h0m0s"` and forwards entries to `loki.write.local`.

File source:

1. **`local.file_match`**: Discovers log files at `/var/log/{syslog,messages,*.log}` and sets `instance` and `job` labels on each target.
2. **`loki.source.file`**: Tails the matched files and forwards entries to `loki.write.local`.

Both log sources converge at **`loki.write`**, which pushes all log entries to Loki at `http://loki:3100/loki/api/v1/push`.

The metrics and logs paths don't share components.
The journal and file sources both send data to the same `loki.write` component.
`livedebugging{}` uses default settings so you can inspect both paths in the Alloy UI without extra configuration.

## Try it out

1. Open Grafana at http://localhost:3000 and import the Node Exporter community dashboard to visualize system metrics.
   Go to **Dashboards → Import**.
   Enter dashboard ID `1860` or download the JSON from https://grafana.com/api/dashboards/1860/revisions/37/download.
   Select the **Prometheus** data source and click **Import**.
   The dashboard provides CPU, memory, disk, and network panels pre-built against the metrics this scenario collects.

2. To explore logs, open the Loki Explore view in Grafana at `http://localhost:3000/a/grafana-lokiexplore-app`.
   Run `{job="integrations/node_exporter"}` to see log entries that Alloy collects from the journal and log files.

3. To inspect both pipelines in real time, open the Alloy UI at http://localhost:12345.
   Select `prometheus.scrape.integrations_node_exporter`, `loki.source.journal.logs_integrations_integrations_node_exporter_journal_scrape`, or `loki.source.file.logs_integrations_integrations_node_exporter_direct_scrape` from the component graph to use live debug.

## Customize the scenario

- **Monitor a different log path**: Edit `local.file_match.logs_integrations_integrations_node_exporter_direct_scrape` in `config.alloy` and add entries to `path_targets` to tail additional log files, such as application logs under `/var/log/myapp/*.log`.
- **Adjust the scrape interval**: Edit the `scrape_interval` value in `prometheus.scrape.integrations_node_exporter` in `config.alloy` to collect metrics more or less frequently.
  The default is 15 seconds.
- **Enable additional Node Exporter collectors**: Remove collector names from the `disable_collectors` list in `prometheus.exporter.unix.integrations_node_exporter` in `config.alloy` to expose metrics for `xfs`, `zfs`, `btrfs`, or other subsystems present on your host.
- **Monitor the Docker host**: Linux hosts only. Add bind mounts for `/proc`, `/sys`, and `/var/log` to the `alloy` service in `docker-compose.yml` so Alloy reads the host instead of the container.

## Deploy on a real Linux server

1. Install and run Alloy on each Linux host.
   Refer to https://grafana.com/docs/alloy/latest/set-up/install/linux/ for more information.

2. Copy the `config.alloy` from this scenario to your Linux server and update the remote write endpoints:

   ```alloy
   prometheus.remote_write "local" {
     endpoint {
       url = "http://<PROMETHEUS_HOST>:9090/api/v1/write"
     }
   }

   loki.write "local" {
     endpoint {
       url = "http://<LOKI_HOST>:3100/loki/api/v1/push"
     }
   }
   ```

   Replace _`<PROMETHEUS_HOST>`_ and _`<LOKI_HOST>`_ with your Prometheus and Loki host names or IP addresses.

3. Start Alloy on your Linux server. Refer to https://grafana.com/docs/alloy/latest/configure/linux/ and https://grafana.com/docs/alloy/latest/set-up/run/linux/ for more information.

## Troubleshoot common problems

Diagnose container startup failures, missing Grafana data, port conflicts, VM metrics, and empty journal logs.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited.
For Alloy specifically, the most common cause is a syntax error in `config.alloy`.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select the relevant source component and use live debug to confirm data passes through the pipeline.
If the pipeline looks healthy but Grafana shows nothing, confirm that you select the correct data source in **Explore**.

### Port conflicts with other services

Ports 3000 for Grafana, 9090 for Prometheus, 3100 for Loki, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

### Metrics reflect a VM rather than the host machine

On macOS and Windows, Docker Desktop runs containers inside a Linux virtual machine.
The default `docker-compose.yml` doesn't mount host `/proc` or `/sys`, so Node Exporter reports the container or virtual machine CPU, memory, and disk, not your physical machine.
You should expect this behavior.
To monitor your actual host, add bind mounts to `docker-compose.yml` or run Alloy natively on a Linux machine.

### Journal logs are empty

The `loki.source.journal` component reads from `/var/log/journal` or `/run/log/journal`.
If systemd isn't configured for persistent journal storage on your host, the volatile journal under `/run/log/journal` may be empty after a reboot.
Run `journalctl --disk-usage` on the host to confirm whether journal data exists.

## Stop the scenario

```sh
docker compose down
```

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- Linux install guide: https://grafana.com/docs/alloy/latest/set-up/install/linux/
- More examples: https://github.com/grafana/alloy-scenarios
