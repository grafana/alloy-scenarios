# Windows Security Event Logs with Grafana Alloy

A focused logs-only scenario for shipping the **Windows Security event channel** to Loki, with filtering and field-extraction tuned for SOC-style queries (logon attempts, privilege escalation, account changes).

## How this differs from the [`windows/`](../windows/) scenario

| Aspect | `windows/` (broad) | `windows-events/` (this) |
|---|---|---|
| Channels | Application + System + Performance metrics | **Security** only |
| Processing | Pass-through with basic JSON parsing | **Drops noise event IDs** + extracts security-specific fields as labels |
| Backend | Loki + Prometheus + Grafana | **Loki + Grafana** (no metrics) |
| Demo intent | "ship Windows logs to Loki" | "make Security events queryable for SOC use cases" |

If you want general-purpose Windows monitoring, use `windows/`. If you specifically care about Security audit events, use this one.

## Prerequisites

- A Windows host (Server or Desktop) with admin access — `loki.source.windowsevent` reads from the Windows Event Log API and only runs on Windows.
- Docker Desktop for Windows (or any Linux machine you can reach over the network) for the Loki/Grafana backend.
- Git, to clone the repo.

## Step 1 — Backend (Loki + Grafana)

On the machine that will host the backend (the Windows host itself, or any Linux machine):

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/windows-events
docker compose up -d
```

Grafana is on `http://<backend-host>:3000` with the Loki datasource already provisioned.

## Step 2 — Install Alloy on the Windows host

Follow the [Windows install guide](https://grafana.com/docs/alloy/latest/set-up/install/windows/). Recommended: Windows Installer + Windows Service.

If your backend is on a different machine than the Windows host, edit the `loki.write` URL in `config.alloy` from `http://localhost:3100` to `http://<backend-host>:3100`.

## Step 3 — Replace the Alloy config

1. Stop the `Grafana Alloy` Windows service.
2. Replace `C:\Program Files\GrafanaLabs\Alloy\config.alloy` with the [`config.alloy`](./config.alloy) from this directory.
3. Start the service.
4. Open `http://localhost:12345` to confirm the components load without error.

## Step 4 — Generate Security events

To see traffic, trigger some auditable actions on the Windows host:

- **Failed logon (4625)**: try to log in with a wrong password from a remote machine, or run `runas /user:fakeuser cmd` and enter a wrong password.
- **Successful logon (4624)**: log out and back in, or open a new RDP session.
- **User created (4720)**: `net user testuser P@ssw0rd /add` from an admin shell.
- **Privilege use (4672)**: any action requiring Administrator elevation.

Some of these only generate events if the corresponding **audit policy** is enabled. Check `auditpol /get /category:*` on the Windows host; enable additional audit policies via `auditpol /set /subcategory:"<name>" /success:enable /failure:enable` if needed.

## Step 5 — Query in Grafana

```logql
# All Security events
{eventlog_name="Security"}

# Failed logons
{eventlog_name="Security", event_id="4625"}

# Successful logons by a specific user
{eventlog_name="Security", event_id="4624", target_user_name="alice"}

# All events affecting a specific user account
{eventlog_name="Security", target_user_name="alice"}

# Recent privileged-operation events
{eventlog_name="Security", event_id=~"4672|4673"}
```

The promoted labels are `event_id`, `subject_user_name`, `target_user_name`, and `logon_type`. Other event fields (computer, eventRecordID, channel) are kept as **structured metadata** — searchable via Loki's `| json` filter without inflating the label index.

## What's filtered out

The pipeline drops these event IDs at the Alloy side:

| Event ID | Description | Why dropped |
|---|---|---|
| 4658 | Handle to an object was closed | Pairs with 4656/4663; on its own rarely actionable |
| 4690 | Attempt to duplicate a handle to an object | Audit noise |
| 4674 | Operation attempted on a privileged object | Fires for routine privileged ops |
| 5379 | Credential Manager credentials were read | Frequent false-positive in normal use |

If you want one of these back, edit `stage.match` in `config.alloy` to remove the corresponding ID from the `event_id=~"…"` regex.

## Stopping

```bash
docker compose down -v
```

Stop the Alloy Windows service separately if you no longer want it running.
