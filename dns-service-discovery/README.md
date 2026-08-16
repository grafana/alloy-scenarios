# Discover Prometheus targets through DNS SRV records

This scenario shows how Alloy discovers scrape targets from DNS instead of a static target list.
CoreDNS serves two SRV records for demo exporters; Alloy resolves them with `discovery.dns`, adds a stable job label with `discovery.relabel`, then scrapes both targets and remote-writes the samples to Prometheus.

## Before you begin

Ensure that [Docker][docker] and [Docker Compose][docker-compose] are installed, and that ports 3000, 9090, and 12345 are free.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

```text
                  SRV records
+---------+  _metrics._tcp.demo.local  +-------+  scrape  +------------+     +---------+
| CoreDNS |--------------------------->| Alloy |--------->| Prometheus |<----| Grafana |
+---------+                            +---+---+          +------------+     +---------+
                                           |
                                  discovers two exporters
                                  +--------+ +--------+
                                  |   A    | |   B    |
                                  +--------+ +--------+
```

CoreDNS returns `exporter-a.demo.local:8000` and `exporter-b.demo.local:8000` for `_metrics._tcp.demo.local`.
The exporters use fixed addresses only inside this isolated Compose network so the zone file is deterministic; real deployments would point DNS records at their own hosts.

## Run the scenario

From the repository root, use either command:

```sh
cd dns-service-discovery
docker compose up -d
```

```sh
./run-example.sh dns-service-discovery
cd dns-service-discovery
```

Verify all services are running:

```sh
docker compose ps
```

## Explore the discovered targets

Open Grafana at http://localhost:3000 or Prometheus at http://localhost:9090 and run:

```promql
up{job="dns-service-discovery"}
```

Expect two healthy time series. To see the exporter identities, run:

```promql
dns_discovery_demo_info{job="dns-service-discovery"}
```

The Alloy UI at http://localhost:12345 shows the targets flowing through `discovery.dns.metrics`, `discovery.relabel.metrics`, and `prometheus.scrape.metrics`.

## Customize the DNS records

Edit `db.demo.local` to change SRV targets, then restart CoreDNS:

```sh
docker compose restart coredns
```

Alloy refreshes DNS every five seconds. In a production environment, replace the demo zone with the DNS service already used by your VM or service-discovery platform.

## Troubleshoot

If only one or no targets appear, inspect the DNS and Alloy logs:

```sh
docker compose logs coredns alloy
```

Confirm the SRV records use a trailing dot on the target host names and that the SRV port matches the exporters' listening port.
If `up` is `0`, ensure the discovered host names resolve to reachable addresses in the same network as Alloy.

## Stop the scenario

Run this from the scenario directory:

```sh
docker compose down
```

## Next steps

- [`discovery.dns` reference](https://grafana.com/docs/alloy/latest/reference/components/discovery/discovery.dns/)
- [`discovery.relabel` reference](https://grafana.com/docs/alloy/latest/reference/components/discovery/discovery.relabel/)
- [`prometheus.scrape` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/)
