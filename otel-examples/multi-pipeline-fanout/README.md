# Multi-pipeline fan out

This scenario shows how to fan out the same traces to multiple backends with different processing per destination using the OTel forward connector.
The demo app sends traces to the `traces/intake` pipeline in Alloy.
Full-fidelity traces go to Tempo Primary while a copy routes through `forward/sampled` into the `traces/sampled` pipeline for 10% sampling and attribute stripping before export to Tempo Secondary.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 8080 for the demo app, 3000 for Grafana, 3200 for Tempo Primary, 3201 for Tempo Secondary, 9090 for Prometheus, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+       +-----------------+       +----------------+       +---------+
| demo-app | OTLP  | Alloy OTel      | full  | Tempo Primary  |       |         |
|          |------>| intake pipeline |------>|                |------>| Grafana |
+----------+       +--------+--------+       +----------------+       |         |
                            | sampled +------------------+            |         |
                            +-------->| Tempo Secondary  |----------->|         |
                                      +------------------+            +---------+
```

- **demo-app**: Flask app on port 8080 that sends HTTP traces with large user agent, cookie, and request body attributes.
- **Alloy intake pipeline**: `traces/intake` in `config-otel.yaml`. Receives OTLP, batches spans, and exports to Tempo Primary and `forward/sampled`.
- **forward/sampled**: Duplicates trace data from the intake pipeline into the sampled pipeline.
- **Alloy sampled pipeline**: `traces/sampled` in `config-otel.yaml`. Applies 10% probabilistic sampling, strips selected attributes, and exports to Tempo Secondary.
- **Tempo Primary**: Stores full-fidelity traces at `http://tempo:4317`.
- **Tempo Secondary**: Stores sampled and stripped traces at `http://tempo-secondary:4317`.
- **Grafana**: Queries **Tempo Primary** and **Tempo Secondary** through provisioned data sources.

The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/multi-pipeline-fanout`
   - Deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/multi-pipeline-fanout && docker compose --env-file ../../image-versions.env up -d --build`

3. From the `multi-pipeline-fanout` directory, check that all containers are up: `docker compose ps`

   Expect `demo-app`, `alloy`, `tempo`, `tempo-secondary`, `prometheus`, and `grafana`.

## Explore the services

- **Demo app** at http://localhost:8080: `/api/orders` and `/api/health`.
- **Grafana** at http://localhost:3000: **Explore** with **Tempo Primary**, **Tempo Secondary**, and Prometheus data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Tempo Primary** at http://localhost:3200: Full-fidelity trace storage.
- **Tempo Secondary** at http://localhost:3201: Sampled trace storage.
- **Prometheus** at http://localhost:9090: Provisioned for Tempo service map linking.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### Forward connector

`forward/sampled` bridges the intake and sampled pipelines. It acts as an exporter in `traces/intake` and a receiver in `traces/sampled`.

### Sampled pipeline processors

1. **`probabilistic_sampler`**: Keeps 10% of traces forwarded from the intake pipeline.
2. **`transform/strip`**: Deletes `http.request.header.user_agent`, `http.request.header.cookie`, and `http.request.body`, then truncates remaining span attributes to 128 characters.

### Pipeline wiring

1. **Intake — `traces/intake`**: `otlp` → `batch` → `otlp/tempo-primary` and `forward/sampled`
2. **Sampled — `traces/sampled`**: `forward/sampled` → `probabilistic_sampler` → `transform/strip` → `batch` → `otlp/tempo-secondary`

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The background load generator calls `/api/orders` and `/api/health` every 0.5 to 2 seconds with varied user agent and cookie headers.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Tempo Primary** data source and run `{resource.service.name="fanout-demo-app"}` in **Search**.
   Pick a trace and note full `http.request.header.user_agent`, `http.request.header.cookie`, and `http.request.body` values on POST spans.

2. Switch to the **Tempo Secondary** data source and run `{resource.service.name="fanout-demo-app"}` in **Search**.

   Expect far fewer traces, roughly 10% of the primary volume.
   On traces that appear, user agent, cookie, and request body attributes are removed and remaining attributes are truncated to 128 characters.

3. Compare primary and secondary:

   - **Trace volume**: Primary keeps 100% of traces; secondary keeps about 10%.
   - **Attribute fidelity**: Primary retains all attributes; secondary strips user agent, cookies, and request body.
   - **Attribute length**: Primary has no truncation; secondary truncates remaining attributes to 128 characters.

4. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Change sampling rate**: Edit `sampling_percentage` under `probabilistic_sampler` in `config-otel.yaml`.
- **Strip different attributes**: Edit the `transform/strip` statements in `config-otel.yaml`.
- **Add another fanout branch**: Add a new `forward` connector and pipeline in `config-otel.yaml`.

## Troubleshoot common problems

Covers startup failures, missing traces, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `tempo`.
Validate the OTel configuration with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No traces in Tempo Primary or Tempo Secondary

Wait for the demo app load generator to start. It sleeps five seconds after startup.
In Grafana, search **Tempo Primary** for `{resource.service.name="fanout-demo-app"}`.
Check Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 8080, 3000, 3200, 3201, 9090, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/multi-pipeline-fanout` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OpenTelemetry forward connector: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/forwardconnector
- More examples: https://github.com/grafana/alloy-scenarios
