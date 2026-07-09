# Build only what you need with a minimal OpenTelemetry Collector

This scenario shows how to build a minimal OpenTelemetry Collector image and run a traces pipeline end to end.
You generate traces, process traces with memory and batch processors, and export traces to Tempo for exploration in Grafana.
This scenario uses OpenTelemetry YAML in `config.yaml` and not [Alloy syntax](https://grafana.com/docs/alloy/latest/get-started/syntax/).

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports `3000`, `3200`, `4317`, and `4318` free on your host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Telemetry flows from the load generator to the custom collector and then to Tempo.

```text
+--------------+   OTLP   +---------------+   OTLP   +-------+     +---------+
| telemetrygen |--------->| minimal-otel  |--------->| Tempo |<----| Grafana |
+--------------+          +---------------+          +-------+     +---------+
```

- **minimal-otel:** Builds from `builder-config.yaml` and runs the pipeline in `config.yaml`.
- **Tempo:** Stores traces and exposes search APIs.
- **Grafana:** Auto provisions a Tempo data source and provides trace exploration.
- **telemetrygen:** Sends sample traces with service name `minimal-demo`.

## Run the scenario

1. Clone the repository if you have not cloned it yet: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/custom-builds/minimal-otel`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh custom-builds/minimal-otel`

3. Confirm all containers are up: `cd alloy-scenarios/custom-builds/minimal-otel && docker compose ps`

4. Check collector logs for active trace flow: `cd alloy-scenarios/custom-builds/minimal-otel && docker compose logs minimal-otel --tail=50`

## Explore the services

Open Grafana at [http://localhost:3000](http://localhost:3000). Anonymous admin access is enabled, so you do not need to sign in.

In Grafana, open **Explore**, choose **Tempo**, and search for service name `minimal-demo`.

## Understand the configuration

The scenario uses four configuration files in pipeline order.

`config.yaml` defines an OpenTelemetry pipeline with:

- `otlp` receiver on `0.0.0.0:4317` and `0.0.0.0:4318`
- `memory_limiter` and `batch` processors
- `otlp` exporter to `tempo:4317`
- `debug` exporter for local visibility

`builder-config.yaml` is the OpenTelemetry Collector Builder manifest. It defines the distribution name, output path, and OpenTelemetry Collector version for the generated binary.

This scenario manifest includes:

- `receivers`: `otlpreceiver`
- `processors`: `batchprocessor` and `memorylimiterprocessor`
- `exporters`: `otlpexporter` and `debugexporter`
- `providers`: `fileprovider` and `envprovider`

It pins unstable modules to `v0.147.0` and stable config providers to `v1.53.0`.

`Dockerfile` uses two stages:

1. `build` stage: runs `go run go.opentelemetry.io/collector/cmd/builder@<OCB_VERSION> --config builder-config.yaml` in a Go image and produces the `minimal-otelcol` binary.
2. `runtime` stage: copies only that binary into a distroless image and starts it with `--config=/etc/otelcol/config.yaml`.

`tempo-config.yaml` configures a local Tempo instance with OTLP receivers and local block storage.

## Try it out

Use these checks to confirm data flow and inspect the custom build result.

1. Query Tempo for traces from `minimal-demo`:

   ```sh
   curl -s "http://localhost:3200/api/search?tags=service.name%3Dminimal-demo&limit=3"
   ```

2. View debug exporter output in collector logs:

	```sh
	docker compose logs minimal-otel --tail=100
	```

	Example output:

	```text
	info  Traces  {"otelcol.component.id": "debug", "otelcol.signal": "traces", "resource spans": 1, "spans": 2}
	```

3. Compare image sizes:

   Image size depends on version, platform, and base image.

   ```sh
   docker images | grep -E "minimal-otel|grafana/alloy"
   ```

4. List compiled components in the custom binary:

   ```sh
   docker run --rm $(docker compose images -q minimal-otel) components
   ```

## Customize the scenario

Use these options to extend the scenario.

- **Different signals:** Add `metrics` or `logs` pipelines to `config.yaml` when you need more than traces.
- **More components:** Add a new `gomod` entry under the correct section in `builder-config.yaml`. For example, add `go.opentelemetry.io/collector/exporter/otlphttpexporter` when you need OTLP over HTTP export, or add a contrib exporter module when you need a non core backend.

After changes, rebuild the image:

```sh
docker compose up -d --build
```

## Troubleshoot common problems

Use these checks when startup or trace flow fails.

### Resolve port conflicts

Check whether another process uses required ports:

```sh
ss -ltnp | grep -E ":3000|:3200|:4317|:4318"
```

### Resolve missing traces in Grafana

Check telemetrygen and collector logs:

```sh
docker compose ps telemetrygen minimal-otel tempo
docker compose logs telemetrygen minimal-otel --tail=100
```

### Resolve build failures

Rebuild without cache to inspect full builder output:

```sh
docker compose build --no-cache minimal-otel
```

## Stop the scenario

Run `docker compose down` from the `minimal-otel` directory.

## Next steps

- [Custom Alloy builds](../)
- [OpenTelemetry Collector Builder](https://github.com/open-telemetry/opentelemetry-collector/tree/main/cmd/builder)
- [OpenTelemetry in Alloy](https://grafana.com/docs/alloy/latest/introduction/otel_alloy/)
- [OpenTelemetry engine command reference](https://grafana.com/docs/alloy/latest/reference/cli/otel/)
- [Custom components in Alloy](https://grafana.com/docs/alloy/latest/get-started/components/custom-components/)
