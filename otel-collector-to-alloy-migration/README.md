# OpenTelemetry Collector to Alloy migration

This scenario runs the same OTLP traces and metrics through a stock OpenTelemetry Collector and Grafana Alloy.
It shows the direct River translation of a familiar Collector pipeline: OTLP receiver, batch processor, and OTLP exporters.

Each collector writes to its own Tempo and Prometheus instance so the same telemetry can be compared without duplicate samples sharing a series.

## Before you begin

- [Docker][docker] and [Docker Compose][docker-compose]
- Ports 3000 for Grafana and 12345 for the Alloy UI available on the host

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
                              +--------+       +-------------------------+
                              | Alloy  |------>| Tempo (Alloy)            |
                 +----------->| batch  |       | Prometheus (Alloy)       |
                 |            +--------+       +-------------------------+
+----------+ OTLP |
| demo app |------+
+----------+      |            +-----------+   +-------------------------+
                 +----------->| Collector |-->| Tempo (Collector)        |
                              | batch     |   | Prometheus (Collector)   |
                              +-----------+   +-------------------------+
```

- **demo app**: Generates one trace and metric set per second, then sends the identical OTLP payloads to both collectors.
- **Alloy**: Runs the River configuration in `config.alloy` and writes to **Tempo (Alloy)** and **Prometheus (Alloy)**.
- **Collector**: Runs the equivalent YAML in `collector-config.yaml` and writes to **Tempo (Collector)** and **Prometheus (Collector)**.
- **Grafana**: Provisions all four backends as data sources for comparison.

## Run the scenario

From the repository root, start the scenario with pinned image versions:

```bash
./run-example.sh otel-collector-to-alloy-migration
```

Or run it from the scenario directory:

```bash
cd otel-collector-to-alloy-migration
docker compose up -d
```

Check that every service is running:

```bash
docker compose ps
```

## Compare the pipelines

Open Grafana at http://localhost:3000 and choose **Explore**.

1. Select **Prometheus (Alloy)** and run `migration_demo_requests_total`.
2. Select **Prometheus (Collector)** and run the same query. Both return the same request counter for `service_name="migration-demo"`.
3. Select **Tempo (Alloy)** and search for `{ resource.service.name = "migration-demo" }`.
4. Select **Tempo (Collector)** and use the same search. Both show `checkout` spans with matching `request.id` attributes.

Open the Alloy UI at http://localhost:12345 to inspect the `otelcol.receiver.otlp`, `otelcol.processor.batch`, and exporter components with live debugging.

## Map the Collector configuration to Alloy

| OpenTelemetry Collector YAML | Alloy River |
| --- | --- |
| `receivers.otlp` | `otelcol.receiver.otlp` |
| `processors.batch` | `otelcol.processor.batch` |
| `exporters.otlp/tempo` | `otelcol.exporter.otlp` |
| `exporters.otlphttp/prometheus` | `otelcol.exporter.otlphttp` |
| `service.pipelines` | `output` blocks between components |

The pipelines have the same receiver, batch, and export semantics. Separate backends make the two paths independently observable.

## Troubleshoot common problems

If a service exits, inspect it with `docker compose logs <service>`.
For configuration errors, run `docker compose logs alloy` or `docker compose logs collector`.
The demo app retries exports continuously, so wait a few seconds after the collectors start before querying Grafana.

## Stop the scenario

Run this from the scenario directory:

```bash
docker compose down --volumes
```

## Next steps

- [Migrate to Grafana Alloy](https://grafana.com/docs/alloy/latest/set-up/migrate/)
- [OTLP receiver reference](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.receiver.otlp/)
- [Alloy scenarios](https://github.com/grafana/alloy-scenarios)
