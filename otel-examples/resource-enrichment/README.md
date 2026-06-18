# Resource enrichment

This scenario shows how to enrich traces and metrics with host, OS, and container metadata in the Alloy OTel Engine without changing application code.
The demo app sends minimal resource attributes over OTLP.
Alloy applies `resourcedetection` and `resource` processors before export to Tempo and Prometheus.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo, 9090 for Prometheus, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+     +-------------+     +-------------+     +---------+
| demo-app |     |             |---->| Prometheus  |---->|         |
|          | OTLP| Alloy OTel  |     +-------------+     | Grafana |
|          |---->| Engine      |---->| Tempo       |---->|         |
+----------+     +-------------+     +-------------+     +---------+
```

- **demo-app**: Flask app on port 8080 that sends traces and metrics with only `service.name` and `service.version` set.
- **Alloy**: Runs the OTel Engine from `config-otel.yaml`. `resourcedetection` and `resource` processors enrich all signals before export. Mounts `/var/run/docker.sock` read-only for the Docker detector. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.
- **Prometheus**: Stores enriched metrics through its OTLP receiver at `http://prometheus:9090/api/v1/otlp`.
- **Tempo**: Stores enriched traces at `http://tempo:4317`.
- **Grafana**: Queries Prometheus and Tempo through provisioned data sources.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/resource-enrichment`
   - Deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/resource-enrichment && docker compose --env-file ../../image-versions.env up -d --build`

3. From the `resource-enrichment` directory, check that all containers are up: `docker compose ps`

   Expect `demo-app`, `alloy`, `prometheus`, `tempo`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: `/api/users`, `/api/items`, and `/health`.
- **Grafana** at http://localhost:3000: **Explore** with Prometheus and Tempo data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Prometheus** at http://localhost:9090: Enriched metrics from the OTLP receiver.
- **Tempo** at http://localhost:3200: Enriched trace storage.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### resourcedetection processor

Detectors: `env`, `system`, and `docker`.

- **`env`**: Reads `OTEL_RESOURCE_ATTRIBUTES` from the environment
- **`system`**: Discovers `host.name`, `os.type`, and `host.arch` with hostname from the OS
- **`docker`**: Discovers container metadata through the mounted Docker socket

Uses `override: false` so app-set attributes are not overwritten. Timeout is 5 seconds.

### resource processor

Adds static attributes with `upsert` action:

- `deployment.environment`: `demo`
- `service.namespace`: `otel-examples`

### Pipeline wiring

1. **Traces**: `otlp` → `resourcedetection` → `resource` → `batch` → `otlp/tempo` and `debug`
2. **Metrics**: `otlp` → `resourcedetection` → `resource` → `batch` → `otlphttp/prometheus`

The `debug` exporter on the trace pipeline prints detailed output to the Alloy container logs.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The background load generator calls `/api/users` or `/api/items` every two seconds.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Tempo** data source and run `{resource.service.name="enrichment-demo"}` in **Search**.
   Open a trace and expand resource attributes.
   Expect attributes the app did not set:

   - `host.name`: Collector container hostname
   - `os.type`: Detected OS
   - `host.arch`: CPU architecture
   - `deployment.environment`: `demo`
   - `service.namespace`: `otel-examples`

2. Select the **Prometheus** data source and run:

   - `app_requests_total`: Request counter with enriched resource labels such as `deployment_environment` and `service_namespace`

3. Inspect debug exporter output: `docker compose logs alloy`

   Look for `debug` exporter output showing the full enriched resource.

4. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Add detectors**: Extend the `detectors` list under `resourcedetection` in `config-otel.yaml`.
- **Add resource attributes**: Edit the `resource` processor attributes in `config-otel.yaml`.
- **Remove Docker detection**: Drop the Docker socket mount from `docker-compose.yml` and remove the `docker` detector from `config-otel.yaml`.

## Troubleshoot common problems

Covers startup failures, missing telemetry, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `prometheus`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No traces or metrics in Tempo or Prometheus

Wait for the demo app load generator to start. It sleeps five seconds after startup.
In Grafana, search Tempo for `{resource.service.name="enrichment-demo"}` and Prometheus for `app_requests_total`.
Check Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 8080, 3000, 3200, 9090, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/resource-enrichment` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry resourcedetection processor: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/resourcedetectionprocessor
- More examples: https://github.com/grafana/alloy-scenarios
