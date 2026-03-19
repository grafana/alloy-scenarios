<p align="center">
  <img src="./img/banner.png" alt="Grafana Alloy Scenarios Banner" width="300"/>
</p>

# Grafana Alloy Scenarios

A collection of self-contained, runnable scenarios demonstrating how to use [Grafana Alloy](https://grafana.com/docs/alloy/) for telemetry collection and processing. Each scenario includes a full LGMT stack (Loki, Grafana, Mimir, Tempo) with pre-configured dashboards so you can explore immediately.

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

### Run a scenario

```bash
# Option 1: Navigate to the scenario directory
cd <scenario-dir> && docker compose up -d

# Option 2: Use centralized image management (from repo root)
./run-example.sh <scenario-directory>
```

The centralized approach manages all Docker image versions in a single `image-versions.env` file, making it easy to update images across all scenarios.

### Access the stack

Once a scenario is running:

- **Grafana**: [http://localhost:3000](http://localhost:3000) (no login required)
- **Alloy UI**: [http://localhost:12345](http://localhost:12345) (pipeline debugging)

### Stop a scenario

```bash
cd <scenario-dir> && docker compose down
```

## Scenarios

### Logs

| Scenario | Description |
| -------- | ----------- |
| [GELF log ingestion](gelf-log-ingestion/) | Ingest structured logs from applications using the GELF (Graylog Extended Log Format) protocol over UDP. |
| [Kafka logs](kafka/) | Consume and process logs from Apache Kafka topics. |
| [Log API gateway](log-api-gateway/) | Use Alloy as a centralized log gateway that accepts logs via a Loki-compatible push API endpoint. |
| [Log routing](routing/) | Route logs from multiple sources to different Loki tenants based on log content and origin. |
| [Log secret filtering](log-secret-filtering/) | Automatically redact sensitive credentials and secrets from logs using pattern matching before storage. |
| [Logs from file](logs-file/) | Monitor and tail log files using Alloy. |
| [Logs over TCP](logs-tcp/) | Receive and process TCP logs in JSON format. |
| [Popular logging frameworks](app-instrumentation/logging/popular-logging-frameworks/) | Parse logs from popular logging frameworks across 7 programming languages. |
| [Structured log parsing](mail-house/) | Parse structured logs into labels and structured metadata. |
| [Syslog monitoring](syslog/) | Monitor non-RFC5424 compliant syslog messages using `rsyslog` and Alloy. |

### Tracing

| Scenario | Description |
| -------- | ----------- |
| [Distributed tracing](trace-delivery/) | Learn distributed tracing through a sofa delivery workflow from order to doorstep. |
| [Game of tracing](game-of-tracing/) | An interactive strategy game teaching distributed tracing, sampling, and service graphs. |
| [OpenTelemetry basic tracing](otel-basic-tracing/) | Collect and visualize OpenTelemetry traces using Alloy and Tempo. |
| [OpenTelemetry service graphs](otel-tracing-service-graphs/) | Generate service graphs using the Alloy `servicegraph` connector. |
| [OpenTelemetry span metrics](otel-span-metrics/) | Generate RED metrics (Request rate, Error rate, Duration) from OpenTelemetry traces using the span metrics connector. |
| [OpenTelemetry tail sampling](otel-tail-sampling/) | Apply tail sampling policies to OpenTelemetry traces with Alloy and Tempo. |

### Metrics

| Scenario | Description |
| -------- | ----------- |
| [Blackbox probing](blackbox-probing/) | Monitor endpoint availability and response times using synthetic HTTP probes. |
| [OTel metrics pipeline](otel-metrics-pipeline/) | Forward OpenTelemetry metrics from applications through Alloy with batching and transformation into Prometheus. |

### Profiling

| Scenario | Description |
| -------- | ----------- |
| [Continuous profiling](continuous-profiling/) | Collect and visualize CPU, memory, and goroutine profiles from Go applications using Grafana Pyroscope. |

### Frontend

| Scenario | Description |
| -------- | ----------- |
| [Faro frontend observability](faro-frontend-observability/) | Collect frontend web telemetry (logs, errors, web vitals) from browser applications using the Faro Web SDK. |

### Infrastructure Monitoring

| Scenario | Description |
| -------- | ----------- |
| [Docker monitoring](docker-monitoring/) | Monitor Docker container metrics and logs. |
| [Monitor Linux](linux/) | Monitor a Linux server's system metrics using Alloy. |
| [Monitor Windows](windows/) | Monitor Windows system metrics and Event Logs. |
| [Self-monitoring](self-monitoring/) | Configure Alloy to monitor itself, collecting its own metrics and logs. |
| [SNMP monitoring](snmp/) | Monitor SNMP devices using the Alloy SNMP exporter. |

### Database and Cache Monitoring

| Scenario | Description |
| -------- | ----------- |
| [Elasticsearch monitoring](elasticsearch-monitoring/) | Monitor Elasticsearch cluster health, node status, and performance metrics. |
| [Memcached monitoring](memcached-monitoring/) | Monitor Memcached instance metrics including connections, memory usage, and command performance. |
| [MySQL monitoring](mysql-monitoring/) | Monitor MySQL database server metrics and performance indicators. |
| [PostgreSQL monitoring](postgres-monitoring/) | Monitor PostgreSQL transaction statistics, connections, and server configuration. |
| [Redis monitoring](redis-monitoring/) | Monitor Redis instance metrics including connections, memory usage, and command throughput. |

### Kubernetes

| Scenario | Description |
| -------- | ----------- |
| [Kubernetes](k8s/) | A series of scenarios demonstrating Alloy setup using the Kubernetes monitoring Helm chart. See subdirectories for telemetry-specific examples. |

### OTel Engine Examples (Experimental)

Alloy v1.14+ includes an experimental **OTel Engine** that runs standard OpenTelemetry Collector YAML configs directly. These scenarios use `alloy otel` instead of River/HCL syntax. See the [OTel examples README](otel-examples/) for details.

| Scenario | Description |
| -------- | ----------- |
| [File log processing](otel-examples/filelog-processing/) | Collect and parse mixed-format log files using the OTel `filelog` receiver with operator chains. |
| [PII redaction](otel-examples/pii-redaction/) | Scrub credit cards, emails, and IPs from traces and logs using OTTL `replace_pattern`. |
| [Multi-tenant routing](otel-examples/routing-multi-tenant/) | Route logs to different Loki tenants based on resource attributes using fan-out and filter. |
| [Cost control](otel-examples/cost-control/) | Drop health checks, filter debug logs, and apply probabilistic sampling to cut telemetry volume. |
| [Resource enrichment](otel-examples/resource-enrichment/) | Auto-attach host, OS, and Docker metadata to all signals via `resourcedetection`. |
| [Count connector](otel-examples/count-connector/) | Derive request rate and error rate metrics from traces and logs using the `count` connector. |
| [OTTL transform cookbook](otel-examples/ottl-transform/) | A cookbook of OTTL patterns: JSON parsing, severity mapping, attribute promotion, truncation. |
| [Host metrics](otel-examples/host-metrics/) | Collect CPU, memory, disk, and network metrics using the `hostmetrics` receiver. |
| [Multi-pipeline fan-out](otel-examples/multi-pipeline-fanout/) | Send traces to two backends with different processing per destination. |
| [Kafka buffer](otel-examples/kafka-buffer/) | Buffer traces through Kafka for durability and backpressure handling. |

## Contributing

Contributions of scenarios or improvements to scenarios are welcome. You can contribute in several ways:

### Suggest a scenario

If you have an idea for a scenario but don't have time to implement it:

1. Open an [issue](https://github.com/grafana/alloy-scenarios/issues/new) with the label `scenario-suggestion`
2. Describe the scenario and what it would demonstrate
3. Explain why this would be valuable to the community
4. Outline any special requirements or considerations

### Contribute a scenario

If you'd like to contribute a complete scenario:

1. Fork this repository and create a branch
2. Create a directory in the root of this repository with a descriptive name for your scenario
3. Follow the [scenario template](#scenario-template) below
4. Submit a pull request with your scenario

### Improve a scenario

To improve a scenario:

1. Fork this repository and create a branch
2. Make your improvements to the scenario
3. Submit a pull request with a clear description of your changes

### Scenario template

When creating a scenario, include the following files:

- `docker-compose.yml` - Docker Compose file with the LGMT stack
- `config.alloy` - Alloy configuration file for the scenario
- `README.md` - Documentation explaining the scenario
- Any additional files needed for your scenario, such as scripts or data files

### Scenario checklist

Before submitting your scenario, ensure that you have:

- [ ] Created a directory in the root of this repository with a descriptive name
- [ ] Included a docker-compose.yml file with the necessary components, such as LGMT stack or subset
- [ ] Created a complete config.alloy file that demonstrates the monitoring approach
- [ ] Written a README.md with:
  - A clear description of what the scenario demonstrates
  - Prerequisites for running the demo
  - Step-by-step instructions for running the demo
  - Expected output and what to look for
  - Screenshots if applicable
  - Explanation of key configuration elements
- [ ] Added the scenario to the table in this README.md
- [ ] Ensured the scenario works with the centralized image management system
- [ ] Verified all components start correctly with `docker compose up -d`

### Best practices for scenarios

- Keep the scenario focused on demonstrating one concept
- Use clear, descriptive component and variable names
- Add comments to explain complex parts of your Alloy configuration
- Consider including a "Customizing" section in your README.md
- Provide sample queries for Grafana/Prometheus/Loki/Tempo that work with your scenario
- Use environment variables for versions and configurable parameters

## Get help

If you have questions about creating a scenario or need help with Alloy:

- Join the [Grafana Labs Community Forums](https://community.grafana.com/)
- Check the [Grafana Alloy documentation](https://grafana.com/docs/alloy/)

## License

This repository is licensed under the Apache License, Version 2.0. Refer to [LICENSE](LICENSE) for the full license text.
