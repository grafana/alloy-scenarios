# AWS Kinesis Data Firehose to Loki — no AWS account required

Demonstrates `loki.source.awsfirehose`, the HTTP receiver that accepts AWS Kinesis Data Firehose's documented delivery format. **You don't need an AWS account or any AWS SDKs** — Firehose is just an HTTPS POST in a known JSON shape, and this scenario emulates the producer with a small Python container.

This is the same producer-emulator pattern used by [`syslog/`](../syslog/) and [`gelf-log-ingestion/`](../gelf-log-ingestion/).

## Architecture

- **`alloy`** runs `loki.source.awsfirehose` on port `:9999`, listening at `/awsfirehose/api/v1/push`
- **`firehose-sender`** (Python) generates synthetic CloudWatch-style log batches every 5 seconds and POSTs them to Alloy in the documented Firehose delivery format (records array with gzip-compressed, base64-encoded data fields)
- **`loki`** + **`grafana`** for storage and visualization, with the Loki datasource auto-provisioned

The sender alternates between three log streams:
1. VPC flow logs on `eni-0abc1234-all` (channel `/aws/vpc/flowlogs`)
2. VPC flow logs on `eni-0def5678-all` (same channel, different stream)
3. Lambda invocation logs on `[$LATEST]abc` (channel `/aws/lambda/checkout-service`)

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root
./run-example.sh aws-firehose-logs
```

## Accessing

- **Grafana**: http://localhost:3000 (no login)
- **Alloy UI**: http://localhost:12345 — confirm components healthy, use livedebugging to watch records flow through
- **Firehose endpoint**: http://localhost:9999/awsfirehose/api/v1/push (POSTable from your laptop)
- **Loki API**: http://localhost:3100

## Trying it out

Within ~10 seconds of bring-up, the sender starts producing batches. In Grafana Explore on Loki:

```logql
# All Firehose-delivered logs
{log_group=~".+"}

# Just VPC flow logs
{log_group="/aws/vpc/flowlogs"}

# A specific ENI
{log_group="/aws/vpc/flowlogs", log_stream="eni-0abc1234-all"}

# Lambda invocations
{log_group="/aws/lambda/checkout-service"}

# Just the data records (vs control messages)
{msg_type="DATA_MESSAGE"}
```

The promoted labels `log_group`, `log_stream`, and `msg_type` come from the CloudWatch envelope — `loki.source.awsfirehose` automatically attaches `__aws_cw_log_group`, `__aws_cw_log_stream`, and `__aws_cw_msg_type` discovery labels when the records contain a CloudWatch subscription filter envelope; this scenario's `loki.relabel` block promotes them.

## Send your own records

The receiver is just an HTTP endpoint. From your laptop:

```bash
curl -X POST http://localhost:9999/awsfirehose/api/v1/push \
  -H 'Content-Type: application/json' \
  -d '{
    "requestId": "test-1",
    "timestamp": 1234567890,
    "records": [
      {"data": "'$(printf '{"messageType":"DATA_MESSAGE","logGroup":"/manual","logStream":"laptop","logEvents":[{"id":"x","timestamp":1234567890000,"message":"hi from curl"}]}' | gzip | base64)'"}
    ]
  }'
```

This adds a one-off entry visible at `{log_group="/manual"}`.

## Differences from real Firehose

This scenario emulates the wire format. A real Firehose delivery stream has a few additional concerns the demo doesn't cover:

- **Authentication**: real Firehose includes an `X-Amz-Firehose-Access-Key` header that the receiver validates. `loki.source.awsfirehose` supports this via the `access_key` argument; we leave it disabled in the demo for ease of trying it from curl. In production, **always** set an access key.
- **TLS**: real Firehose requires HTTPS. Add `tls { cert_file = ..., key_file = ... }` to the Alloy `http` block in production.
- **Retry semantics**: real Firehose retries on 5xx and partial successes. The Python sender here just logs failures and moves on.
- **Custom labels via header**: real Firehose can set `X-Amz-Firehose-Common-Attributes` (label names prefixed `lbl_`). Try adding this to your own producer to see additional discovery labels appear.

## Stopping

```bash
docker compose down -v
```
