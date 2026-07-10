# Azure Event Hubs logs

This scenario shows how to ingest Azure Event Hubs messages with `loki.source.azure_event_hubs`.
Azure Diagnostic Settings stream Activity Log records to an event hub in production, and this scenario emulates that producer with a small script.
You don't need an Azure subscription.
Alloy consumes the event hub's Kafka-compatible endpoint and forwards each record to Loki as a log line.
The `config.alloy` file defines the pipeline.
Complexity: medium.

## Why this scenario doesn't use the official emulator

Microsoft ships an official Event Hubs emulator (`mcr.microsoft.com/azure-messaging/eventhubs-emulator`) for offline development, and this scenario originally tried it.
`loki.source.azure_event_hubs` connects to Event Hubs over its Kafka-compatible endpoint, and both of the component's authentication mechanisms hardcode TLS on that Kafka connection.
The official emulator's Kafka port only speaks plaintext `SASL_PLAINTEXT` — it doesn't terminate TLS at all.
Pointing Alloy at the emulator fails immediately: Alloy's TLS handshake bytes reach a plaintext listener, and the emulator resets the connection.

Since there's no way to disable TLS on `loki.source.azure_event_hubs`, this scenario runs a self-hosted single-node Kafka broker (the `eventhub` service) configured to speak the exact wire protocol Azure Event Hubs uses on its real Kafka endpoint: TLS with SASL PLAIN authentication, using the literal username `$ConnectionString` that real Event Hubs also expects.
A `cert-init` step generates a throwaway CA and certificate so the broker has something to terminate TLS with, and Alloy trusts that CA before it starts.
The result behaves identically to a real Event Hubs namespace's Kafka endpoint from Alloy's point of view, without needing an Azure subscription or the official emulator.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

A generator script produces fake Azure Activity Log records and publishes them to a self-hosted broker that speaks the same protocol as Azure Event Hubs' Kafka endpoint. Alloy consumes them and forwards parsed log lines to Loki.

```text
+--------------+  produce   +-----------+  consume   +----------------------------+  push  +------+  query  +---------+
| log-producer |----------->| eventhub  |<-----------| loki.source.azure_event_hubs |------>| Loki |<--------| Grafana |
+--------------+            +-----------+            +----------------------------+        +------+         +---------+
```

- **cert-init** generates a throwaway CA, a TLS certificate for the `eventhub` broker, and a truststore, then writes them to a shared volume. It runs once and exits.
- **eventhub** is a single-node Kafka broker (KRaft mode) with a `SASL_SSL` listener. It requires SASL PLAIN authentication with username `$ConnectionString`, matching real Azure Event Hubs' Kafka endpoint.
- **topic-init** pre-creates the `insights-activity-logs` topic with two partitions, then exits.
- **log-producer** generates a fake Activity Log JSON record every three seconds and publishes it to `insights-activity-logs`.
- **Alloy** trusts the `cert-init` CA, then runs `loki.source.azure_event_hubs` to consume `insights-activity-logs` and forward records to `loki.write.local`.
- **Loki** stores the log lines.
- **Grafana** queries logs with a provisioned Loki data source.

Each Activity Log record carries `resourceId`, `operationName`, `category`, `resultType`, `level`, and `correlationId` fields, matching the shape of a real Azure Activity Log entry.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/azure-event-hubs-logs`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh azure-event-hubs-logs`

