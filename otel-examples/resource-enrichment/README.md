# Resource Enrichment

Automatically enrich all telemetry signals with host, OS, and container metadata using the Alloy OTel pipeline -- without changing application code.

## What This Demonstrates

- **`resourcedetection` processor** with `env`, `system`, and `docker` detectors to discover environment metadata
- **`resource` processor** to add custom attributes (`deployment.environment`, `service.namespace`)
- How the collector adds context that apps do not set themselves (hostname, OS type, architecture)
- **Debug exporter** with `detailed` verbosity to inspect enriched resource attributes

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

## Explore

Open Grafana at [http://localhost:3000](http://localhost:3000).

### Check enriched traces in Tempo

1. Go to Explore > Tempo.
2. Search for traces from `enrichment-demo`.
3. Click on any trace and expand the resource attributes. You should see attributes the app did **not** set:
   - `host.name` -- the collector container's hostname
   - `os.type` -- detected OS
   - `host.arch` -- CPU architecture
   - `deployment.environment` = `demo`
   - `service.namespace` = `otel-examples`

### Check enriched metrics in Prometheus

1. Go to Explore > Prometheus.
2. Query `app_requests_total` -- the metric labels should include `deployment_environment`, `service_namespace`, and other enriched attributes.

### Inspect debug exporter output

```bash
docker compose logs alloy
```

Look for the `debug` exporter output showing the full resource with detected attributes attached.

### Check the Alloy OTel pipeline

Visit the Alloy OTel HTTP server at [http://localhost:8888](http://localhost:8888).

## Key Configuration

The `config-otel.yaml` pipeline uses two processors:

1. **`resourcedetection`** -- Auto-detects environment metadata:
   - `env` detector: reads `OTEL_RESOURCE_ATTRIBUTES` environment variable
   - `system` detector: discovers `host.name`, `os.type`, `host.arch`
   - `docker` detector: discovers container metadata (requires Docker socket mount)
   - `override: false` ensures app-set attributes are not overwritten

2. **`resource`** -- Adds static attributes:
   - `deployment.environment` = `demo`
   - `service.namespace` = `otel-examples`
   - Uses `upsert` action so existing values are updated but new ones are also created

Note: The Alloy container mounts `/var/run/docker.sock` read-only to enable the Docker detector.

## Stop

```bash
docker compose down
```
