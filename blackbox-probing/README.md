# Blackbox probing

Grafana Alloy probes HTTP endpoints with `prometheus.exporter.blackbox` and stores the results in Prometheus.
Instead of scraping application metrics, Alloy sends synthetic requests to each target and records whether the endpoint responds, how long it took, and what HTTP status code came back.
This scenario probes `nginx` on port 80 and the Prometheus server on port 9090.
The `config.alloy` file defines the blackbox exporter, scrape job, and remote write path.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 8080 for nginx, 9090 for Prometheus, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
+-------+     +---------------------------+     +------------+     +---------+
| nginx |<----| Alloy                     |---->| Prometheus |---->| Grafana |
| :80   |     | blackbox probe + scrape   |     |            |     |         |
+-------+     +---------------------------+     +------------+     +---------+
                      |
                      | HTTP probe
                      v
                prometheus:9090
```

- **nginx**: A simple web server on port 80 inside the Compose network, published on host port 8080.
- **Alloy**: Runs `prometheus.exporter.blackbox` with an `http_2xx` module, scrapes the probe metrics every 15 seconds, and remote-writes them to Prometheus.
- **Prometheus**: Stores probe metrics through its remote-write receiver.
- **Grafana**: Queries probe metrics with a provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/blackbox-probing`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh blackbox-probing`

3. Check that all containers are up: `cd alloy-scenarios/blackbox-probing && docker compose ps`

   Expect `nginx`, `prometheus`, `grafana`, and `alloy`.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query probe metrics directly.
- **nginx** at http://localhost:8080: The probed web server on the host.

## Understand the configuration

The `config.alloy` pipeline has three components:

1. **`prometheus.exporter.blackbox "default"`**: Defines an `http_2xx` module with a five-second timeout and two probe targets:
   - `nginx` at `http://nginx:80`
   - `prometheus` at `http://prometheus:9090`
2. **`prometheus.scrape "blackbox_targets"`**: Scrapes metrics from the blackbox exporter every 15 seconds and forwards them to remote write.
3. **`prometheus.remote_write "remote"`**: Sends samples to Prometheus at `http://prometheus:9090/api/v1/write`.

`livedebugging` is enabled so you can inspect probe traffic in the Alloy UI.

## Try it out

1. Open Grafana **Explore** or Prometheus at http://localhost:9090 and try these PromQL queries:

   - `probe_success`: returns `1` when a probe succeeds, `0` when it fails
   - `probe_duration_seconds`: total time the probe took
   - `probe_http_status_code`: HTTP status code from the target
   - `probe_http_duration_seconds`: duration by phase such as resolve, connect, TLS, processing, and transfer

2. Open the Alloy UI at http://localhost:12345 and use live debug on `prometheus.exporter.blackbox.default` to watch probes run.

## Customize the scenario

- **Add a target**: Add another `target` block inside `prometheus.exporter.blackbox "default"` with a `name`, `address`, and `module`.
- **Change the probe module**: Edit the inline `config` on `prometheus.exporter.blackbox "default"` to add modules for HTTPS, TCP, or DNS checks.
- **Change scrape frequency**: Edit `scrape_interval` on `prometheus.scrape "blackbox_targets"`.

## Troubleshoot common problems

When probes fail, metrics are missing, or ports conflict, use these steps.

### probe_success is 0 for a target

Check that the target container is running with `docker compose ps`.
For `nginx`, open http://localhost:8080 in a browser to confirm it responds.
For `prometheus`, open http://localhost:9090/-/healthy.
Read Alloy logs with `docker compose logs alloy` if the exporter fails to start.

### No metrics appear in Grafana

Open the Alloy UI at http://localhost:12345 and check that `prometheus.scrape.blackbox_targets` and `prometheus.remote_write.remote` are healthy.
Allow one scrape interval, 15 seconds, before you query Prometheus.

### Port conflicts with other services

Ports 3000, 8080, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `prometheus.exporter.blackbox` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.blackbox/
- `prometheus.scrape` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/
- Linux host monitoring scenario: [../linux/](../linux/)
