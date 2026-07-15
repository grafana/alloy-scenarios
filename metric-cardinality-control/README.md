# Control Prometheus metric cardinality

This scenario shows how Grafana Alloy uses `prometheus.relabel` to build a cardinality-controlled Prometheus path before remote write.
A local exporter exposes an intentionally noisy metric family and a request metric with volatile labels.
Alloy scrapes the exporter once, keeps an original comparison path, and applies `drop`, `labeldrop`, and `replace` rules to a cardinality-controlled path.
Prometheus stores both paths, and a provisioned Grafana dashboard compares current series with distinct series observed over a rolling window.
The `config.alloy` file defines the pipeline.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

The OpenTelemetry [cost control](../otel-examples/cost-control/) scenario reduces telemetry with OpenTelemetry Collector processors.
This scenario uses the Prometheus pull model and applies native Prometheus relabel actions between scrape and remote write.

## Understand the architecture

Alloy scrapes one exporter and fans every sample into two labeled paths.

```text
                                         +-------------------------------+
                                         | prometheus.relabel "before"   |
                                      +->| add pipeline="before"         |-+
                                      |  +-------------------------------+ |
+----------+     +------------------+ |                                    |     +------------+     +---------+
| exporter |<----| prometheus.scrape|-+                                    +---->| Prometheus |---->| Grafana |
+----------+     +------------------+ |                                    |     +------------+     +---------+
                                      |  +-------------------------------+ |
                                      +->| prometheus.relabel "after"    |-+
                                         | drop, labeldrop, and replace  |
                                         | add pipeline="after"         |
                                         +-------------------------------+
```

- **Exporter**: Exposes 200 stable noisy series and, after one startup gap, one request series every scrape.
  The request's ID, query value, and numeric route value change on each scrape.
- **Alloy**: Scrapes once and forwards each sample to both relabel components.
  The `pipeline` label keeps the stored comparison paths distinct.
- **Prometheus**: Receives both paths through one remote-write endpoint.
- **Grafana**: Provides the **Metric cardinality control** dashboard with current and rolling comparisons.

The exporter leaves the request family absent for its first scrape after startup so Alloy can mark any request series retained across an exporter restart as stale before a new series appears.
It then alternates between the retained `checkout` and `search` operations.
Their `/orders/<ID>` and `/users/<ID>` routes normalize to different route templates.
This keeps each current sample distinct from the previous raw series' stale marker after relabeling.
Relabeling rewrites labels but doesn't aggregate samples, so this fixture avoids producing duplicate output label sets at one scrape timestamp.

## Run the scenario

1. Clone the repository if you haven't already, then enter its root directory:

   ```sh
   git clone https://github.com/grafana/alloy-scenarios.git
   cd alloy-scenarios
   ```

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   ```sh
   cd metric-cardinality-control
   docker compose up -d
   ```

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   ```sh
   ./run-example.sh metric-cardinality-control
   cd metric-cardinality-control
   ```

3. Check that all containers are running:

   ```sh
   docker compose ps
   ```

   Expect `exporter`, `alloy`, `prometheus`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Open **Dashboards**, then open **Metric cardinality control**. No login is required.
- **Prometheus** at http://localhost:9090: Run the comparison queries directly.
- **Alloy UI** at http://localhost:12345: Inspect the component graph and live-debug the two relabel paths.

After three successful scrapes, the dashboard should show these patterns:

- **Current demo series**: 201 series in `before` and one series in `after`.
  The `drop` rule removes all 200 noisy series from `after`.
- **Unique demo series observed over 5m**: The `before` value grows as volatile request labels create new identities.
  The `after` request identities remain bounded by the two normalized operations and routes.
- **Current request labels**: The before table includes raw `request_id`, `query`, and route values.
  The after table omits `request_id` and `query` and shows `/orders/:id` or `/users/:id`.

## Understand the configuration

The Alloy pipeline contains four components:

1. **`prometheus.scrape "cardinality_demo"`**: Scrapes `exporter:8000` every five seconds and forwards each sample to both relabel receivers.
2. **`prometheus.relabel "before"`**: Preserves every scraped sample and adds `pipeline="before"`.
3. **`prometheus.relabel "after"`**: Applies these rules in order:

   - `drop` removes the entire `cardinality_demo_noisy_series` family.
   - `labeldrop` removes the `request_id` and `query` labels.
   - `replace` rewrites numeric `/orders/<ID>` and `/users/<ID>` routes to bounded templates.
   - A final rule adds `pipeline="after"` to every surviving series.

