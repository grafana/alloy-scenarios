# SNMP metrics

This scenario collects metrics from SNMP network devices with `prometheus.exporter.snmp` in Grafana Alloy.
Alloy polls a target using a Cisco module defined in `snmp.yml`, scrapes the exporter every 30 seconds, and remote-writes metrics to Prometheus.
Grafana queries Prometheus through a provisioned data source.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.
- An SNMP device reachable from the Alloy container at the hostname configured in `config.alloy`.
  The checked-in configuration uses the address `snmpd`, but `docker-compose.yml` does not define an SNMP service.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+--------+  SNMP  +-------+       +-------------+       +---------+
| device |<------>| Alloy |       | Prometheus  |       | Grafana |
| snmpd  |        |       |------>|             |------>|         |
+--------+        +-------+       +-------------+       +---------+
```

- **SNMP device**: Network hardware polled over SNMP.
  `config.alloy` points target `tm` at `snmpd` with module `CISCO` from `snmp.yml`.
- **Alloy**: Runs `config.alloy`.
  `prometheus.exporter.snmp` polls the device, `prometheus.scrape` collects metrics every 30 seconds, and `prometheus.remote_write` sends them to Prometheus.
  Live debugging is enabled.
- **Prometheus**: Stores metrics through its remote write receiver at `http://prometheus:9090/api/v1/write`.
- **Grafana**: Queries Prometheus through a provisioned data source with anonymous admin access enabled.

Loki also runs in this stack and Grafana provisions a Loki data source, but the checked-in Alloy configuration sends metrics only.
It does not push logs to Loki.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/snmp`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh snmp`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `snmp` directory, check that all containers are up: `docker compose ps`

   Expect `alloy`, `prometheus`, `grafana`, and `loki`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Prometheus data source.
  You don't need to log in.
- **Alloy UI** at http://localhost:12345: Component graph for `prometheus.exporter.snmp`, `prometheus.scrape`, and `prometheus.remote_write`.
  Live debugging is enabled in `config.alloy`.
- **Prometheus** at http://localhost:9090: SNMP metrics from remote write.
- **Loki** at http://localhost:3100: Deployed in this stack, but the checked-in Alloy configuration does not send logs to it.

## Understand the Alloy pipeline

`config.alloy` defines the pipeline:

1. **`prometheus.exporter.snmp`**: Polls SNMP target `tm` at `snmpd` with module `CISCO` from `snmp.yml`.
   The target adds static label `ilo_node=switch`.
   Walk settings come from the `walk_param` block named `cisco` with 2 retries and a 30 second timeout.
2. **`discovery.relabel`**: Sets the `job` label to `smpt`.
3. **`prometheus.scrape`**: Scrapes the exporter every 30 seconds.
4. **`prometheus.remote_write`**: Sends metrics to `http://prometheus:9090/api/v1/write`.

### Metrics collected

The `CISCO` module in `snmp.yml` exports:

- **ifInterface**: Gauge for each interface from OID `1.4.6.1.4.3.9.9.244.1.2.1.1.7`

Authentication profiles `public_v1` and `public_v2` are defined in `snmp.yml` with a placeholder community value.
The checked-in target block does not set an `auth` value.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Prometheus** data source and run these PromQL queries:

   - `{job="smpt"}`: All SNMP metrics from this scenario
   - `ifInterface`: Cisco interface gauge from the `CISCO` module
   - `{ilo_node="switch"}`: Metrics from target `tm`

2. Open the Alloy UI at http://localhost:12345.

   Navigate to the component graph to verify `prometheus.exporter.snmp` → `prometheus.scrape` → `prometheus.remote_write`.
   Use live debugging to inspect metrics flowing through each component.

## Customize the scenario

- **Add SNMP targets**: Add `target` blocks under `prometheus.exporter.snmp` in `config.alloy`.
- **Change modules or OIDs**: Edit the `modules` section in `snmp.yml`.
- **Set SNMP authentication**: Replace the `<community>` placeholder in `snmp.yml` and set `auth` on each target in `config.alloy`.
- **Point at another Prometheus**: Update the remote write URL in `prometheus.remote_write` in `config.alloy`.

## Troubleshoot common problems

This section covers startup failures, missing metrics, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `alloy`, `prometheus`, or `grafana`.

### No SNMP metrics in Prometheus

Before you start the stack, check these configuration mismatches in the checked-in files:

- `config.alloy` sets `config_file = "/etc/snmp/snmp.yml"`, but `docker-compose.yml` mounts `snmp.yml` at `/etc/alloy/snmp.yml`.
  Update one path so they match.
- Target `tm` uses `walk_params = "Cisco"`, but the `walk_param` block is named `cisco`.
  The names must match exactly.
- `docker-compose.yml` does not include an SNMP agent or device at hostname `snmpd`.
  Add an SNMP service to the compose file or change `address` to a reachable host on your network.

Open the Alloy UI at http://localhost:12345 and check that `prometheus.exporter.snmp` targets are up.
In Grafana **Explore**, select the **Prometheus** data source and run `{job="smpt"}`.

### Port conflicts with other services

Ports 3000, 3100, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `snmp` directory.

## Next steps

- Alloy `prometheus.exporter.snmp` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.snmp/
- snmp_exporter module format: https://github.com/prometheus/snmp_exporter
- More examples: https://github.com/grafana/alloy-scenarios
