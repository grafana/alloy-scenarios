# systemd journal to Loki — focused filtering recipes

A focused logs-only scenario for shipping a Linux host's systemd journal to Loki, with filtering and label promotion tuned for keeping the index lean and queries fast.

## How this differs from `linux/`

| Aspect | `linux/` (existing) | `systemd-journal/` (this) |
|---|---|---|
| Scope | Metrics + journal + flat files (full Linux observability suite) | **Journal only** — focused scenario |
| Pipeline | Pass-through ingest, all units, all priorities | **Drops noisy units + drops info/debug priorities** |
| Stack | Prom + Loki + Grafana + node_exporter | **Loki + Grafana only** |
| Labels promoted | none specifically | `unit`, `priority`, `hostname` |
| Demo intent | "monitor a Linux box end-to-end" | "show advanced journal filtering recipes" |

If you want general-purpose Linux observability, use `linux/`. If you specifically need journal filtering recipes (drop noisy units, drop low-priority entries, label by unit/priority for fast filtering), this scenario is the minimal moving-parts version.

## Linux host required

`loki.source.journal` reads `/var/log/journal` and `/run/log/journal`. **These directories only exist on Linux hosts running systemd**. On macOS or Windows Docker Desktop:

- The bind mounts will resolve to empty directories (Docker creates them silently).
- Alloy will start cleanly but the source will sit idle with no journal entries.
- The scenario is functionally a no-op — there's no synthesised journal to fall back to.

To exercise the scenario fully you need:
- A Linux host (bare metal, VM, WSL2 with systemd, or a Linux VM on macOS such as OrbStack / Lima / multipass).
- `systemd` writing journals to `/var/log/journal` (persistent) or `/run/log/journal` (volatile). Most distros ship with at least the volatile journal active.

## Running

On a Linux host:

```bash
cd systemd-journal
docker compose up -d
```

Wait ~10 seconds, then open Grafana.

## Accessing

- **Grafana**: http://localhost:3000 (no login required)
- **Alloy UI**: http://localhost:12345 — confirm components are healthy and use livedebugging to inspect entries flowing through each stage
- **Loki API**: http://localhost:3100

## Trying it out

Generate some journal traffic on the Linux host:

```bash
# Trigger a notice
logger -p user.notice "test from systemd-journal scenario"

# Trigger an error
logger -p user.err "this is a test error"

# Tickle a service unit to produce events
sudo systemctl restart cron 2>/dev/null || sudo systemctl restart crond
```

Then in Grafana Explore on Loki:

```logql
# All journal entries (after filtering)
{job="systemd-journal"}

# Errors only
{job="systemd-journal", priority=~"err|crit|alert|emerg"}

# A specific unit
{job="systemd-journal", unit="ssh.service"}

# A specific host (useful when shipping from many)
{job="systemd-journal", hostname="my-server"}

# All recent NetworkManager events
{job="systemd-journal", unit="NetworkManager.service"}
```

## What's filtered out

The pipeline drops these at the Alloy side:

| Filter | What it drops | Why |
|---|---|---|
| `{unit=~"systemd-logind.service\|systemd-tmpfiles-clean.service\|cron.service"}` | Login session housekeeping, tmpfile cleanup, every cron tick | High-volume, low-signal in dev/ops dashboards |
| `{priority=~"info\|debug"}` | LOG_INFO and LOG_DEBUG entries | Keep `notice` and above |

To keep one of these back, edit `stage.match` in `config.alloy` — remove the corresponding entry from the regex.

## Why run Alloy as root

The Alloy container runs with `user: "0:0"`. On most Linux distros, `/var/log/journal/*.journal` files are owned by `root:systemd-journal` with mode 0640. Reading them requires either being root or a member of the `systemd-journal` group. Running Alloy as root inside a container with a read-only bind-mount keeps things simple for a demo. In production, prefer running the Alloy native package as a service — it joins the right groups automatically.

## Stopping

```bash
docker compose down -v
```

## Customization ideas

- **Promote more journal fields**: extend the `loki.relabel.journal` block. `__journal__pid` → `pid`, `__journal__exe` → `exe`, `__journal__cmdline` → `cmdline`, etc.
- **Per-environment unit filters**: maintain different `stage.match` regexes for prod vs dev.
- **Forward errors only**: add a `stage.match` keeping only `priority=~"err|crit|alert|emerg"` if you want a focused error stream.
- **Multi-host fan-in**: deploy this on every Linux host with the same `loki.write` URL pointing at a central Loki cluster.
