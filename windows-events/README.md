# Windows security event logs

This scenario shows how to collect Windows Security event log entries and forward them to Loki with filtering and field extraction tuned for SOC-style queries.
Alloy runs as a Windows service on the monitored host, drops high-volume noise event IDs, and promotes security fields such as `event_id` and `target_user_name` to labels.
You run Loki and Grafana in Docker on the Windows host or on a separate backend machine, then point `loki.write.endpoint` in `config.alloy` at that backend.

## Before you begin

Ensure you have the following:

- [Git][git] to clone the repository.
- A Windows Server or Windows desktop machine with administrator access.
  `loki.source.windowsevent` reads through the Windows Event Log API and only runs on Windows.
- [Docker Desktop for Windows][docker-desktop] or a Linux machine on the network for the Loki and Grafana backend.
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for the Alloy UI free where you run those services.

[git]: https://git-scm.com/downloads
[docker-desktop]: https://docs.docker.com/desktop/setup/install/windows-install/

## Compare with a related scenario

| Aspect         | [`windows/`](../windows/)                         | `windows-events/`                                           |
| -------------- | ------------------------------------------------- | ----------------------------------------------------------- |
| Channels       | Application, System, and performance metrics      | Security only                                               |
| Processing     | Pass-through with basic JSON parsing              | Drops noise event IDs and extracts security-specific labels |
| Backend        | Loki, Prometheus, and Grafana                     | Loki and Grafana only                                       |
| Scenario focus | General Windows metrics and event logs            | Security audit events for SOC-style queries                 |

Use [`windows/`](../windows/) for general-purpose Windows monitoring with metrics and Application or System logs.
Use this scenario when you specifically need filtered Security channel events with labels for logon, privilege, and account-change queries.

## Understand the architecture

Alloy runs on the Windows host and pushes processed Security events to Loki.
Docker Compose in this directory starts Loki and Grafana only.

```text
+----------------+     +-------+     +------+     +---------+
| Windows host   |     |       |     | Loki |     | Grafana |
| Security event |---->| Alloy |---->|      |---->|         |
| log channel    |     |       |     |      |     |         |
+----------------+     +-------+     +------+     +---------+
```

- **Windows host**: Source of Security channel audit events.
- **Alloy**: Runs as a Windows service with `config.alloy` from this directory.
  The pipeline parses event payloads, drops selected noise event IDs, promotes query labels, and pushes to Loki.
- **Loki**: Stores Security event entries from `loki.write.endpoint`.
- **Grafana**: Anonymous administrator access on port 3000 with a provisioned Loki data source.

## Run the scenario

1. Clone the repository on the machine that hosts the backend:

   ```sh
   git clone https://github.com/grafana/alloy-scenarios.git
   ```

2. Start Loki and Grafana from the scenario directory:

   ```sh
   cd alloy-scenarios/windows-events
   docker compose up -d
   ```

   From the repository root you can also run `./run-example.sh windows-events` to use pinned image versions from `image-versions.env`.

3. Check that the containers are running:

   ```sh
   docker ps
   ```

   Grafana is available at `http://<backend-host>:3000` with the Loki data source already provisioned.

