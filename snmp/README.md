# Monitor SNMP devices with Grafana Alloy

This scenario shows how to use Grafana Alloy to collect metrics from a network device over SNMP and forward them to Prometheus.
A local `snmpd` container runs a net-snmp agent that answers SNMPv2c queries, so the demo works end to end without any real hardware.
Alloy uses `prometheus.exporter.snmp` to walk the standard MIB-II interfaces table, `prometheus.scrape` to collect the result every 30 seconds, and `prometheus.remote_write` to send the samples to Prometheus. Grafana queries Prometheus through a provisioned data source.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy free on the host.

The `snmpd` service builds locally from the official Debian image with net-snmp installed.
Its SNMP endpoint listens on UDP 161 inside the Compose network only, so it isn't published to the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

This scenario collects metrics only. SNMP polling flows from the agent through Alloy to Prometheus.

```text
+-------+     +-------+     +------------+     +---------+
| snmpd |---->| Alloy |---->| Prometheus |---->| Grafana |
+-------+     +-------+     +------------+     +---------+
```

- **snmpd**: A net-snmp agent that acts as the monitored device. It answers SNMPv2c queries with the read-only community `public` and exposes the standard MIB-II interfaces table.
- **Alloy**: Polls the agent with `prometheus.exporter.snmp`, relabels the target, scrapes the exporter, and remote-writes the samples to Prometheus. Live debugging is enabled.
- **Prometheus**: Stores the SNMP metrics through its remote write receiver at `http://prometheus:9090/api/v1/write`.
- **Grafana**: Queries Prometheus through a provisioned data source with anonymous admin access enabled.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/snmp`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Prometheus, Alloy, and the Debian base image.

   - Deploy the scenario: `./run-example.sh snmp`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `snmp` directory, check that all containers are up: `docker compose ps`

   Expect `snmpd`, `alloy`, `prometheus`, and `grafana`.
   The first deploy builds the `snmpd` image, so it can take a moment before every container is running.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Prometheus data source, with no login required.
- **Alloy UI** at http://localhost:12345: Component graph for `prometheus.exporter.snmp`, `prometheus.scrape`, and `prometheus.remote_write`, plus live debug views.
- **Prometheus** at http://localhost:9090: SNMP metrics from remote write.

## Understand the configuration

The `config.alloy` pipeline has four components: `prometheus.exporter.snmp.snmp_exporter`, `discovery.relabel.snmp_targets`, `prometheus.scrape.snmp_targets`, and `prometheus.remote_write.remote`.

1. **`prometheus.exporter.snmp.snmp_exporter`**: Loads the SNMP module definitions from `config_file = "/etc/alloy/snmp.yml"`, which `docker-compose.yml` mounts into the Alloy container. Its `target "snmpd"` block polls the `snmpd` service at `address = "snmpd"` with the `if_mib` module, the `public_v2` auth profile, and the `default` walk parameters. The `walk_param "default"` block sets `retries = "2"` and `timeout = "30s"`, and the target attaches a `device = "snmpd"` label.
2. **`discovery.relabel.snmp_targets`**: Takes the exporter targets and sets the `job` label to `snmp`.
3. **`prometheus.scrape.snmp_targets`**: Scrapes the relabeled target every 30 seconds and forwards the samples to `prometheus.remote_write.remote`.
4. **`prometheus.remote_write.remote`**: Pushes the metrics to Prometheus at `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

### Metrics collected

The `snmp.yml` file defines what Alloy collects. The `public_v2` auth profile uses SNMPv2c with the community string `public`. The `if_mib` module walks the MIB-II interfaces group at OID `1.3.6.1.2.1.2`, which every net-snmp agent answers without vendor-specific MIBs. It exports these metrics, indexed by `ifIndex` and enriched with an `ifDescr` label through a lookup:

- **ifNumber**: The number of network interfaces on the system.
- **ifOperStatus**: The current operational state of each interface, where `1` means up and `2` means down.
- **ifInOctets**: The total octets received on each interface.
- **ifOutOctets**: The total octets transmitted on each interface.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Prometheus** data source and run these PromQL queries:

   - `up{job="snmp"}`: A value of `1` confirms that Alloy reached the agent and the scrape succeeded.
   - `ifOperStatus`: The operational state of every interface, each carrying an `ifDescr` label such as `eth0` or `lo` from the lookup in `snmp.yml`.
   - `rate(ifInOctets[5m])`: Receive throughput per interface. Use `rate(ifOutOctets[5m])` for transmit throughput.

2. Open the Alloy UI at http://localhost:12345.

   Navigate to the component graph to verify `prometheus.exporter.snmp` → `prometheus.scrape` → `prometheus.remote_write`.
   Select `prometheus.exporter.snmp.snmp_exporter` and use live debug to watch each SNMP walk.

## Customize the scenario

- **Poll a real device**: Change `address` in the `target "snmpd"` block in `config.alloy` to your device address, set the community string in the `public_v2` auth in `snmp.yml`, and remove the `snmpd` service from `docker-compose.yml`.
- **Collect more metrics**: Add OIDs to the `walk` list and matching entries to the `metrics` list in `snmp.yml`, then reference the module with `module` in the target block in `config.alloy`.
- **Use SNMPv3**: Add an auth profile to `snmp.yml` with `version: 3` and the relevant security settings, then point the target `auth` argument at it.
- **Adjust the poll rate**: Change `scrape_interval` in `prometheus.scrape.snmp_targets`, or tune `retries` and `timeout` in the `walk_param "default"` block in `config.alloy`.
- **Point at another Prometheus**: Update the remote write URL in `prometheus.remote_write.remote` in `config.alloy`.

## Troubleshoot common problems

This section covers startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps -a` to check the status of each container.
If a container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `snmpd` or `alloy`.
For Alloy, the most common cause is a syntax error in `config.alloy` or a `config_file` path that doesn't match where `docker-compose.yml` mounts `snmp.yml`.

### No SNMP metrics in Prometheus

Open the Alloy UI at http://localhost:12345 and check that all components show a healthy status.
Select `prometheus.exporter.snmp.snmp_exporter` and use live debug to check that each SNMP walk returns data.
If the walk reports a connection error, check that the `snmpd` container is running with `docker compose ps`.
Alloy resolves the `snmpd` name over the Compose network, so the agent must be up for the poll to succeed.
In Grafana **Explore**, select the **Prometheus** data source and run `up{job="snmp"}` to check that the scrape target is up.

### Port conflicts with other services

Ports 3000 for Grafana, 9090 for Prometheus, and 12345 for Alloy must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `snmp` directory.

## Next steps

- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `prometheus.exporter.snmp` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.snmp/
- snmp_exporter module format: https://github.com/prometheus/snmp_exporter
- More examples: https://github.com/grafana/alloy-scenarios
