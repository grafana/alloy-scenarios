<p align="center">
  <img src="./img/banner.png" alt="Grafana Alloy Scenarios Banner" width="300"/>
</p>

# Grafana Alloy scenarios

This repository provides self-contained, runnable scenarios that show how to use [Grafana Alloy](https://grafana.com/docs/alloy/) for telemetry collection and processing.
Each scenario includes a full LGMT stack with Loki, Grafana, Mimir, and Tempo.
Each scenario also includes pre-configured dashboards so you can explore immediately.

## Get started

### Prerequisites

Install [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) before you run a scenario.

### Run a scenario

Start a scenario from its directory or from the repository root.

```bash
# Option 1: Navigate to the scenario directory
cd <scenario-dir> && docker compose up -d

# Option 2: Use centralized image management (from repo root)
./run-example.sh <scenario-directory>
```

The centralized approach stores all Docker image versions in `image-versions.env`.
You can update images across all scenarios from that single file.

### Access the stack

After a scenario starts, open these endpoints:

- **Grafana**: [http://localhost:3000](http://localhost:3000). No login is required.
- **Alloy UI**: [http://localhost:12345](http://localhost:12345) for pipeline debugging.

### Run with the Coda app overlay

Each scenario includes a `docker-compose.coda.yml` file that defines demo application services separately from the infrastructure stack.
You can run the observability backend on its own, or add the app when you are ready.

```bash
# Infrastructure only
cd <scenario-dir> && docker compose up -d

# Infrastructure + demo app
cd <scenario-dir> && docker compose -f docker-compose.yml -f docker-compose.coda.yml up -d
```

If you have the `coda` CLI installed, it manages the app overlay automatically:

```bash
coda start <scenario-dir>   # Start app containers
coda stop <scenario-dir>    # Stop app containers
coda status <scenario-dir>  # Show container status
coda list                   # List all available scenarios
```

### Stop a scenario

Shut down a scenario from its directory.

```bash
cd <scenario-dir> && docker compose down
```

## Scenarios

Browse scenarios by telemetry type.
Each row links to a directory with a README, `config.alloy`, and Docker Compose files.

### Logs

These scenarios focus on log collection, parsing, routing, and redaction.

| Scenario | Description |
| -------- | ----------- |
| [AWS Data Firehose logs](aws-firehose-logs/) | Ingest AWS Data Firehose deliveries with `loki.source.awsfirehose`. Uses a local sender. No AWS account required. |
| [GELF log ingestion](gelf-log-ingestion/) | Ingest GELF logs over UDP. |
| [Kafka logs](kafka/) | Consume and process logs from Apache Kafka topics. |
| [Log API gateway](log-api-gateway/) | Use Alloy as a centralized log gateway that accepts logs via a Loki-compatible push API endpoint. |
| [Log routing](routing/) | Route logs from multiple sources to different Loki tenants based on log content and origin. |
| [Log secret filtering](log-secret-filtering/) | Redact sensitive credentials and secrets from logs with pattern rules before storage. |
| [Logs from file](logs-file/) | Tail log files with Alloy. |
| [Logs over TCP](logs-tcp/) | Receive and process TCP logs in JSON format. |
| [Popular logging frameworks](app-instrumentation/logging/popular-logging-frameworks/) | Parse logs from popular logging frameworks across 7 programming languages. |
| [Structured log parsing](mail-house/) | Parse structured logs into labels and structured metadata. |
| [Syslog monitoring](syslog/) | Monitor non-RFC5424 compliant syslog messages with `rsyslog` and Alloy. |
| [systemd journal](systemd-journal/) | Ship systemd journal entries to Loki with filtering and labels tuned for fast queries. |
| [Windows security events](windows-events/) | Ship Windows Security event logs to Loki with SOC-focused filtering and field extraction. |

### Tracing

These scenarios show distributed tracing with OpenTelemetry and Tempo.

| Scenario | Description |
| -------- | ----------- |
| [Distributed tracing](trace-delivery/) | Learn distributed tracing through a sofa delivery workflow from order to doorstep. |
| [Game of tracing](game-of-tracing/) | Play an interactive strategy game that teaches distributed tracing, sampling, and service graphs. |
| [OpenTelemetry basic tracing](otel-basic-tracing/) | Collect and visualize OpenTelemetry traces with Alloy and Tempo. |
| [OpenTelemetry service graphs](otel-tracing-service-graphs/) | Generate service graphs with the Alloy `servicegraph` connector. |
| [OpenTelemetry span metrics](otel-span-metrics/) | Generate RED metrics from OpenTelemetry traces with the span metrics connector. Request rate, error rate, and duration. |
| [OpenTelemetry tail sampling](otel-tail-sampling/) | Apply tail sampling policies to OpenTelemetry traces with Alloy and Tempo. |

### Metrics

These scenarios collect and forward metrics with Alloy.

| Scenario | Description |
| -------- | ----------- |
| [Blackbox probing](blackbox-probing/) | Monitor endpoint availability and response times with synthetic HTTP probes. |
| [OTel metrics pipeline](otel-metrics-pipeline/) | Forward OpenTelemetry metrics from applications through Alloy. Alloy batches and transforms samples before it sends them to Prometheus. |

### Profiling

These scenarios collect continuous profiles from applications.

| Scenario | Description |
| -------- | ----------- |
| [Continuous profiling](continuous-profiling/) | Collect and visualize CPU, memory, and goroutine profiles from Go applications with Grafana Pyroscope. |

### Secrets and configuration

These scenarios load credentials and configuration from external stores.

| Scenario | Description |
| -------- | ----------- |
| [Vault secrets](vault-secrets/) | Pull `prometheus.remote_write` basic_auth credentials from HashiCorp Vault at runtime with `remote.vault`. Credentials reload on rotation. |

### Frontend

These scenarios collect telemetry from browser applications.

| Scenario | Description |
| -------- | ----------- |
| [Faro frontend observability](faro-frontend-observability/) | Collect frontend web telemetry, including logs, errors, and web vitals, from browser applications with the Faro Web SDK. |

### Cloud monitoring

These scenarios pull telemetry from cloud provider APIs.

| Scenario | Description |
| -------- | ----------- |
| [CloudWatch metrics](cloudwatch-metrics/) | Pull Amazon CloudWatch metrics into Prometheus with `prometheus.exporter.cloudwatch`. Uses LocalStack for offline reproducibility. No AWS account required. |

### Infrastructure monitoring

These scenarios monitor hosts, containers, and network devices.

| Scenario | Description |
| -------- | ----------- |
| [Docker monitoring](docker-monitoring/) | Monitor Docker container metrics and logs. |
| [Linux monitoring](linux/) | Collect Linux system metrics, journal entries, and log files with Alloy. |
| [Windows monitoring](windows/) | Monitor Windows system metrics and Event Logs. |
| [NGINX monitoring](nginx-monitoring/) | Monitor NGINX access and error logs plus `stub_status` metrics with Alloy. |
| [Self-monitoring](self-monitoring/) | Configure Alloy to monitor itself and collect its own metrics and logs. |
| [SNMP monitoring](snmp/) | Monitor SNMP devices with the Alloy SNMP exporter. |

### Database and cache monitoring

These scenarios monitor databases and in-memory caches.

| Scenario | Description |
| -------- | ----------- |
| [Elasticsearch monitoring](elasticsearch-monitoring/) | Monitor Elasticsearch cluster health, node status, and performance metrics. |
| [Memcached monitoring](memcached-monitoring/) | Monitor Memcached instance metrics, including connections, memory usage, and command performance. |
| [MySQL monitoring](mysql-monitoring/) | Monitor MySQL database server metrics and performance indicators. |
| [PostgreSQL monitoring](postgres-monitoring/) | Monitor PostgreSQL transaction statistics, connections, and server configuration. |
| [RabbitMQ monitoring](rabbitmq-monitoring/) | Monitor RabbitMQ queue, connection, and channel metrics plus broker container logs. |
| [Redis monitoring](redis-monitoring/) | Monitor Redis instance metrics, including connections, memory usage, and command throughput. |

### Kubernetes

The `k8s/` directory groups Helm-based and manifest-based examples for Alloy on Kubernetes.

| Scenario | Description |
| -------- | ----------- |
| [Kubernetes](k8s/) | Scenarios for Alloy on Kubernetes with the k8s-monitoring Helm chart or plain manifests. See subdirectories for logs, metrics, profiling, tracing, and cluster events. |

### OTel engine examples (experimental)

Alloy v1.14 and later include an experimental **OTel Engine** that runs standard OpenTelemetry Collector YAML configurations directly.
These scenarios use `alloy otel` instead of River or HCL syntax.
Refer to the [OTel examples README](otel-examples/) for details.

| Scenario | Description |
| -------- | ----------- |
| [Cost control](otel-examples/cost-control/) | Drop health checks, filter debug logs, and apply probabilistic sampling to cut telemetry volume. |
| [Count connector](otel-examples/count-connector/) | Derive request rate and error rate metrics from traces and logs with the `count` connector. |
| [File log processing](otel-examples/filelog-processing/) | Collect and parse mixed-format log files with the OTel `filelog` receiver and operator chains. |
| [Host metrics](otel-examples/host-metrics/) | Collect CPU, memory, disk, and network metrics with the `hostmetrics` receiver. |
| [Kafka buffer](otel-examples/kafka-buffer/) | Buffer traces through Kafka for durability and backpressure control. |
| [Multi-pipeline fan-out](otel-examples/multi-pipeline-fanout/) | Send traces to two backends. Each destination runs its own process path. |
| [Multi-tenant routing](otel-examples/routing-multi-tenant/) | Route logs to different Loki tenants based on resource attributes with fan-out and filter. |
| [OTTL transform cookbook](otel-examples/ottl-transform/) | A cookbook of OTTL patterns for JSON parsing, severity mapping, attribute promotion, and truncation. |
| [PII redaction](otel-examples/pii-redaction/) | Scrub credit cards, emails, and IPs from traces and logs with OTTL `replace_pattern`. |
| [Resource enrichment](otel-examples/resource-enrichment/) | Attach host, OS, and Docker metadata to all signals with `resourcedetection`. |

## Contributing

We welcome scenarios and improvements.
You can contribute in several ways.

### Suggest a scenario

Share an idea when you do not have time to implement a full scenario.

1. Open an [issue](https://github.com/grafana/alloy-scenarios/issues/new) on GitHub with the label `scenario-suggestion`
2. Describe the scenario and what it would show
3. Explain why this would be valuable to the community
4. Outline any special requirements or considerations

### Contribute a scenario

Add a complete scenario to the repository.

1. Fork this repository and create a branch
2. Create a directory in the root of this repository with a descriptive name for your scenario
3. Follow the scenario template section below
4. Submit a pull request with your scenario

### Improve a scenario

Update an existing scenario.

1. Fork this repository and create a branch
2. Make your improvements to the scenario
3. Submit a pull request with a clear description of your changes

### Scenario template

Include the following files when you create a scenario:

- `docker-compose.yml` - Docker Compose file with the LGMT stack
- `docker-compose.coda.yml` - Docker Compose override with the demo app services for use with the `coda` CLI or `-f` flag
- `config.alloy` - Alloy configuration file for the scenario
- `README.md` - Documentation that explains the scenario
- Any additional files needed for your scenario, such as scripts or data files

### Scenario checklist

Confirm the following items before you submit your scenario:

- [ ] Created a directory in the root of this repository with a descriptive name
- [ ] Included a docker-compose.yml file with the necessary components, such as LGMT stack or subset
- [ ] Created a complete config.alloy file that shows the monitoring approach
- [ ] Written a README.md with:
  - A clear description of what the scenario shows
  - Prerequisites to run the demo
  - Step-by-step instructions to run the demo
  - Expected output and what to look for
  - Screenshots if applicable
  - Explanation of key configuration elements
- [ ] Added the scenario to the table in this README.md
- [ ] Ensured the scenario works with the centralized image management system
- [ ] Verified all components start correctly with `docker compose up -d`

### Best practices for scenarios

Follow these guidelines when you author or update a scenario:

- Keep the scenario focused on one concept
- Use clear, descriptive component and variable names
- Add comments to explain complex parts of your Alloy configuration
- Include a Customizing section in your README.md when readers might change the setup
- Provide sample queries for Grafana, Prometheus, Loki, or Tempo that work with your scenario
- Use environment variables for versions and configurable parameters

## Get help

If you have questions about a scenario or Alloy configuration, use these resources:

- Join the [Grafana Labs Community Forums](https://community.grafana.com/)
- Read the [Grafana Alloy documentation](https://grafana.com/docs/alloy/)

## License

This repository is licensed under the Apache License, Version 2.0.
Refer to [LICENSE](LICENSE) for the full license text.
