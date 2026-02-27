<p align="center">
  <img src="./img/banner.png" alt="Grafana Alloy Scenarios Banner" width="300"/>
</p>

# Grafana Alloy Scenarios

This repository contains scenarios that demonstrate how to use Alloy to monitor various data sources. Each scenario is a self-contained example that includes a Loki, Grafana, Mimir, and Tempo (LGMT) stack and an Alloy configuration file.

## Run scenarios

You can run any scenario in two ways:

1. **Traditional way**: Navigate to the scenario directory and run `docker compose up -d`
2. **Using centralized image management**: Run `./run-example.sh <scenario-directory>` from the root directory

The centralized approach allows you to manage all Docker image versions in a single `image-versions.env` file, making it easier to update images across all examples.

## Current Scenarios

| Scenario | Description |
| -------- | ------------ |
| [Distributed tracing](trace-delivery/) | Learn distributed tracing through a sofa delivery workflow from order to doorstep. |
| [Docker monitoring](docker-monitoring/) | Monitor Docker containers using Alloy. |
| [Game of tracing](game-of-tracing/) | An interactive strategy game teaching distributed tracing, sampling, and service graphs. |
| [Kafka logs](kafka/) | Learn how to use Alloy to monitor logs from Kafka. |
| [Kubernetes](k8s/) | A series of scenarios that demonstrate how to set up Alloy using the Kubernetes monitoring Helm chart. Refer to the respective directories for examples specific to each telemetry source. |
| [Log routing](routing/) | Route logs from multiple sources to different Loki tenants based on log content and origin. |
| [Logs from file](logs-file/) | Monitor logs from a file using Alloy. |
| [Logs over TCP](logs-tcp/) | Send TCP logs to Alloy within a JSON format. |
| [Monitor Linux](linux/) | Learn how to use Alloy to monitor a Linux server. |
| [Monitor Windows](windows/) | Learn how to use Alloy to monitor system metrics and Event Logs. |
| [OpenTelemetry basic tracing](otel-basic-tracing/) | Collect and visualize OpenTelemetry traces using Alloy and Tempo. |
| [OpenTelemetry service graph generation](otel-tracing-service-graphs/) | Generate service graphs using the Alloy `servicegraph` connector. |
| [OpenTelemetry tail sampling](otel-tail-sampling/) | Learn how to use OpenTelemetry tail sampling with Alloy and Tempo. |
| [Popular logging frameworks](app-instrumentation/logging/popular-logging-frameworks/) | Learn how to use Alloy to parse logs from popular logging frameworks. |
| [Self-monitoring](self-monitoring/) | Learn how to configure Alloy to monitor itself, collecting its own metrics and logs. |
| [SNMP monitoring](snmp/) | Monitor Simple Network Management Protocol (SNMP) devices using the Alloy SNMP exporter. |
| [Structured log parsing](mail-house/) | Learn how to parse structured logs into labels and structured metadata. |
| [Syslog monitoring](syslog/) | Monitor non RFC5424 compliant syslog messages using `rsyslog` and Alloy. |

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
