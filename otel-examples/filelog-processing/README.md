# Filelog processing

This scenario shows how to ingest and parse mixed-format log files with the OTel filelog receiver in the Alloy OTel Engine.
A log generator writes JSON and plaintext lines to a shared volume at `/var/log/app/demo.log`.
Alloy reads those files with operator chains, maps severity levels, tags records with `service.name`, and ships them to Loki over OTLP HTTP.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 8888 for the OTel Engine HTTP server, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+---------------+       +-----------------+       +------+       +---------+
| log-generator | file  | Alloy OTel      |       | Loki |       | Grafana |
|               |------>| Engine          |------>|      |------>|         |
+---------------+       +-----------------+       +------+       +---------+
```

- **log-generator**: Python script that appends JSON and plaintext log lines to `/var/log/app/demo.log` every two seconds.
- **Alloy**: Runs the OTel Engine from `config-otel.yaml`. The filelog receiver tails files from the shared `app-logs` volume. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.
- **Loki**: Stores parsed logs through its OTLP HTTP endpoint at `http://loki:3100/otlp`.
- **Grafana**: Queries Loki through a provisioned data source.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/filelog-processing`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/filelog-processing && docker compose --env-file ../../image-versions.env up -d`

3. From the `filelog-processing` directory, check that all containers are up: `docker compose ps`

   Expect `log-generator`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Loki** at http://localhost:3100: Log backend API.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### Filelog receiver

The `filelog` receiver includes `/var/log/app/*.log` and runs a chain of operators on each line:

1. **`json_parser`**: Runs when the line starts with `{`. Parses the body into attributes and reads the timestamp from `attributes.timestamp` using layout `%Y-%m-%dT%H:%M:%S.%fZ`.
2. **`regex_parser`**: Runs when the line starts with a date pattern. Captures `timestamp`, `level`, and `message` from plaintext lines using layout `%Y-%m-%d %H:%M:%S,%f`.
3. **`severity_parser`**: Maps the parsed `level` attribute to OTel severity when `attributes.level` is set.
4. **`add`**: Sets `resource["service.name"]` to `log-demo`.

### Log pipeline

**Logs**: `filelog` → `batch` → `otlphttp/loki`

The batch processor uses a 2s timeout and a batch size of 256 records.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The log generator alternates between JSON and plaintext formats with random DEBUG, INFO, WARN, and ERROR levels.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki** data source and run these LogQL queries:

   - `{service_name="log-demo"}`: All ingested lines
   - `{service_name="log-demo"} | json`: JSON lines with parsed fields
   - `{service_name="log-demo"} |= "ERROR"`: Error lines only

   Both JSON and plaintext lines appear in Loki with severity levels and timestamps parsed from the source format.

2. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Change log formats**: Edit `app/generate_logs.py` or add new operator branches in `config-otel.yaml`.
- **Add files to tail**: Extend the `include` list under `receivers.filelog` in `config-otel.yaml`.
- **Change the service name**: Update the `add` operator value and the LogQL queries in this README.

## Troubleshoot common problems

Covers startup failures, missing logs, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `log-generator`, `alloy`, or `loki`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No logs in Loki

Wait a few seconds for the log generator to write lines to the shared volume.
In Grafana, select the **Loki** data source in **Explore** and run `{service_name="log-demo"}`.
Check the generator with `docker compose logs log-generator`.
Check Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 3000, 3100, 8888, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/filelog-processing` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry filelog receiver: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/filelogreceiver
- More examples: https://github.com/grafana/alloy-scenarios
