# Amazon Data Firehose logs

This scenario shows how to ingest Amazon Data Firehose deliveries with `loki.source.awsfirehose`.
Firehose sends logs as an HTTPS POST in a documented JSON shape, and this scenario emulates the producer with a small Python container.
You don't need an AWS account or any AWS SDKs.
Alloy receives the batches, promotes CloudWatch envelope labels, and forwards parsed log lines to Loki.
The `config.alloy` file defines the pipeline.

This scenario uses the same producer-emulator pattern as [`syslog/`](../syslog/) and [`gelf-log-ingestion/`](../gelf-log-ingestion/).

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 12345 for Alloy, and 9999 for the Firehose receiver free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+------------------+       +---------------------------+       +------+       +---------+
| firehose-sender  | POST  | Alloy                     | push  |      | query |         |
| (Python)         |------>| (loki.source.awsfirehose) |------>| Loki |<------| Grafana |
+------------------+       +---------------------------+       +------+       +---------+
```

- **firehose-sender**: A Python container that generates synthetic CloudWatch-style log batches every five seconds and POSTs them to Alloy in the documented Firehose delivery format.
  Records use a gzip-compressed, base64-encoded `data` field.
- **Alloy**: Runs `loki.source.awsfirehose` on port 9999 at `/awsfirehose/api/v1/push`.
  CloudWatch envelope discovery labels are promoted through `loki.relabel` rules attached to the source.
- **Loki**: Stores the parsed log lines.
- **Grafana**: Queries logs with a provisioned Loki data source.

The sender alternates between three log streams:

1. VPC flow logs on `eni-0abc1234-all` in log group `/aws/vpc/flowlogs`
2. VPC flow logs on `eni-0def5678-all` in the same log group
3. Lambda invocation logs on `[$LATEST]abc` in log group `/aws/lambda/checkout-service`

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/aws-firehose-logs`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh aws-firehose-logs`

3. Confirm all containers are up: `cd alloy-scenarios/aws-firehose-logs && docker compose ps`

   You should see `alloy`, `loki`, `grafana`, and `firehose-sender`.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Firehose endpoint** at http://localhost:9999/awsfirehose/api/v1/push: POSTable from your laptop.
- **Loki** at http://localhost:3100: Log storage backend.

## Understand the configuration

The `config.alloy` pipeline has three components:

1. **`loki.relabel "firehose"`**: Defines rules that promote CloudWatch envelope discovery labels to indexed labels.
   `__aws_cw_log_group` becomes `log_group`, `__aws_cw_log_stream` becomes `log_stream`, and `__aws_cw_msg_type` becomes `msg_type`.
   These labels are exposed through the source's `relabel_rules` argument, not through a standalone relabel stage after the source.
2. **`loki.source.awsfirehose "fake"`**: Listens on `0.0.0.0:9999` and accepts Firehose delivery payloads.
   It auto-detects the CloudWatch subscription envelope and attaches `__aws_cw_*` discovery labels when present.
   Parsed entries forward to `loki.write.local`.
3. **`loki.write "local"`**: Pushes log lines to Loki at `http://loki:3100/loki/api/v1/push`.

The `firehose-sender` service reads `ALLOY_FIREHOSE_URL`, `INTERVAL_SECONDS`, and `EVENTS_PER_BATCH` from environment variables in `docker-compose.yml`.

## Try it out

1. Wait about ten seconds after bring-up for the sender to produce its first batches.

2. Open Grafana **Explore**, select the **Loki** data source, and try these LogQL queries:

   - `{log_group=~".+"}`: all Firehose-delivered logs
   - `{log_group="/aws/vpc/flowlogs"}`: VPC flow logs only
   - `{log_group="/aws/vpc/flowlogs", log_stream="eni-0abc1234-all"}`: a specific ENI
   - `{log_group="/aws/lambda/checkout-service"}`: Lambda invocations
   - `{msg_type="DATA_MESSAGE"}`: data records only, excluding control messages

3. POST your own record from your laptop:

   ```sh
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

   Query `{log_group="/manual"}` in Grafana to find the entry.

4. Open the Alloy UI at http://localhost:12345 and use live debug on `loki.source.awsfirehose.fake` to watch records flow through the pipeline.

## Customize the scenario

- **Change batch rate**: Edit `INTERVAL_SECONDS` or `EVENTS_PER_BATCH` for the `firehose-sender` service in `docker-compose.yml`.
- **Enable access-key validation**: Set the `access_key` argument on `loki.source.awsfirehose` and send the matching `X-Amz-Firehose-Access-Key` header from your producer.
- **Add TLS**: Add a `tls` block with `cert_file` and `key_file` under the source's `http` block for production deployments.

## Troubleshoot common problems

Diagnose missing logs, sender failures, and port conflicts.

### No logs appear in Grafana after a minute

Check that `firehose-sender` is running with `docker compose ps`.
Read its output with `docker compose logs firehose-sender`. Connection errors to Alloy appear there.
Open the Alloy UI at http://localhost:12345 and check that `loki.source.awsfirehose.fake` is healthy.

### curl test returns an error

Check that Alloy is listening on port 9999 with `docker compose ps`.
The `data` field must be gzip-compressed JSON, then base64-encoded, matching the Firehose delivery format.

### Port conflicts with other services

Ports 3000, 3100, 12345, and 9999 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Differences from real Firehose

This scenario emulates the wire format.
A real Firehose delivery stream has additional concerns the demo doesn't cover:

- **Authentication**: Real Firehose includes an `X-Amz-Firehose-Access-Key` header that the receiver validates.
  `loki.source.awsfirehose` supports this through the `access_key` argument.
  The demo leaves it disabled so you can POST from curl.
  In production, always set an access key.
- **TLS**: Real Firehose requires HTTPS.
  Add a `tls` block with `cert_file` and `key_file` to the Alloy `http` block in production.
- **Retry semantics**: Real Firehose retries on 5xx and partial successes.
  The Python sender logs failures and moves on.
- **Custom labels via header**: Real Firehose can set `X-Amz-Firehose-Common-Attributes` with label names prefixed `lbl_`.
  Add this header in your own producer to see additional discovery labels appear.

## Stop the scenario

Run `docker compose down` from the scenario directory.
Run `docker compose down -v` to remove stored data as well.

## Next steps

- `loki.source.awsfirehose` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.awsfirehose/
- Syslog ingestion scenario: [../syslog/](../syslog/)
- GELF log ingestion scenario: [../gelf-log-ingestion/](../gelf-log-ingestion/)
