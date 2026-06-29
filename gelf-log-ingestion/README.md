# GELF log ingestion

This scenario shows how to ingest GELF logs with `loki.source.gelf`.
GELF is the Graylog Extended Log Format for structured log messages over UDP.
A Python app sends GELF messages with pygelf, Alloy relabels GELF metadata into Loki labels, and Grafana queries the stored log lines.
The `config.alloy` file defines the pipeline.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 12345 for the Alloy UI, and 12201 for GELF UDP ingestion free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

The `gelf-logger` service installs pygelf at startup and sends structured messages to Alloy over UDP.
Alloy promotes GELF host, level, and facility fields to Loki labels before writing to Loki.

```text
+-------------+     UDP :12201     +-------+     +------+     +---------+
| gelf-logger |------------------->| Alloy |---->| Loki |---->| Grafana |
| Python app  |                    |       |     |      |     |         |
+-------------+                    +-------+     +------+     +---------+
```

- **gelf-logger**: Python app that sends random structured log lines every one to three seconds with pygelf.
- **Alloy**: Listens for GELF on UDP port 12201, relabels metadata, and forwards log lines to Loki.
- **Loki**: Stores the GELF log entries.
- **Grafana**: Queries logs through a provisioned Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/gelf-log-ingestion`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh gelf-log-ingestion`

3. Check that all containers are up: `cd alloy-scenarios/gelf-log-ingestion && docker compose ps`

   Expect `gelf-logger`, `alloy`, `loki`, and `grafana`.
   The `gelf-logger` container installs pygelf on first start before it begins sending messages.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.

## Understand the configuration

The `config.alloy` pipeline has three components:

1. **`loki.source.gelf "default"`**: Listens on `0.0.0.0:12201` for GELF UDP messages and forwards entries to `loki.relabel.gelf`.
2. **`loki.relabel "gelf"`**: Promotes `__gelf_message_host`, `__gelf_message_level`, and `__gelf_message_facility` to `host`, `level`, and `facility` labels, then forwards to `loki.write.local`.
3. **`loki.write "local"`**: Pushes log lines to Loki at `http://loki:3100/loki/api/v1/push`.

The demo app in `app/main.py` sends logs to `alloy:12201` with structured fields such as `user_id`, `order_id`, and `gateway`.
The Alloy container runs with `--stability.level=experimental` because `loki.source.gelf` requires experimental stability.
`livedebugging` is enabled.

## GELF level mapping

GELF uses syslog severity levels from 0 to 7:

| GELF level | Syslog severity |
|------------|-----------------|
| 0          | Emergency       |
| 1          | Alert           |
| 2          | Critical        |
| 3          | Error           |
| 4          | Warning         |
| 5          | Notice          |
| 6          | Informational   |
| 7          | Debug           |

## Try it out

1. Open Grafana **Explore**, select the **Loki** data source, and try these LogQL queries:

   - `{job="loki.source.gelf.default"}`: all GELF logs received by Alloy
   - `{level="6"}`: informational messages

2. Open the Alloy UI at http://localhost:12345 and use live debug on `loki.source.gelf.default` to watch GELF messages arrive from the logger.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `loki.source.gelf` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.gelf/
- Log secret filtering scenario: [../log-secret-filtering/](../log-secret-filtering/)
