# Collect batch-job metrics through Pushgateway

This scenario shows how Alloy collects metrics from short-lived jobs that cannot be scraped directly.
The bundled batch job pushes `job_last_success_timestamp` to Prometheus Pushgateway, where Alloy scrapes it and remote-writes it to Prometheus.

## Before you begin

Ensure that [Docker][docker] and [Docker Compose][docker-compose] are installed, and that ports 3000, 9090, 9091, and 12345 are available.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-----------+  push metric  +-------------+  scrape  +-------+  remote write  +------------+     +---------+
| batch job |-------------->| Pushgateway |--------->| Alloy |--------------->| Prometheus |<----| Grafana |
+-----------+               +-------------+          +-------+                +------------+     +---------+
```

- **Batch job** sends one completion timestamp to Pushgateway, then remains idle so the example stays observable.
- **Pushgateway** retains the last metric from the job.
- **Alloy** scrapes Pushgateway every five seconds and forwards samples with `prometheus.remote_write`.
- **Prometheus** stores the samples, and **Grafana** provides a ready-to-use Prometheus data source.

## Run the scenario

From the repository root, start the scenario with either command:

```sh
cd prometheus-pushgateway
docker compose up -d
```

```sh
./run-example.sh prometheus-pushgateway
cd prometheus-pushgateway
```

Confirm every service is running:

```sh
docker compose ps
```

## Explore the metric

Open Grafana at http://localhost:3000 or Prometheus at http://localhost:9090 and run:

```promql
job_last_success_timestamp{job="demo_batch"}
```

The value is the Unix timestamp at which the bundled job completed.
Use the following query to calculate its age:

```promql
time() - job_last_success_timestamp{job="demo_batch"}
```

Pushgateway is available at http://localhost:9091 and the Alloy UI at http://localhost:12345.

## Use this pattern with your own job

Push a metric when the job finishes successfully:

```sh
printf 'job_last_success_timestamp %s\n' "$(date +%s)" \
  | curl --data-binary @- http://pushgateway:9091/metrics/job/your_batch_job
```

Use grouping labels only when they identify the logical job. Avoid per-run labels such as a timestamp or random execution ID, because Pushgateway retains every label set and they create unbounded Prometheus cardinality.

## Troubleshoot

If the metric is absent, inspect the job, Pushgateway, and Alloy logs:

```sh
docker compose logs batch-job pushgateway alloy
```

Check http://localhost:9091/metrics to confirm Pushgateway received the metric, then check `up{job="pushgateway"}` in Prometheus. A value of `0` means Alloy cannot reach Pushgateway.

## Stop the scenario

Run this from the scenario directory:

```sh
docker compose down
```

## Next steps

- [Pushgateway documentation](https://github.com/prometheus/pushgateway)
- [`prometheus.scrape` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/)
- [`prometheus.remote_write` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/)
