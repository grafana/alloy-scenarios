# Syslog via rsyslog and Alloy

The `loki.source.syslog` component in Grafana Alloy expects RFC5424 syslog.
Legacy and non-RFC5424 formats need normalization before Alloy can ingest them.
This scenario puts rsyslog in front of Alloy to receive syslog on port 514, reformat messages with `RSYSLOG_SyslogProtocol23Format`, and forward them to Alloy over TCP.
Alloy writes the logs to Loki, and Grafana queries them through a provisioned data source.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 514, 3000, 3100, 51893, 51898, and 12345 free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------------+  UDP   +---------+  TCP   +-------+       +------+       +---------+
| syslog-     |------->| rsyslog |------->| Alloy |------->| Loki |------->| Grafana |
| simulator   |        |  :514   | :51893 |       |        |      |        |         |
+-------------+        +---------+        +-------+        +------+        +---------+
```

- **syslog-simulator**: Python script that sends syslog messages to rsyslog on UDP port 514.
- **rsyslog**: Receives syslog on port 514 and forwards all messages to Alloy on TCP port 51893 using the `RSYSLOG_SyslogProtocol23Format` template.
- **Alloy**: Runs `config.alloy`.
  `loki.source.syslog` listens on TCP port 51893 and UDP port 51898, then forwards logs to Loki.
  Live debugging is enabled.
- **Loki**: Stores logs at `http://loki:3100/loki/api/v1/push`.
- **Grafana**: Queries Loki through a provisioned data source with anonymous admin access enabled.

In production, point your network devices or hosts at rsyslog instead of the simulator.
rsyslog normalizes non-RFC5424 messages before Alloy ingests them.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/syslog`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh syslog`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `syslog` directory, check that all containers are up: `docker compose ps`

   Expect `rsyslog`, `syslog-simulator`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Loki data source.
  You don't need to log in.
- **Alloy UI** at http://localhost:12345: Component graph for `loki.source.syslog` and `loki.write`.
  Live debugging is enabled in `config.alloy`.
- **Loki** at http://localhost:3100: Syslog logs from Alloy.
- **rsyslog** on UDP and TCP port 514: Syslog intake from the simulator or external senders.

## Understand the Alloy pipeline

`config.alloy` defines the pipeline:

1. **`loki.source.syslog`**: Listens on TCP port 51893 and UDP port 51898.
   Each listener adds `component=loki.source.syslog` and a `protocol` label.
2. **`loki.write`**: Sends logs to `http://loki:3100/loki/api/v1/push`.

rsyslog forwards normalized syslog to the TCP listener on port 51893.
The UDP listener on port 51898 is available for direct RFC5424 syslog sends to Alloy.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki** data source and run these LogQL queries:

   - `{component="loki.source.syslog"}`: All syslog listener logs
   - `{protocol="tcp"}`: Logs forwarded from rsyslog over TCP
   - `{protocol="udp"}`: Logs received on the UDP listener on port 51898

2. Open the Alloy UI at http://localhost:12345.

   Navigate to the component graph to verify the path from `loki.source.syslog` to `loki.write`.
   Use live debugging to inspect log entries flowing through each component.

3. Watch the simulator output: `docker compose logs -f syslog-simulator`

   The script sends a new message every 3 to 8 seconds with application name `MyApp`.

## Customize the scenario

- **Change rsyslog forwarding**: Edit `rsyslog.conf` to adjust intake ports or the Alloy target address.
- **Change Alloy listeners**: Edit the `listener` blocks under `loki.source.syslog` in `config.alloy` and update the matching port maps in `docker-compose.yml`.
- **Point at another Loki**: Update the push URL in `loki.write` in `config.alloy`.

## Troubleshoot common problems

This section covers startup failures, missing logs, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `rsyslog`, `alloy`, or `loki`.

### No syslog logs in Loki

Check that rsyslog can reach Alloy on TCP port 51893: `docker compose logs rsyslog`
Open the Alloy UI at http://localhost:12345 and verify that `loki.source.syslog` is receiving entries on the TCP listener.
In Grafana **Explore**, run `{protocol="tcp"}` against the **Loki** data source.

### Port conflicts with other services

Ports 514, 3000, 3100, 51893, 51898, and 12345 must be free before you start the stack.
Port 514 is the standard syslog port and often conflicts with a host rsyslog service.
If another service uses one of these ports, edit the port map in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `syslog` directory.

## Next steps

- Alloy `loki.source.syslog` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.syslog/
- rsyslog forwarding documentation: https://www.rsyslog.com/doc/
- More examples: https://github.com/grafana/alloy-scenarios
