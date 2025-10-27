<div align="center">
<img src="./img/banner.png" alt="Quest" width="300"/>
<h1> Grafana Alloy Scenarios </h1>
</div>

This repository contains scenarios that demonstrate how to use Grafana Alloy to monitor various data sources. Each scenario is a self-contained example which will include an `LGMT` stack (Loki, Grafana, Metrics, Tempo) and an Alloy configuration file.

## Running Scenarios

You can run any scenario in two ways:

1. **Traditional way**: Navigate to the scenario directory and run `docker compose up -d`
2. **Using centralized image management**: Run `./run-example.sh <scenario-directory>` from the root directory

The centralized approach allows you to manage all Docker image versions in a single `image-versions.env` file, making it easier to update images across all examples.

## Current Scenarios

| Scenario | Description |
| -------- | ------------ |
| [Docker Monitoring](docker-monitoring/) | Monitor Docker containers using Grafana Alloy. |
| [Syslog](syslog/) | Monitor non RFC5424 compliant syslog messages using rsyslog and Alloy. |
| [Logs Over TCP](logs-tcp/) | Send TCP logs to Alloy within a JSON format. |
| [Mail House](mail-house/) | Learn how to parse structured logs into Labels and Structured Metadata |
| [Monitor Windows](windows/) | Learn how to use Grafana Alloy to monitor system metrics and Event Logs|
| [Monitor Linux](linux/) | Learn how to use Grafana Alloy to monitor a Linux Server|
| [Kubernetes](k8s/) | A series of scenarios that demonstrate how to setup Alloy via the Kubernetes monitoring helm chart. Examples specific to each telemetry source are provided in the respective directories. |
| [Logs from File](logs-file/) | Monitor logs from a file using Grafana Alloy. |
| [OpenTelemetry Basic Tracing](otel-basic-tracing/) | Collect and visualize OpenTelemetry traces using Grafana Alloy and Tempo. |
| [OpenTelemetry Tracing Service Graph Generation](otel-tracing-service-graphs/) | Learn how to generate service graphs from OpenTelemetry traces using Grafana Alloy and Tempo. |
| [OpenTelemetry Tail sampling](otel-tail-sampling/) | Learn how to use OpenTelemetry tail sampling with Grafana Alloy and Tempo. |
| [Trace Deliverty](trace-delivery/) | A fun scenerio where the concepts of traces are taught through the supply chain of sofa creaton |
| [Game of Tracing](game-of-tracing/) | Learn traces through a strategic game |
| [Kafka](kafka/) | Learn how to use Grafana Alloy to monitor logs from Kafka. |
| [Popular Logging Frameworks](app-instrumentation/logging/popular-logging-frameworks/) | Learn how to use Grafana Alloy to parse logs from popular logging frameworks. |
| [Self-Monitoring](self-monitoring/) | Learn how to configure Grafana Alloy to monitor itself, collecting its own metrics and logs. |

## Contributing

We welcome contributions of new scenarios or improvements to existing ones! You can contribute in several ways:

### Suggesting New Scenarios

If you have an idea for a scenario but don't have time to implement it:

1. Open a [new issue](https://github.com/grafana/alloy-scenarios/issues/new) with the label `scenario-suggestion`
2. Describe the scenario and what it would demonstrate
3. Explain why this would be valuable to the community
4. Outline any special requirements or considerations

### Contributing a New Scenario

If you'd like to contribute a complete scenario:

1. Fork this repository and create a new branch
2. Create a new directory in the root of this repository with a descriptive name for your scenario
3. Follow the [scenario template](#scenario-template) below
4. Submit a pull request with your new scenario

### Improving Existing Scenarios

To improve an existing scenario:

1. Fork this repository and create a new branch
2. Make your improvements to the existing scenario
3. Submit a pull request with a clear description of your changes

### Scenario Template

When creating a new scenario, please include the following files:

- `docker-compose.yml` - Docker Compose file with the LGMT stack
- `config.alloy` - Alloy configuration file for the scenario
- `README.md` - Documentation explaining the scenario
- Any additional files needed for your scenario (scripts, data files, etc.)

You can use the `.cursor/docker-example.mdc` file as a template for new Docker-based scenarios.

### Scenario Checklist

Before submitting your scenario, please ensure:

- [ ] Created a new directory in the root of this repository with a descriptive name
- [ ] Included a docker-compose.yml file with the necessary components (LGMT stack or subset)
- [ ] Created a complete config.alloy file that demonstrates the monitoring approach
- [ ] Written a README.md with:
  - A clear description of what the scenario demonstrates
  - Prerequisites for running the demo
  - Step-by-step instructions for running the demo
  - Expected output and what to look for
  - Screenshots (if applicable)
  - Explanation of key configuration elements
- [ ] Added the scenario to the table in this README.md
- [ ] Ensured the scenario works with the centralized image management system
- [ ] Verified all components start correctly with `docker compose up -d`

### Best Practices for Scenarios

- Keep the scenario focused on demonstrating one concept
- Use clear, descriptive component and variable names
- Add comments to explain complex parts of your Alloy configuration
- Consider including a "Customizing" section in your README.md
- Provide sample queries for Grafana/Prometheus/Loki/Tempo that work with your scenario
- Use environment variables for versions and configurable parameters

## Getting Help

If you have questions about creating a scenario or need help with Alloy:

- Join the [Grafana Labs Community Forums](https://community.grafana.com/)
- Check the [Grafana Alloy documentation](https://grafana.com/docs/alloy/)
## License

This repository is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for the full license text.
