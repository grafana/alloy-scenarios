# Filter systemd journal logs

This scenario forwards a Linux host systemd journal to Loki with filtering and label promotion tuned for lean indexes and fast queries.
It focuses on journal ingestion only.
The broader [`linux/`](../linux/) scenario covers full Linux observability with metrics, flat files, and pass-through journal ingest.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- A **Linux host** running systemd.
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

### Linux host required

`loki.source.journal` reads `/var/log/journal`.
That path only exists on Linux hosts running systemd.
On macOS or Windows Docker Desktop:

- The bind mounts resolve to empty directories.
  Docker creates them silently.
- Alloy starts cleanly, but the source sits idle with no journal entries.
- The scenario is functionally a no-op.
  There is no synthesized journal to fall back to.

To exercise the scenario fully you need:

- A Linux host, such as bare metal, a VM, WSL2 with systemd, or a Linux VM on macOS through OrbStack, Lima, or multipass.
- `systemd` writing journals to `/var/log/journal` or `/run/log/journal`.
  Most distros ship with at least the volatile journal active.
  The checked-in `config.alloy` sets `path = "/var/log/journal"`.
  On volatile-only hosts, point `path` at `/run/log/journal` instead.

### How this differs from `linux/`

| Aspect          | `linux/`                                       | `systemd-journal/`                             |
| --------------- | ---------------------------------------------- | ---------------------------------------------- |
| Scope           | Metrics, journal, and flat files               | Journal only                                   |
| Pipeline        | Pass-through ingest, all units, all priorities | Drops noisy units and info or debug priorities |
| Stack           | Prometheus, Loki, Grafana, and `node_exporter` | Loki, Grafana, and Alloy                       |
| Labels promoted | none specifically                              | `unit`, `priority`, `hostname`                 |
| Demo intent     | Monitor a Linux box end to end                 | Show journal filtering recipes                 |

Use [`linux/`](../linux/) for general-purpose Linux observability.
Use this scenario when you need focused journal filtering with fewer moving parts.

## Understand the architecture

```text
+-------------+     +-------+     +------+     +---------+
| systemd     |     |       |     | Loki |     | Grafana |
| journal     |---->| Alloy |---->|      |---->|         |
+-------------+     +-------+     +------+     +---------+
```

- **systemd journal**: Host journal at `/var/log/journal`, bind-mounted read-only into the Alloy container.
- **Alloy**: Runs `config.alloy` as root so it can read journal files.
  `loki.source.journal` ingests entries, `loki.process` drops noisy units and low-priority messages, and `loki.write` sends logs to Loki.
  Live debugging is enabled.
- **Loki**: Stores logs at `http://loki:3100/loki/api/v1/push`.
- **Grafana**: Queries Loki through a provisioned data source with anonymous administrator access enabled.

## Run the scenario

On a Linux host:

1. Clone the repository: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Go to the scenario: `cd alloy-scenarios/systemd-journal`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh systemd-journal`

   **Option 3: From the scenario directory with pinned versions**

   - Deploy the scenario: `docker compose --env-file ../image-versions.env up -d`

3. From the `systemd-journal` directory, check that all containers are up: `docker compose ps`

   Expect `alloy`, `loki`, and `grafana`.
   Wait about 10 seconds before you open Grafana.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** with the Loki data source.
  You don't need to log in.
- **Alloy UI** at http://localhost:12345: Component graph for `loki.source.journal`, `loki.process`, and `loki.write`.
  Live debugging is enabled in `config.alloy`.
- **Loki** at http://localhost:3100: Journal logs from Alloy.

## Understand the Alloy pipeline

`config.alloy` defines the pipeline:

1. **`loki.relabel`**: Promotes journal metadata to Loki labels `unit`, `priority`, and `hostname`.
2. **`loki.source.journal`**: Reads `/var/log/journal` with a 12 hour `max_age`, applies relabel rules, and sets `job=systemd-journal`.
3. **`loki.process`**: Drops selected noisy units and info or debug priority entries.
4. **`loki.write`**: Sends logs to `http://loki:3100/loki/api/v1/push`.

### What gets filtered out

The `loki.process` block drops two groups of entries:

- **Noisy units** (`{unit=~"systemd-logind.service|systemd-tmpfiles-clean.service|cron.service"}`): Login session housekeeping, tmpfile cleanup, and every cron tick.
  High-volume, low-signal in dev or ops dashboards.
- **Low priorities** (`{priority=~"info|debug"}`): LOG_INFO and LOG_DEBUG entries.
  Keeps `notice` and above.

To keep one of these streams, edit `stage.match` in `loki.process` in `config.alloy` and remove the corresponding entry from the regular expression.

### Why Alloy runs as root

The Alloy container runs with `user: "0:0"`.
On most Linux distros, `/var/log/journal/*.journal` files are owned by `root:systemd-journal` with mode 0640.
Reading them requires root or membership in the `systemd-journal` group.
Running Alloy as root inside a container with a read-only bind mount keeps the demo simple.
In production, prefer the Alloy native package as a service.
It joins the right groups automatically.

## Try it out

1. Generate journal traffic on the Linux host:

   ```bash
   logger -p user.notice "test from systemd-journal scenario"
   logger -p user.err "this is a test error"
   sudo systemctl restart cron 2>/dev/null || sudo systemctl restart crond
   ```

2. Open Grafana at http://localhost:3000 and go to **Explore**.

   Select the **Loki** data source and run these LogQL queries:

   - `{job="systemd-journal"}`: All journal entries after filtering
   - `{job="systemd-journal", priority=~"err|crit|alert|emerg"}`: Errors only
   - `{job="systemd-journal", unit="ssh.service"}`: A specific unit
   - `{job="systemd-journal", hostname="my-server"}`: A specific host when you forward from many hosts
   - `{job="systemd-journal", unit="NetworkManager.service"}`: Recent NetworkManager events

3. Open the Alloy UI at http://localhost:12345.

   Navigate to the component graph to verify the path from `loki.source.journal` through `loki.process` to `loki.write`.
   Use live debugging to inspect entries flowing through each stage.

## Customize the scenario

- **Promote more journal fields**: Extend the `loki.relabel.journal` block.
  Map `__journal__pid` to `pid`, `__journal__exe` to `exe`, or `__journal__cmdline` to `cmdline`.
- **Per-environment unit filters**: Maintain different `stage.match` regular expressions for prod and dev.
- **Forward errors only**: Add a `stage.match` block that keeps only `priority=~"err|crit|alert|emerg"`.
- **Multi-host fan-in**: Deploy this on every Linux host with the same `loki.write` URL pointing at a central Loki cluster.

## Troubleshoot common problems

This section covers startup failures, missing logs, and port conflicts.

### Containers didn't start or exited unexpectedly

Run `docker compose ps` to check the status of each container.
If any container has exited, run `docker compose logs <SERVICE_NAME>` to read the failure reason.
Replace `<SERVICE_NAME>` with the name of the service that exited, such as `alloy` or `loki`.

### No journal entries in Loki

Confirm you're on a Linux host with an active systemd journal.
Check that `/var/log/journal` contains journal files on the host.
If your distro uses the volatile journal only, set `path = "/run/log/journal"` in `loki.source.journal` in `config.alloy`.
In Grafana **Explore**, run `{job="systemd-journal"}` against the **Loki** data source.

### Port conflicts with other services

Ports 3000, 3100, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port map in `docker-compose.yml` for the conflicting service before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down -v` from the `systemd-journal` directory.

## Next steps

- Alloy `loki.source.journal` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.journal/
- Full Linux observability: [`linux/`](../linux/)
- More examples: https://github.com/grafana/alloy-scenarios