3. Check that all containers are up: `cd alloy-scenarios/azure-event-hubs-logs && docker compose ps`

   Expect `eventhub`, `log-producer`, `alloy`, `loki`, and `grafana` running, with `cert-init` and `topic-init` exited (they're one-shot setup steps).

   If `eventhub` restarts once before it reports healthy, that's expected. Kafka's own SASL_SSL self-check occasionally races with KRaft's combined broker and controller bootstrap on a cold start, and it always succeeds on retry. The `restart: on-failure` policy handles this automatically.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Loki** at http://localhost:3100: Log storage backend.

The `eventhub` broker doesn't expose a host port. Only containers on the compose network talk to it.

## Understand the configuration

The `config.alloy` pipeline has two components:

1. **`loki.source.azure_event_hubs "activity_logs"`**: Connects to `eventhub:9093`, consumes the `insights-activity-logs` event hub with consumer group `$Default`, authenticates with the `connection_string` mechanism, and forwards records to `loki.write.local`.
2. **`loki.write "local"`**: Pushes log lines to Loki at `http://loki:3100/loki/api/v1/push`.

The `connection_string` argument holds whatever value the broker's SASL PLAIN password check expects — in production, this is your real Event Hubs namespace connection string. Here it's a fixed placeholder value that the self-hosted broker matches.
`livedebugging` is enabled.

## Try it out

1. Wait about ten seconds after bring-up for the producer to publish its first records and for Alloy to consume them.

2. Open Grafana **Explore**, select the **Loki** data source, and try these LogQL queries:

   - `{job="loki.source.azure_event_hubs"}`: all records consumed from the event hub
   - `{job="loki.source.azure_event_hubs"} | json | category="Administrative"`: administrative operations only
   - `{job="loki.source.azure_event_hubs"} | json | level="Error"`: error-level records
   - `{job="loki.source.azure_event_hubs"} | json | resultType="Failure"`: failed operations

3. Open the Alloy UI at http://localhost:12345 and use live debug on `loki.source.azure_event_hubs.activity_logs` to watch records flow through the pipeline.

## Customize the scenario

To point this scenario at a real Azure Event Hubs namespace instead of the self-hosted broker:

1. Remove the `cert-init`, `eventhub`, `topic-init`, and `log-producer` services from `docker-compose.yml`, along with the `eh-certs` volume and the CA-trust step in the `alloy` service's entrypoint.
2. Update `config.alloy`:

   ```alloy
   loki.source.azure_event_hubs "activity_logs" {
   	fully_qualified_namespace = "<your-namespace>.servicebus.windows.net:9093"
   	event_hubs                = ["<your-event-hub-name>"]
   	forward_to                = [loki.write.local.receiver]

   	authentication {
   		mechanism = "oauth"
   	}
   }
   ```

   Use `mechanism = "connection_string"` with a real `connection_string` argument instead of `oauth` if you'd rather authenticate with a shared access key.

3. If you use `oauth`, make sure the Alloy host has Azure AD credentials available, for example through a managed identity or `az login`.

The `loki.write` block stays the same for the self-hosted broker and real Event Hubs.

## Troubleshoot common problems

Use these steps when logs don't appear or ports conflict.

### No logs appear in Grafana after 30 seconds

Check that `log-producer` is running with `docker compose ps`. Read its output with `docker compose logs log-producer` — it should print `>` prompts from `kafka-console-producer.sh` with no errors.
Check that `eventhub` reports healthy with `docker compose ps`.
Open the Alloy UI at http://localhost:12345 and check that `loki.source.azure_event_hubs.activity_logs` is healthy and consuming.

### The eventhub container keeps restarting

One restart on cold start is expected — refer to [Run the scenario](#run-the-scenario). If it restarts more than two or three times, check `docker compose logs eventhub` for the underlying error and check that `cert-init` exited successfully (`docker compose ps cert-init`) before `eventhub` started.

### Port conflicts with other services

Ports 3000, 3100, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Differences from real Azure Event Hubs

This scenario emulates Azure Event Hubs' Kafka wire protocol rather than using a real namespace.
A few things work differently from production:

- **Authentication**: Real Event Hubs validates the SAS key in your connection string against the namespace's actual access policy. The self-hosted broker only checks that the password matches a fixed placeholder value, so any connection string with the right shape "works."
- **Single broker, single namespace**: Real Event Hubs runs as a managed, multi-tenant service with per-namespace throughput units and multiple partitions replicated across the service. The self-hosted broker is one container with one topic and two partitions.
- **TLS trust**: Real Event Hubs presents a certificate signed by a public CA that your OS already trusts. This scenario generates its own CA and certificate on every `docker compose up`, and installs that CA into the Alloy container's trust store — that step isn't needed against real Event Hubs.
- **Why any of this exists**: `loki.source.azure_event_hubs` hardcodes TLS with no argument to disable it. The official Azure Event Hubs emulator's Kafka listener doesn't support TLS, so it can't stand in for a real namespace with this component. The self-hosted broker exists specifically to give the component something that speaks Azure Event Hubs' actual wire protocol without needing a real Azure subscription.

## Stop the scenario

Run `docker compose down` from the scenario directory.
Run `docker compose down -v` to also remove the generated certificates, so the next `docker compose up` regenerates them.

## Next steps

- `loki.source.azure_event_hubs` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.azure_event_hubs/
- Amazon Data Firehose logs scenario: [../aws-firehose-logs/](../aws-firehose-logs/) — another scenario that emulates a cloud log-delivery producer without a real cloud account
- Kafka logs scenario: [../kafka/](../kafka/) — a plaintext Kafka pipeline with `loki.source.kafka`
