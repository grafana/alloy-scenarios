# Routing multi-tenant

This scenario shows how to route logs from different tenants into separate Loki organizations with the OTel forward connector and filter processor in the Alloy OTel Engine.
A log generator sends OTLP logs with a `tenant` resource attribute for `team-a` and `team-b`.
Alloy fans out from one intake pipeline into per-tenant pipelines that filter, enrich, and export with the correct `X-Scope-OrgID` header.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+--------------+       +-----------------+       +----------------+       +---------+
| log-generator| OTLP  | Alloy OTel      | team-a| Loki (team-a)  |       |         |
|              |------>| intake pipeline |------>|                |------>| Grafana |
+--------------+       +--------+--------+       +----------------+       |         |
                               | team-b  +------------------+             |         |
                               +-------->| Loki (team-b)    |------------>|         |
                                         +------------------+             +---------+
```

- **log-generator**: Python script that sends OTLP logs for `team-a` and `team-b` every two seconds.
- **Alloy intake pipeline**: `logs/intake` in `config-otel.yaml`. Receives OTLP and exports to `forward/team-a` and `forward/team-b`.
- **Alloy tenant pipelines**: `logs/team-a` and `logs/team-b` filter by tenant, add a `team` resource attribute, and export to Loki with `X-Scope-OrgID`.
- **Loki**: Single Loki instance with `auth_enabled: true`. Tenant isolation uses the `X-Scope-OrgID` header on ingest and query.
- **Grafana**: **Loki (team-a)** and **Loki (team-b)** data sources send the matching org header on each query.

The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/routing-multi-tenant`
   - Deploy the scenario: `docker compose up -d`

   The log generator sends logs for both tenants every two seconds.

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/routing-multi-tenant && docker compose --env-file ../../image-versions.env up -d`

   The log generator sends logs for both tenants every two seconds.

3. From the `routing-multi-tenant` directory, check that all containers are up: `docker compose ps`

   Expect `log-generator`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with **Loki (team-a)** and **Loki (team-b)** data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Loki** at http://localhost:3100: Multi-tenant log backend API.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### Forward connectors

- **`forward/team-a`**: Duplicates intake logs into the team-a pipeline
- **`forward/team-b`**: Duplicates intake logs into the team-b pipeline

### Per-tenant processors

**Team A (`logs/team-a`):**

1. **`filter/team-a`**: Drops logs where `resource.attributes["tenant"] != "team-a"`
2. **`resource/team-a`**: Sets `team=team-a`
3. **`batch`**: Batches before export
4. **`otlphttp/loki-team-a`**: Exports with `X-Scope-OrgID: team-a`

**Team B (`logs/team-b`):**

1. **`filter/team-b`**: Drops logs where `resource.attributes["tenant"] != "team-b"`
2. **`resource/team-b`**: Sets `team=team-b`
3. **`batch`**: Batches before export
4. **`otlphttp/loki-team-b`**: Exports with `X-Scope-OrgID: team-b`

### Pipeline wiring

1. **Intake — `logs/intake`**: `otlp` → `forward/team-a` and `forward/team-b`
2. **Team A — `logs/team-a`**: `forward/team-a` → `filter/team-a` → `resource/team-a` → `batch` → `otlphttp/loki-team-a`
3. **Team B — `logs/team-b`**: `forward/team-b` → `filter/team-b` → `resource/team-b` → `batch` → `otlphttp/loki-team-b`

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki (team-a)** data source and run:

   - `{service_name="frontend-service"}`: Logs from team-a only

2. Switch to the **Loki (team-b)** data source and run:

   - `{service_name="order-service"}`: Logs from team-b only

3. Verify isolation by confirming team-a's data source does not show team-b logs and vice versa.
   Loki enforces this through the multi-tenant `X-Scope-OrgID` header on ingest and query.

4. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Add a tenant**: Add a forward connector, filter, resource processor, Loki exporter, and pipeline in `config-otel.yaml`. Add a matching Grafana data source in `docker-compose.yml`.
- **Change filter logic**: Edit the `filter/team-a` or `filter/team-b` conditions in `config-otel.yaml`.
- **Change tenant labels**: Update `resource/team-a` and `resource/team-b` attribute values in `config-otel.yaml`.

## Troubleshoot common problems

Covers startup failures, missing logs, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `log-generator`, `alloy`, or `loki`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No logs in Loki for one tenant

Wait a few seconds for the log generator to start. It sleeps three seconds after startup.
In Grafana, query **Loki (team-a)** for `{service_name="frontend-service"}` and **Loki (team-b)** for `{service_name="order-service"}`.
Check the generator with `docker compose logs log-generator` and Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 3000, 3100, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/routing-multi-tenant` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry forward connector: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/forwardconnector
- More examples: https://github.com/grafana/alloy-scenarios