4. **`prometheus.remote_write "local"`**: Sends both distinct paths to Prometheus at `http://prometheus:9090/api/v1/write`.

The generated `scrape_samples_post_metric_relabeling` metric isn't used for the comparison.
The scrape component calculates it before samples enter the separate downstream relabel components, so it has the same value in both paths.

## Try it out

1. Open the **Metric cardinality control** dashboard in Grafana.

2. Run this instant query in Grafana **Explore** or Prometheus to count the current demo series:

   ```promql
   count by (pipeline) (
     cardinality_demo_noisy_series{
       job="metric-cardinality-control",
       pipeline=~"before|after"
     }
     or
     topk by (pipeline) (
       1,
       timestamp(
         cardinality_demo_request_value{
           job="metric-cardinality-control",
           pipeline=~"before|after"
         }
       )
     )
   )
   ```

   The noisy family is emitted continuously, while `topk` selects the newest request identity in each pipeline.
   Selecting the newest request prevents an older identity that remains query-visible after an Alloy restart from temporarily inflating the current count.
   This query describes the demo's intended active identities; it doesn't report the total number of series in the TSDB head.

3. Count distinct demo series that have a real sample in the previous five minutes:

   ```promql
   count by (pipeline) (
     present_over_time(
       {job="metric-cardinality-control", pipeline=~"before|after", __name__=~"cardinality_demo_.+"}[5m]
     )
   )
   ```

   The result ramps up after startup.
   It measures rolling observed identities rather than all-time cardinality.

4. Compare the newest request labels directly:

   ```promql
   cardinality_demo_request_value{job="metric-cardinality-control", pipeline="before"}
   and
   topk(
     1,
     timestamp(
       cardinality_demo_request_value{job="metric-cardinality-control", pipeline="before"}
     )
   )
   ```

   ```promql
   cardinality_demo_request_value{job="metric-cardinality-control", pipeline="after"}
   and
   topk(
     1,
     timestamp(
       cardinality_demo_request_value{job="metric-cardinality-control", pipeline="after"}
     )
   )
   ```

5. Open the Alloy UI and select `prometheus.relabel.before` and `prometheus.relabel.after` to inspect the two paths.

## Customize the scenario

- **Change the noisy series count**: Edit `NOISY_SERIES_COUNT` in `app/exporter.py`, then restart the exporter.
- **Change the rolling window**: Replace `[5m]` in the dashboard and example query with a window that covers several scrapes.
- **Try another relabel rule**: Add a rule to `prometheus.relabel "after"`, validate the file with the same Alloy version used by the scenario, and reload the stack.

Every kept sample must still have a unique final label set at each scrape timestamp.
If a rule removes the labels that distinguish simultaneous samples or a current sample from a stale marker, Prometheus receives duplicates rather than an aggregate.

The `before` path exists only for this demonstration and intentionally increases total ingestion.
In a production cardinality-control pipeline, forward only the controlled path to remote write.

## Troubleshoot common problems

Use these steps when data or the dashboard doesn't look as expected.

### The dashboard is empty

Run `docker compose ps` and check that all four services are running.
Open the Alloy UI and check that `prometheus.scrape.cardinality_demo` reports successful scrapes.
Run `up{job="metric-cardinality-control"}` in Prometheus and expect one series in each pipeline.

### The after route is not normalized

Run the two request queries from **Try it out** and compare their `route` labels.
Check that the exporter still emits `/orders/<ID>` and `/users/<ID>` values that match the replace rule in `config.alloy`.

### Prometheus reports duplicate or out-of-order samples

Check that the exporter emits only one request sample per scrape and continues to alternate its retained operation and route family.
Don't emit multiple raw series that become the same final label set after `labeldrop` and `replace`.

### A simple current-series count is temporarily high

If Alloy restarts while Prometheus keeps its data, request identities from the previous scrape cache can remain query-visible for up to five minutes.
A plain `count` over all demo series can therefore temporarily include both the old and new identities.
The dashboard's current query avoids this by selecting the newest request identity with `topk` and `timestamp`.
The rolling query intentionally continues to include identities observed during its five-minute window.

### Port conflicts with other services

Ports 3000, 9090, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run this command from the scenario directory:

```sh
docker compose down
```

## Next steps

- `prometheus.scrape` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/
- `prometheus.relabel` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.relabel/
- `prometheus.remote_write` reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/
- Prometheus relabel configuration: https://prometheus.io/docs/prometheus/latest/configuration/configuration/#relabel_config
- Related OpenTelemetry scenario: [Cost control](../otel-examples/cost-control/)
