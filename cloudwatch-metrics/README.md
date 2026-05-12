# AWS CloudWatch metrics — no AWS account required

Demonstrates `prometheus.exporter.cloudwatch`, Alloy's built-in wrapper around [YACE](https://github.com/nerdswords/yet-another-cloudwatch-exporter). **No real AWS account or live infrastructure needed** — [LocalStack](https://localstack.cloud/) emulates the CloudWatch and STS APIs locally, and a small Python seeder container plants synthetic `EC2/CPUUtilization` data points every 30 s.

This is the same offline-reproducibility pattern used by [`aws-firehose-logs/`](../aws-firehose-logs/).

## Architecture

```
metric-seeder (Python)
  └── put_metric_data → LocalStack CloudWatch (:4566)
                              ↑
                        Alloy prometheus.exporter.cloudwatch
                              ↓
                        prometheus.scrape → prometheus.remote_write
                              ↓
                        Prometheus (:9090)
                              ↑
                        Grafana (:3000)
```

- **`localstack`** — emulates `cloudwatch` + `sts` APIs; no AWS credentials required
- **`metric-seeder`** — pushes `CPUUtilization` (random 5–85 %) for `i-1234567890abcdef0` every 30 s
- **`alloy`** — runs `prometheus.exporter.cloudwatch` pointed at LocalStack via `AWS_ENDPOINT_URL`; scrapes every 60 s and remote-writes to Prometheus
- **`prometheus`** — stores and serves metrics
- **`grafana`** — visualises with Prometheus datasource auto-provisioned

## Running

```bash
# From this directory
docker compose up -d

# Or from the repo root
./run-example.sh cloudwatch-metrics
```

LocalStack and the metric-seeder start first; Alloy waits for LocalStack to be healthy before scraping.

## Accessing

| Service | URL |
|---|---|
| **Grafana** | http://localhost:3000 (no login) |
| **Prometheus** | http://localhost:9090 |
| **Alloy UI** | http://localhost:12345 |
| **LocalStack** | http://localhost:4566/_localstack/health |

## Trying it out

Within ~90 s of bring-up (LocalStack ready → seeder plants first points → Alloy scrapes → Prometheus ingests), metrics appear in Prometheus.

Open **Grafana → Explore → Prometheus** and run:

```promql
# CPU utilisation for the seeded EC2 instance
aws_ec2_cpuutilization_average

# Maximum CPU in the last 5 m
aws_ec2_cpuutilization_maximum

# All CloudWatch-sourced metrics
{job="cloudwatch/localstack/ec2_cpu"}
```

Or query Prometheus directly:

```bash
curl -sG 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=aws_ec2_cpuutilization_average' | jq .
```

In the **Alloy UI** (http://localhost:12345), navigate to **Graph** to see the pipeline:
`prometheus.exporter.cloudwatch.localstack` → `prometheus.scrape.cloudwatch` → `prometheus.remote_write.local`

Use **livedebugging** on `prometheus.scrape.cloudwatch` to watch metrics flow through in real time.

## Adapting for real AWS

To point this scenario at real CloudWatch instead of LocalStack:

1. Remove the `localstack` and `metric-seeder` services from `docker-compose.yml`
2. Remove the `AWS_ENDPOINT_URL` environment variable from the `alloy` service
3. Set real credentials:
   ```yaml
   environment:
     - AWS_ACCESS_KEY_ID=<your-key>
     - AWS_SECRET_ACCESS_KEY=<your-secret>
     - AWS_DEFAULT_REGION=us-east-1
   ```
4. Update the `dimensions` in `config.alloy` to match a real `InstanceId` in your account

The `config.alloy` static job configuration and Alloy pipeline are identical for both LocalStack and real AWS.
