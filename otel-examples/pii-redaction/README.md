# PII redaction

This scenario shows how to redact personally identifiable information from traces and logs with OTTL `replace_pattern` statements in the Alloy OTel Engine transform processor.
The demo app intentionally emits credit card numbers, email addresses, and IP addresses in span attributes and log bodies.
Alloy masks those values before export to Tempo and Loki.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 3200 for Tempo, 8888 for the OTel Engine HTTP server, 12345 for the Alloy UI, and 4317 and 4318 for OTLP free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+----------+     +-------------+     +------+     +---------+
| demo-app |     |             |---->| Loki |---->|         |
|          | OTLP| Alloy OTel  |     +------+     | Grafana |
|          |---->| Engine      |---->| Tempo|---->|         |
+----------+     +-------------+     +------+     +---------+
```

- **demo-app**: Flask app that sends traces and logs containing credit card numbers, emails, and IP addresses over OTLP.
- **Alloy**: Runs the OTel Engine from `config-otel.yaml`. `transform/traces` and `transform/logs` redact PII before export. The `alloyengine` extension loads the stub `config.alloy` and exposes the Alloy UI on port 12345.
- **Loki**: Stores redacted logs through its OTLP HTTP endpoint at `http://loki:3100/otlp`.
- **Tempo**: Stores redacted traces at `http://tempo:4317`.
- **Grafana**: Queries Loki and Tempo through provisioned data sources.

## Run the scenario

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/otel-examples/pii-redaction`
   - Deploy the scenario: `docker compose up -d --build`

   The demo app generates traffic every three seconds with no manual interaction needed.

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `cd otel-examples/pii-redaction && docker compose --env-file ../../image-versions.env up -d --build`

   The demo app generates traffic every three seconds with no manual interaction needed.

3. From the `pii-redaction` directory, check that all containers are up: `docker compose ps`

   Expect `demo-app`, `alloy`, `loki`, `tempo`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with Loki and Tempo data sources, with no login required.
- **Alloy UI** at http://localhost:12345: Started by the `alloyengine` extension in `config-otel.yaml`. Because `config.alloy` is a stub, this UI does not graph the OTel YAML pipeline.
- **OTel Engine HTTP server** at http://localhost:8888: Collector telemetry and health endpoint.
- **Loki** at http://localhost:3100: Log backend API.
- **Tempo** at http://localhost:3200: Trace storage backend.

## Understand the OTel pipeline

`config-otel.yaml` defines the pipeline. `config.alloy` is a stub that the `alloyengine` extension loads so the Alloy UI can start next to the OTel Engine.

### transform/traces

Redacts PII from span attributes with `replace_pattern`:

- `user.credit_card`: Masks 16-digit card numbers as `****-****-****-****`
- `user.email`: Masks email addresses as `***@***.***`
- `client.ip`: Masks IP addresses as `***.***.***.***`

### transform/logs

Redacts PII from log bodies with `replace_pattern`:

- Credit card numbers masked as `****-****-****-****`
- Email addresses masked as `***@***.***`

Both processors use `error_mode: ignore` so a failed match does not block the pipeline.

### Pipeline wiring

1. **Traces**: `otlp` → `transform/traces` → `batch` → `otlp/tempo`
2. **Logs**: `otlp` → `transform/logs` → `batch` → `otlphttp/loki` and `debug`

The `debug` exporter prints detailed log output to the Alloy container logs.

To run without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`, and remove the `config.alloy` volume mount from `docker-compose.yml`.

## Try it out

The background load generator calls `/order` every three seconds.

1. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Tempo** data source and run `{resource.service.name="pii-demo-app"}` in **Search**.
   Open a trace and inspect the `process-order` span attributes:

   - `user.credit_card`: `****-****-****-****`
   - `user.email`: `***@***.***`
   - `client.ip`: `***.***.***.***`

2. Select the **Loki** data source and run:

   - `{service_name="pii-demo-app"}`: Redacted log records

   Log messages contain masked values such as `Payment processed for card ****-****-****-**** by ***@***.***`.

3. Open the Alloy UI at http://localhost:12345, or http://localhost:8888 for OTel Engine telemetry.

## Customize the scenario

- **Add redaction rules**: Edit the `replace_pattern` statements in `transform/traces` or `transform/logs` in `config-otel.yaml`.
- **Redact additional fields**: Add span attribute or log body patterns in the transform processors.
- **Change sample PII data**: Edit the `ORDERS` list in `app/app.py`.

## Troubleshoot common problems

Covers startup failures, missing telemetry, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `demo-app`, `alloy`, or `loki`.
Validate the OTel config with `docker compose run --rm alloy otel validate --config=/etc/alloy/config-otel.yaml`.

### No traces or logs in Tempo or Loki

Wait for the demo app load generator to start. It sleeps five seconds after startup.
In Grafana, search Tempo for `{resource.service.name="pii-demo-app"}` and Loki for `{service_name="pii-demo-app"}`.
Check Alloy with `docker compose logs alloy`.

### Port conflicts with other services

Ports 3000, 3100, 3200, 8888, 12345, 4317, and 4318 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` for the conflicting service before you run `docker compose up -d --build`.

## Stop the scenario

Run `docker compose down` from the `otel-examples/pii-redaction` directory.

## Next steps

- OTel engine examples overview: https://github.com/grafana/alloy-scenarios/tree/main/otel-examples
- Alloy OTel Engine documentation: https://grafana.com/docs/alloy/latest/set-up/otel_engine/
- OTTL reference: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/pkg/ottl
- More examples: https://github.com/grafana/alloy-scenarios
