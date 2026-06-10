# Alloy clustering (multi-node consistent-hashed scrape)

Run a **three-node Grafana Alloy cluster** that shares a pool of scrape targets.
With clustering enabled, the cluster uses consistent hashing to assign each target
to exactly one node, so each node scrapes roughly **1/3** of the targets. Stop a
node and its targets are automatically redistributed to the survivors within
seconds — no gaps, no duplicate scrapes, no manual sharding.

This is how Alloy scales metric collection horizontally. Grafana runs the same
pattern to scrape [nearly 20M Prometheus
metrics](https://grafana.com/blog/how-we-use-grafana-alloy-clustering-to-scrape-nearly-20m-prometheus-metrics/).

## What this scenario demonstrates

- Forming an Alloy cluster with the `--cluster.*` command-line flags (gossip over
  the HTTP port).
- Opting a `prometheus.scrape` component into clustering so targets are sharded
  across nodes (`clustering { enabled = true }`).
- Discovering a dynamic pool of targets with `discovery.docker` — every node sees
  the same targets and hashes them identically, which is what makes the sharding
  consistent.
- **Failover:** killing a node redistributes its targets to the rest of the
  cluster automatically.

## Architecture

```
                    ┌───────────────────────────────────────────┐
                    │            Alloy cluster (gossip)           │
   9 node-exporter  │   ┌─────────┐   ┌─────────┐   ┌─────────┐   │
   "target"         │   │ alloy-1 │◀─▶│ alloy-2 │◀─▶│ alloy-3 │   │
   containers  ─────┼──▶│ ~3 tgts │   │ ~3 tgts │   │ ~3 tgts │   │
   (discovered via  │   └────┬────┘   └────┬────┘   └────┬────┘   │
    discovery.docker)│       │             │             │        │
                    └────────┼─────────────┼─────────────┼────────┘
                             └─────────────┴─────────────┘
                                           │ remote_write
                                           ▼
                                     ┌────────────┐     ┌─────────┐
                                     │ Prometheus │────▶│ Grafana │
                                     └────────────┘     └─────────┘
```

Each Alloy node discovers all nine `target` containers but, thanks to clustering,
only **scrapes the subset assigned to it**. Every sample is stamped with a
`scraped_by` label (the node's hostname) so you can watch the distribution shift.

## Prerequisites

- Docker
- Docker Compose v2+ — the target pool is scaled with `deploy.replicas`, which
  `docker compose up` honors on v2 and newer (legacy `docker-compose` v1 ignores
  it; on v1, scale the pool with `docker compose up -d --scale target=9` instead).

## Running the demo

### Step 1: Clone the repository

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/alloy-clustering
```

### Step 2: Start the stack

```bash
docker compose up -d
```

This starts Prometheus, Grafana, nine `node-exporter` scrape targets, and three
Alloy nodes (`alloy-1`, `alloy-2`, `alloy-3`).

### Step 3: Confirm the cluster formed

Open the Alloy **Clustering** page on any node and you should see all three peers
listed as participants:

- alloy-1: <http://localhost:12345/clustering>
- alloy-2: <http://localhost:12346/clustering>
- alloy-3: <http://localhost:12347/clustering>

### Step 4: Open the dashboard

Go to Grafana at <http://localhost:3000> (no login required) and open the
**Alloy clustering** dashboard. You should see:

- **Targets scraped per Alloy node** — three bands of roughly equal height,
  summing to nine.
- **Targets monitored** — a steady `9`.
- **Alloy nodes scraping** — `3`.
- **Current target ownership** — a table mapping each target to its owning node.

## Try it: failover

Stop one node and watch its targets move to the survivors:

```bash
docker compose stop alloy-2
```

- **Within seconds:** the cluster reassigns `alloy-2`'s targets to `alloy-1` and
  `alloy-3`, which begin scraping them right away — confirm the new ownership on
  each node's Clustering page. **Targets monitored** never leaves `9`, so no
  target is ever dropped.
- **Over the next minute:** as `alloy-2`'s now-stale `up` series age out of the
  Prometheus lookback window, **Targets scraped per Alloy node** reattributes its
  share to the survivors — `alloy-2`'s band falls to zero while the `alloy-1` and
  `alloy-3` bands grow to absorb it. The stacked total stays pinned at `9` the
  whole time (no target is double-counted mid-handover), and **Alloy nodes
  scraping** falls to `2`.

Bring the node back and the cluster rebalances again:

```bash
docker compose start alloy-2
```

`alloy-2` rejoins the gossip ring within roughly 20 seconds and reclaims about a
third of the targets.

> The dashboard sets Prometheus `--query.lookback-delta=1m` so a stopped node's
> stale series clear in about a minute instead of the default five. The cluster
> hands the targets to the survivors within seconds, but the departed node's band
> only falls to zero once its last samples age out of that window.

## How it works

Clustering is enabled per node with command-line flags in `docker-compose.yml`:

```
run
  --cluster.enabled=true
  --cluster.join-addresses=alloy-1:12345,alloy-2:12345,alloy-3:12345
  ...
```

`--cluster.enabled` turns on the gossip-based cluster (which reuses the HTTP port,
`12345`). `--cluster.join-addresses` lists every peer so the cluster forms
regardless of startup order. Each node's name defaults to its hostname
(`alloy-1`, `alloy-2`, `alloy-3`).

Enabling clustering on the collector is only half of it — components must **opt
in**. In `config.alloy`, the scrape component does so:

```alloy
prometheus.scrape "clustered" {
  targets    = discovery.relabel.targets.output
  forward_to = [prometheus.remote_write.default.receiver]

  clustering {
    enabled = true
  }
}
```

With the block present, the cluster hashes the target set onto a ring of nodes and
each node scrapes only the targets it owns. Because all nodes share the same
Docker socket and therefore discover the same targets, every node computes the
same ring and the same ownership — that consistency is what prevents both gaps and
double scraping.

## Endpoints

| Service | URL |
| ------- | --- |
| Grafana | <http://localhost:3000> |
| Prometheus | <http://localhost:9090> |
| alloy-1 UI | <http://localhost:12345> |
| alloy-2 UI | <http://localhost:12346> |
| alloy-3 UI | <http://localhost:12347> |

## Scaling the target pool

Change the number of synthetic targets to see the distribution adjust. Edit
`deploy.replicas` for the `target` service in `docker-compose.yml` (for example to
`18`) and re-apply:

```bash
docker compose up -d
```

`discovery.docker` picks up the new containers on its next refresh and the cluster
reshards them across the three nodes.

> On a recent Docker Compose you can do this in one line without editing the file:
> `docker compose up -d --scale target=18` (this overrides `deploy.replicas`).

## Cleanup

```bash
docker compose down
```
