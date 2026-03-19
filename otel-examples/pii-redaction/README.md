# PII Redaction

Demonstrates using the OTel Collector **transform processor** with OTTL `replace_pattern` statements to scrub personally identifiable information (credit card numbers, email addresses, IP addresses) from traces and logs before they reach storage backends.

## What This Demonstrates

- **Transform processor** with OTTL expressions for pattern-based redaction
- Scrubbing PII from **trace span attributes** (credit cards, emails, IPs)
- Scrubbing PII from **log record bodies** (credit cards, emails)
- A Flask demo app that intentionally emits telemetry containing sensitive data
- Verifying that redacted data arrives in Tempo and Loki with masked values

## Prerequisites

- Docker and Docker Compose

## Run

```bash
docker compose up -d
```

The demo app automatically generates traffic every 3 seconds -- no manual interaction needed.

## Alloy UI

The Alloy pipeline debugging UI is available at [http://localhost:12345](http://localhost:12345). This is enabled by the `alloyengine` extension in `config-otel.yaml`, which runs the River UI alongside the OTel pipeline.

If you prefer a pure OTel config without the Alloy UI, remove the `extensions` block and the `extensions: [alloyengine]` line from `config-otel.yaml`.

## Explore

1. Open Grafana at [http://localhost:3000](http://localhost:3000) (no login required).

### Check Traces (Tempo)

2. Go to **Explore** and select the **Tempo** datasource.
3. Search for traces from `pii-demo-app`.
4. Open a trace and inspect the `process-order` span attributes. You should see:
   - `user.credit_card` = `****-****-****-****`
   - `user.email` = `***@***.***`
   - `client.ip` = `***.***.***.***`

### Check Logs (Loki)

5. Switch to the **Loki** datasource.
6. Run:

```logql
{service_name="pii-demo-app"}
```

7. Log messages should contain masked values like `Payment processed for card ****-****-****-**** by ***@***.***`.

## Key Configuration

The `config-otel.yaml` defines two transform processors:

- **`transform/traces`** -- applies `replace_pattern` on span attributes to mask credit card numbers, emails, and IP addresses using regex.
- **`transform/logs`** -- applies `replace_pattern` on log bodies to mask credit cards and emails.

Both processors use `error_mode: ignore` so a failed match does not block the pipeline.

The pipeline receives OTLP data on ports 4317 (gRPC) and 4318 (HTTP), processes it through the transform stage, then exports traces to Tempo and logs to Loki.

## Stop

```bash
docker compose down
```
