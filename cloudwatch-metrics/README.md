# Amazon CloudWatch metrics

This scenario shows how to pull Amazon CloudWatch metrics into Prometheus with `prometheus.exporter.cloudwatch`, Alloy's built-in wrapper around [YACE](https://github.com/nerdswords/yet-another-cloudwatch-exporter).
You don't need a real AWS account.
[LocalStack](https://localstack.cloud/) emulates the CloudWatch and STS APIs locally, and a Python seeder pushes synthetic `EC2/CPUUtilization` data points every 30 seconds.
The `config.alloy` file defines the pipeline.

This scenario uses the same offline pattern as [`aws-firehose-logs/`](../aws-firehose-logs/).

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 4566 for LocalStack, 9090 for Prometheus, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

LocalStack emulates CloudWatch, the seeder writes metrics into it, and Alloy reads those metrics through the CloudWatch exporter.

```text
+---------------+      +------------+
| metric-seeder |----->| LocalStack |
+---------------+      | CloudWatch |
                       +-----+------+
                             ^
                             | GetMetricData
                       +-----+-------+     +------------+     +---------+
                       | Alloy       |---->| Prometheus |---->| Grafana |
                       +-------------+     +------------+     +---------+
```

- **LocalStack** emulates `cloudwatch` and `sts` on port 4566.
- **metric-seeder** pushes `CPUUtilization` values between 5% and 85% for instance `i-1234567890abcdef0` every 30 seconds.
- **Alloy** runs `prometheus.exporter.cloudwatch` against LocalStack through `AWS_ENDPOINT_URL`, scrapes every 60 seconds, and remote-writes to Prometheus.
- **Prometheus** stores the CloudWatch-derived metrics.
- **Grafana** queries them through a provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/cloudwatch-metrics`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh cloudwatch-metrics`

3. Check that all containers are up: `cd alloy-scenarios/cloudwatch-metrics && docker compose ps`

   Expect `localstack`, `metric-seeder`, `alloy`, `prometheus`, and `grafana`.
   LocalStack and the metric-seeder start first.
   Alloy waits for LocalStack to become healthy before it scrapes.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.
- **Prometheus** at http://localhost:9090: Query CloudWatch-derived metrics directly.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **LocalStack health** at http://localhost:4566/_localstack/health: Check that the emulated AWS APIs are ready.

## Understand the configuration

The `config.alloy` pipeline has three components:

1. **`prometheus.exporter.cloudwatch "localstack"`**: Static job `ec2_cpu` in region `us-east-1` reads `CPUUtilization` from namespace `AWS/EC2` for instance `i-1234567890abcdef0`, with `Average` and `Maximum` statistics and a one-minute period.
2. **`prometheus.scrape "cloudwatch"`**: Scrapes the exporter every 60 seconds and forwards samples to `prometheus.remote_write.local`.
3. **`prometheus.remote_write "local"`**: Sends samples to Prometheus at `http://prometheus:9090/api/v1/write`.

The `alloy` service sets `AWS_ENDPOINT_URL=http://localstack:4566` so the AWS SDK talks to LocalStack instead of real AWS endpoints.
`livedebugging` is enabled.

## Try it out

Allow about 90 seconds after bring-up for LocalStack to become healthy, the seeder to plant its first data points, Alloy to scrape, and Prometheus to ingest the samples.

1. Open Grafana **Explore**, select the **Prometheus** data source, and try these PromQL queries:

   - `aws_ec2_cpuutilization_average`: average CPU utilization for the seeded EC2 instance
   - `aws_ec2_cpuutilization_maximum`: maximum CPUUtilization statistic for the instance
   - `{job="cloudwatch/localstack/ec2_cpu"}`: all metrics from the static CloudWatch job

2. Query Prometheus directly from your terminal:

   ```sh
   curl -sG 'http://localhost:9090/api/v1/query' \
     --data-urlencode 'query=aws_ec2_cpuutilization_average' | jq .
   ```

3. Open the Alloy UI at http://localhost:12345.
   Open **Graph** to view the pipeline: `prometheus.exporter.cloudwatch.localstack` → `prometheus.scrape.cloudwatch` → `prometheus.remote_write.local`.
   Use live debug on `prometheus.scrape.cloudwatch` to watch metrics flow through in real time.

## Customize the scenario

To point this scenario at real CloudWatch instead of LocalStack:

1. Remove the `localstack` and `metric-seeder` services from `docker-compose.yml`.
2. Remove the `AWS_ENDPOINT_URL` environment variable from the `alloy` service.
3. Set real credentials on the `alloy` service:

   ```yaml
   environment:
     - AWS_ACCESS_KEY_ID=<your-key>
     - AWS_SECRET_ACCESS_KEY=<your-secret>
     - AWS_DEFAULT_REGION=us-east-1
   ```

4. Update the `dimensions` block in `prometheus.exporter.cloudwatch "localstack"` to match a real `InstanceId` in your account.

The static job configuration and Alloy pipeline stay the same for LocalStack and real AWS.

## Troubleshoot common problems

Use these steps when metrics don't appear or ports conflict.

### No metrics in Grafana after 90 seconds

Check that LocalStack is healthy at http://localhost:4566/_localstack/health.
Run `docker compose logs metric-seeder` and check that it prints CPU values every 30 seconds.
Open the Alloy UI at http://localhost:12345 and check that `prometheus.exporter.cloudwatch.localstack` and `prometheus.scrape.cloudwatch` are healthy.

### Port conflicts with other services

Ports 3000, 4566, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `prometheus.exporter.cloudwatch` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.cloudwatch/
- Amazon Data Firehose logs scenario: [../aws-firehose-logs/](../aws-firehose-logs/)
- YACE project: https://github.com/nerdswords/yet-another-cloudwatch-exporter
