# Grafana Alloy clustering

This scenario shows how to run a three-node Grafana Alloy cluster that shares a pool of scrape targets.
With clustering enabled, the cluster hashes each target to exactly one node, so each node scrapes roughly one third of the pool.
Stop a node and the survivors pick up its targets within seconds, without gaps, duplicate scrapes, or manual sharding.
Grafana uses the same pattern to scrape [nearly 20M Prometheus metrics](https://grafana.com/blog/how-we-use-grafana-alloy-clustering-to-scrape-nearly-20m-prometheus-metrics/).
The `config.alloy` file defines the scrape pipeline; enable clustering with `--cluster.*` flags in `docker-compose.yml`.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose] v2 or newer.
  The target pool uses `deploy.replicas`, which `docker compose up` honors on v2 and newer.
  On legacy Compose v1, scale the pool with `docker compose up -d --scale target=9` instead.
- Ports 3000 for Grafana, 9090 for Prometheus, and 12345 through 12347 for the three Alloy UIs free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Three Alloy nodes form a gossip cluster, shard nine discovered scrape targets, and remote-write samples to Prometheus.

```text
                     +------------------------------------------------------+
                     |                 Alloy cluster gossip                 |
   9 node-exporter   |   +------------+    +------------+    +------------+ |
   target containers |   | alloy-1    |<-->| alloy-2    |<-->| alloy-3    | |
   via discovery.    |   | ~3 targets |    | ~3 targets |    | ~3 targets | |
   docker            |   +------+-----+    +-----+------+    +------+-----+ |
                     +----------+----------------+-----------------+--------+
                                                 | remote_write
                                                 v
                                          +------------+     +---------+
                                          | Prometheus |---->| Grafana |
                                          +------------+     +---------+
```

- **Target pool**: Nine `node-exporter` containers labeled for discovery.
  Alloy finds them with `discovery.docker` and relabels them as job `clustered-targets`.
- **Alloy cluster**: Three nodes, `alloy-1`, `alloy-2`, and `alloy-3`, form a gossip cluster over the HTTP port.
  Each node discovers all nine targets but scrapes only its assigned subset.
  Every sample carries a `scraped_by` label with the node's hostname.
- **Prometheus**: Receives remote-written samples from all three nodes and runs with `--query.lookback-delta=1m`.
- **Grafana**: Hosts the **Alloy clustering** dashboard with target distribution and ownership views.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/alloy-clustering`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh alloy-clustering`

3. Check that all containers are up: `cd alloy-scenarios/alloy-clustering && docker compose ps`

   Expect Prometheus, Grafana, nine `target` replicas, and three Alloy nodes.

4. Open the **Clustering** page on any node and check that all three peers are listed:

   - alloy-1: http://localhost:12345/clustering
   - alloy-2: http://localhost:12346/clustering
   - alloy-3: http://localhost:12347/clustering

## Explore the services

- **Grafana** at http://localhost:3000: Open the **Alloy clustering** dashboard, with no login required.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **Alloy UI** at http://localhost:12345, http://localhost:12346, and http://localhost:12347: Pipeline graph, **Clustering** page, and live debug views for each node.

The dashboard shows **Targets scraped per Alloy node** in three roughly equal bands that sum to nine, **Targets monitored** at nine, **Alloy nodes scraping** at three, and **Current target ownership** for each target.

## Understand the configuration

Enable clustering on each node with command-line flags in `docker-compose.yml`:

```text
run
  --cluster.enabled=true
  --cluster.join-addresses=alloy-1:12345,alloy-2:12345,alloy-3:12345
  ...
```

The `config.alloy` pipeline has four components:

1. **`discovery.docker "containers"`**: Watches the Docker socket and discovers the target pool.
2. **`discovery.relabel "targets"`**: Keeps containers labeled `clustering.target=true`, sets `instance` from the container name, and sets `job` to `clustered-targets`.
3. **`prometheus.scrape "clustered"`**: Scrapes every 15 seconds with clustering enabled so each node scrapes only its assigned subset:

   ```alloy
   prometheus.scrape "clustered" {
     targets    = discovery.relabel.targets.output
     forward_to = [prometheus.remote_write.default.receiver]

     clustering {
       enabled = true
     }
   }
   ```

4. **`prometheus.remote_write "default"`**: Remote-writes samples to Prometheus and stamps every series with `scraped_by = constants.hostname`.

## Try it out

1. Open the **Alloy clustering** dashboard in Grafana and review target distribution across the three nodes.

2. Run this PromQL query in Grafana **Explore** or Prometheus:

   ```promql
   count by (scraped_by) (up{job="clustered-targets"})
   ```

3. Stop one node and watch its targets move to the survivors:

   ```sh
   docker compose stop alloy-2
   ```

   Within seconds, the cluster reassigns `alloy-2`'s targets to `alloy-1` and `alloy-3`.
   Check the new ownership on each node's **Clustering** page.
   **Targets monitored** stays at nine.

   Over the next minute, as `alloy-2`'s stale `up` series age out of the one-minute lookback window, **Targets scraped per Alloy node** moves its share to the survivors and **Alloy nodes scraping** falls to two.

4. Bring the node back:

   ```sh
   docker compose start alloy-2
   ```

   `alloy-2` rejoins the gossip ring within roughly 20 seconds and reclaims about a third of the targets.

## Customize the scenario

Edit `deploy.replicas` for the `target` service in `docker-compose.yml`, for example to `18`, and run `docker compose up -d`.
Or scale without editing the file: `docker compose up -d --scale target=18`.

## Troubleshoot common problems

Use these steps when the cluster doesn't form or ports conflict.

### A node doesn't appear on the Clustering page

Check that all three Alloy containers are running with `docker compose ps`.
Each node needs `--cluster.enabled=true` and the same `--cluster.join-addresses` list.

### Port conflicts with other services

Ports 3000, 9090, 12345, 12346, and 12347 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- Alloy clustering documentation: https://grafana.com/docs/alloy/latest/reference/cli/run/#clustering
- `prometheus.scrape` clustering reference: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/#clustering
