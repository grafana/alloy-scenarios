# Host Metrics with OTel Hostmetrics Receiver

Collect CPU, memory, disk, filesystem, network, and process metrics using the OpenTelemetry `hostmetrics` receiver -- an OTel-native replacement for Prometheus node_exporter. Metrics are exported via OTLP to Prometheus.

## What This Demonstrates

- **Hostmetrics receiver**: Collects system-level metrics without a separate exporter binary
- **Scrapers**: CPU (with utilization), memory (with utilization), disk, filesystem, network, load, and process scrapers
- **Resource detection**: Automatically adds host metadata (hostname, OS type) to all metrics
- **OTLP export to Prometheus**: Metrics are sent via OTLP to Prometheus's native OTLP receiver
- **Stress testing**: A stress container generates CPU and memory load to produce interesting metric data

## Metrics Collected

| Scraper    | Example Metrics                                                    |
|------------|-------------------------------------------------------------------|
| CPU        | `system_cpu_time`, `system_cpu_utilization`                        |
| Memory     | `system_memory_usage`, `system_memory_utilization`                 |
| Disk       | `system_disk_io`, `system_disk_operations`                         |
| Filesystem | `system_filesystem_usage`, `system_filesystem_utilization`         |
| Network    | `system_network_io`, `system_network_packets`                      |
| Load       | `system_cpu_load_average_1m`, `system_cpu_load_average_5m`         |
| Process    | `process_cpu_time`, `process_memory_physical_usage`                |

## Prerequisites

- Docker and Docker Compose
- Linux host (hostmetrics requires access to `/proc` and `/sys`)

## Run

```bash
docker compose up -d
```

## Alloy UI

The Alloy pipeline debugging UI is available at [http://localhost:12345](http://localhost:12345). This is enabled by the `alloyengine` extension in `config-otel.yaml`, which runs the River UI alongside the OTel pipeline.

If you prefer a pure OTel config without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`.

## Explore

Open Grafana at [http://localhost:3000](http://localhost:3000) and go to **Explore > Prometheus**.

### Sample PromQL Queries

**CPU utilization:**
```promql
system_cpu_utilization{state="user"}
```

**Memory usage (bytes):**
```promql
system_memory_usage{state="used"}
```

**Disk I/O rate:**
```promql
rate(system_disk_io_total[5m])
```

**Network bytes transmitted:**
```promql
rate(system_network_io_total{direction="transmit"}[5m])
```

**System load averages:**
```promql
system_cpu_load_average_1m
```

**Top processes by CPU:**
```promql
topk(10, rate(process_cpu_time_total[5m]))
```

## Key Configuration

The `config-otel.yaml` configures:

1. **`hostmetrics` receiver**: Enables all major scrapers with 15s collection interval. CPU and memory utilization metrics are explicitly enabled.
2. **`resourcedetection` processor**: Uses `env` and `system` detectors to add hostname and OS metadata.
3. **`otlphttp/prometheus` exporter**: Sends metrics via OTLP to Prometheus's native OTLP endpoint.

The Alloy container runs with `pid: host` and mounts `/proc`, `/sys`, and `/` from the host to enable full system visibility.

## Stop

```bash
docker compose down
```
