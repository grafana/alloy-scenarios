# OTTL Transform Cookbook

A cookbook of the most useful OpenTelemetry Transformation Language (OTTL) patterns running in Grafana Alloy's OTel engine. Demonstrates JSON body parsing, severity mapping, attribute promotion, truncation, pattern replacement, and conditional transforms.

## What This Demonstrates

- **JSON body parsing**: Log records arrive with JSON string bodies; OTTL parses them and promotes fields to attributes
- **Severity mapping**: String severity levels ("INFO", "WARN", "ERROR") are mapped to proper OTel severity numbers
- **Attribute cleanup**: Promoted fields like `level` and `timestamp` are deleted after extraction
- **Tier labeling**: Trace spans are automatically tagged with `app.tier=frontend` (when `http.target` is present) or `app.tier=backend` (when `db.system` is present)
- **Attribute truncation**: All span attributes are truncated to 256 characters
- **Resource enrichment**: A `deployment.environment=demo` attribute is added to all trace resources

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

## Alloy UI

The Alloy pipeline debugging UI is available at [http://localhost:12345](http://localhost:12345). This is enabled by the `alloyengine` extension in `config-otel.yaml`, which runs the River UI alongside the OTel pipeline.

If you prefer a pure OTel config without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`.

## Explore

### Logs in Loki

Open Grafana at [http://localhost:3000](http://localhost:3000) and go to **Explore > Loki**.

Query to see parsed JSON attributes:

```logql
{service_name="ottl-demo-app"}
```

You should see that JSON fields from the log body (`order_id`, `message`, `amount`, `error_code`, etc.) have been promoted to log attributes. The `level` and `timestamp` fields should be removed after promotion. Severity should be correctly set (INFO=9, WARN=13, ERROR=17).

### Traces in Tempo

Switch to **Explore > Tempo** and search for traces from `ottl-demo-app`.

Look for:
- `app.tier` label on spans: `frontend` for HTTP spans, `backend` for database spans
- Long attribute values (like `http.user_agent` or `db.connection_string`) truncated to 256 characters
- `deployment.environment=demo` on trace resources

## Key Configuration

The `config-otel.yaml` defines three transform processors:

1. **`transform/parse-logs`**: Parses JSON string bodies with `ParseJSON(body)`, maps severity, and cleans up attributes
2. **`transform/traces`**: Adds tier labels based on attribute presence, truncates all attributes to 256 chars
3. **`transform/resources`**: Adds `deployment.environment=demo` to trace resources

These are wired into separate pipelines for traces and logs.

## Stop

```bash
docker compose down
```
