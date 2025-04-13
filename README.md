<div align="center">
<img src="./img/banner.png" alt="Quest" width="300"/>
<h1> Grafana Alloy Scenarios </h1>
</div>

This repository contains scenarios that demonstrate how to use Grafana Alloy to monitor various data sources. Each scenario is a self-contained example which will include an `LGMT` stack (Loki, Grafana, Metrics, Tempo) and an Alloy configuration file.

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

## Contributing

If you have a scenario you would like to contribute, please open a pull request with the following changes:

1. Create a new directory in the root of this repository with the name of your scenario.
2. Add a README.md file to the directory with the following sections:
   - Description: A brief description of the scenario.
   - Running the Demo: Instructions on how to run the demo.
3. Add the scenario to the table in the `README.md` file with a link to the scenario's README.


### Example Checklist

When contributing a new scenario, please ensure the following checklist is complete:

- [ ] Created a new directory in the root of this repository with the name of the scenario.
- [ ] A docker compose file including Loki, Grafana, Metrics, Tempo (LGMT) stack. Part of the stack can be omitted if not needed.
- [ ] A complete config.alloy file that demonstrates how to monitor the data source.
- [ ] A README.md file with the following sections:
  - Description: A brief description of the scenario.
  - Running the Demo: Instructions on how to run the demo.
- [ ] Added the scenario to the table in the `README.md` file with a link to the scenario's README.



## License

This repository is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for the full license text.
