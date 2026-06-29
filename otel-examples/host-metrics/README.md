# Host metrics

This scenario shows how to collect CPU, memory, disk, filesystem, network, load, and process metrics with the OTel hostmetrics receiver in the Alloy OTel Engine.
Alloy reads host data through `/proc` and `/sys` mounts, enriches metrics with host metadata, and exports them to Prometheus over OTLP.
A stress container generates CPU and memory load so the charts show activity without manual tuning.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- A Linux host. The hostmetrics receiver needs access to `/proc` and `/sys`.
- Ports 3000 for Grafana, 9090 for Prometheus, 8888 for the OTel Engine HTTP server, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-----------+       +-----------------+       +-------------+       +---------+
| host      | /proc | Alloy OTel      |       | Prometheus  |       | Grafana |
|           |------>| Engine          |------>|             |------>|         |
+-----------+       +-----------------+       +-------------+       +---------+
```

- **host**: Linux `/proc` and `/sys` filesystems mounted read-only into the Alloy container.
- **Alloy**: Runs the OTel Engine from `config-otel.yaml` with `pid: host`. The hostmetrics receiver scrapes the mounted host data every 15 seconds. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.
- **Prometheus**: Stores metrics through its native OTLP receiver at `http://prometheus:9090/api/v1/otlp`.
- **Grafana**: Queries Prometheus through a provisioned data source.
- **stress**: Sidecar container that runs `stress --cpu 1 --vm 1 --vm-bytes 64M` to generate host CPU and memory load. It is not part of the export pipeline.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/host-metrics`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/host-metrics && docker compose --env-file ../../image-versions.env up -d`

3. From the `host-metrics` directory, check that all containers are up: `docker compose ps`

   Expect `alloy`, `prometheus`, `stress`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Prometheus data source, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Prometheus** at http://localhost:9090: Host metrics from the OTLP receiver.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### Hostmetrics receiver

The `hostmetrics` receiver scrapes every 15 seconds with these scrapers:

- **cpu**: `system.cpu.utilization` enabled
- **memory**: `system.memory.utilization` enabled
- **disk**, **filesystem**, **network**, and **load**: Default scraper settings
- **process**: All processes matched by `.*`, with errors for missing exe, I/O, and user data muted

### Metrics collected

- **CPU**: `system_cpu_time`, `system_cpu_utilization`
- **Memory**: `system_memory_usage`, `system_memory_utilization`
- **Disk**: `system_disk_io`, `system_disk_operations`
- **Filesystem**: `system_filesystem_usage`, `system_filesystem_utilization`
- **Network**: `system_network_io`, `system_network_packets`
- **Load**: `system_cpu_load_average_1m`, `system_cpu_load_average_5m`
- **Process**: `process_cpu_time`, `process_memory_physical_usage`

### Metrics pipeline

1. **`resourcedetection`**: Uses `env` and `system` detectors. Hostname comes from the OS.
2. **`batch`**: 10s timeout and batch size of 512 before export.
3. **`otlphttp/prometheus`**: Sends metrics to Prometheus over OTLP.

**Metrics**: `hostmetrics` → `resourcedetection` → `batch` → `otlphttp/prometheus`

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The hostmetrics receiver collects every 15 seconds. Wait at least one scrape interval after startup before you query.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Prometheus** data source and run these PromQL queries:

   - `system_cpu_utilization{state="user"}`: CPU utilization in user space
   - `system_memory_usage{state="used"}`: Memory usage in bytes
   - `rate(system_disk_io_total[5m])`: Disk I/O rate
   - `rate(system_network_io_total{direction="transmit"}[5m])`: Network bytes transmitted per second
   - `system_cpu_load_average_1m`: One-minute load average
   - `topk(10, rate(process_cpu_time_total[5m]))`: Top 10 processes by CPU

2. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Change scrape interval**: Edit `collection_interval` under `receivers.hostmetrics` in `config-otel.yaml`.
- **Disable scrapers**: Remove scrapers from the `scrapers` block in `config-otel.yaml`.
- **Adjust stress load**: Change the `stress` service `command` in `docker-compose.yml`.

## Troubleshoot common problems

Covers startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `alloy`, `prometheus`, or `stress`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No metrics in Prometheus

Wait at least 15 seconds for the first hostmetrics scrape.
In Grafana, select the **Prometheus** data source in **Explore** and run `system_cpu_utilization{state="user"}`.
Open http://localhost:8888 to check OTel Engine telemetry.

Hostmetrics requires a Linux host with `/proc` and `/sys` mounted into the Alloy container.
If you run Docker inside a VM or on macOS or Windows, metric coverage may be limited.

### Port conflicts with other services

Ports 3000, 9090, 8888, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/host-metrics` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry hostmetrics receiver: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/hostmetricsreceiver
- More examples: https://github.com/grafana/alloy-scenarios