4. Install Alloy on the Windows host.
   Refer to [Install Alloy on Windows](https://grafana.com/docs/alloy/latest/set-up/install/windows/) and install Alloy as a Windows service with the Windows installer.

5. If the backend runs on a different machine than the Windows host, edit the URL in `loki.write.endpoint` in `config.alloy` from `http://localhost:3100/loki/api/v1/push` to `http://<backend-host>:3100/loki/api/v1/push`.

6. Replace the default Alloy configuration:

   - Stop the **Grafana Alloy** Windows service.
   - Copy `alloy-scenarios/windows-events/config.alloy` to `C:\Program Files\GrafanaLabs\Alloy\config.alloy`.
   - Start the **Grafana Alloy** service.

7. Open http://localhost:12345 and confirm `loki.source.windowsevent.security`, `loki.process.security`, and `loki.write.endpoint` load without error.

## Access the services

When the backend runs on a Linux host or another Windows machine, open Grafana at `http://<backend-host>:3000` from your browser.

The Alloy UI listens on the Windows host at http://localhost:12345 by default.
Refer to the [Monitor Windows with Grafana Alloy](../windows/) scenario if you need to expose the Alloy UI to other machines on your network through the Windows service registry arguments.

## Explore the services

- **Grafana** at `http://<backend-host>:3000`: **Explore** for Loki queries, with no login required.
- **Alloy UI** at http://localhost:12345 on the Windows host: Pipeline graph, component health, and live debug views.
- **Loki** at `http://<backend-host>:3100`: Log storage backend.

## Understand the configuration

The `config.alloy` pipeline has three Alloy blocks: `loki.source.windowsevent.security`, `loki.process.security`, and `loki.write.endpoint`.
`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

1. **`loki.source.windowsevent.security`**: Reads the Security event log with `use_incoming_timestamp = true` so entries keep the original event time when Alloy restarts or replays history.
2. **`loki.process.security`**:
   - `stage.json` parses the windowsevent JSON wrapper.
   - `stage.eventlogmessage` extracts fields from the event XML payload.
   - `stage.match` drops event IDs `4658`, `4690`, `4674`, and `5379`.
   - `stage.labels` promotes `event_id`, `subject_user_name`, `target_user_name`, and `logon_type`.
   - `stage.structured_metadata` stores `eventRecordID`, `channel`, and `computer` outside the label index.
3. **`loki.write.endpoint`**: Pushes entries to `http://localhost:3100/loki/api/v1/push`.

**Loki** in `docker-compose.yml` uses `loki-config.yaml` with structured metadata and volume support enabled for the Security pipeline.

**Grafana** provisions Loki at `http://loki:3100` as the default data source through its entrypoint script.

## Try it out

1. Generate Security events on the Windows host so you have data to query:

   - **Failed logon, event ID 4625**: Try to sign in with a wrong password from a remote machine, or run `runas /user:fakeuser cmd` and enter a wrong password.
   - **Successful logon, event ID 4624**: Sign out and back in, or open a new RDP session.
   - **User created, event ID 4720**: Run `net user testuser P@ssw0rd /add` from an admin shell.
   - **Privilege use, event ID 4672**: Run any action that requires Administrator elevation.

   Some events appear only when the matching audit policy is enabled.
   Check `auditpol /get /category:*` on the Windows host.
   Enable additional policies with `auditpol /set /subcategory:"<name>" /success:enable /failure:enable` when you need more event types.

2. Open the Alloy UI at http://localhost:12345 and use live debug on `loki.source.windowsevent.security` to confirm events arrive from the Security channel.

3. Open Grafana at `http://<backend-host>:3000`, go to **Explore**, select the **Loki** data source, and run these queries:

   All Security events:

   ```logql
   {eventlog_name="Security"}
   ```

   Failed logons:

   ```logql
   {eventlog_name="Security", event_id="4625"}
   ```

   Successful logons by a specific user:

   ```logql
   {eventlog_name="Security", event_id="4624", target_user_name="alice"}
   ```

   All events affecting a specific user account:

   ```logql
   {eventlog_name="Security", target_user_name="alice"}
   ```

   Recent privileged-operation events:

   ```logql
   {eventlog_name="Security", event_id=~"4672|4673"}
   ```

   Promoted labels are `event_id`, `subject_user_name`, `target_user_name`, and `logon_type`.
   Fields such as `computer`, `eventRecordID`, and `channel` stay in structured metadata.
   You can still search them with Loki JSON filters without expanding the label index.

## Customize the scenario

- **Restore a dropped event ID**: Edit the `stage.match` selector in `loki.process.security` in `config.alloy` and remove the ID from the `event_id=~"…"` regex.
- **Promote more fields to labels**: Add entries to `stage.labels` in `loki.process.security` when you need additional indexed filters.
- **Point at a remote backend**: Change the URL in `loki.write.endpoint` to match your Loki host.
- **Use pinned image versions**: Run `./run-example.sh windows-events` from the repository root to pick up tags from `image-versions.env`.

## Troubleshoot common problems

Diagnose backend startup failures, missing Security events, audit policy gaps, and port conflicts.

### Backend containers didn't start

Run `docker ps` from the `windows-events` directory.
If a container exited, run `docker compose logs <SERVICE_NAME>` for `grafana` or `loki`.
Confirm Docker is running on the backend host.

### No Security events in Grafana

Check `loki.source.windowsevent.security` in the Alloy UI with live debug.
The Alloy service account must be able to read the Security event log.
Confirm the matching audit policies are enabled with `auditpol /get /category:*`.

### Queries return no results for a specific event ID

Generate the event again with the steps in **Try it out**, then confirm the ID isn't listed in the dropped-event table below.
Remove the ID from `stage.match` in `config.alloy` if you intentionally want to keep it.

### Alloy can't reach Loki

Confirm the URL in `loki.write.endpoint` matches the backend host and that port 3100 is reachable from the Windows host.
Open `http://<backend-host>:3100/ready` from the Windows host when you use a remote backend.

### Port conflicts with other services

Ports 3000 and 3100 must be free on the backend host, and port 12345 must be free on the Windows host for the Alloy UI.
Edit the port mappings in `docker-compose.yml` when another process already uses one of these ports.

## Filtered event IDs

The pipeline drops these event IDs in Alloy before entries reach Loki:

| Event ID | Description                                | Why dropped                                            |
| -------- | ------------------------------------------ | ------------------------------------------------------ |
| 4658     | Handle to an object was closed             | Pairs with 4656 or 4663 and is rarely actionable alone |
| 4690     | Attempt to duplicate a handle to an object | Audit noise                                            |
| 4674     | Operation attempted on a privileged object | Fires for routine privileged operations                |
| 5379     | Credential Manager credentials were read   | Frequent false positive during normal use              |

Edit `stage.match` in `loki.process.security` in `config.alloy` to change this list.

## Stop the scenario

Run `docker compose down -v` from the `windows-events` directory.

Stop the **Grafana Alloy** Windows service separately when you no longer want Alloy to run on the host.

## Next steps

- [`loki.source.windowsevent` reference](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.windowsevent/)
- [`loki.process` reference](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/)
- [`windows/`](../windows/) for Application and System event logs plus Windows performance metrics
- More examples: https://github.com/grafana/alloy-scenarios
