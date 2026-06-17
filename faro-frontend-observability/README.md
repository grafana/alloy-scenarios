# Grafana Faro frontend observability

This scenario shows how to collect frontend web telemetry with `faro.receiver` and the [Faro Web SDK](https://github.com/grafana/faro-web-sdk).
The SDK runs in the browser and captures logs, errors, events, and web vitals, then posts them to Alloy on port 12347.
Alloy forwards the received telemetry to Loki.
The `config.alloy` file defines the pipeline.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 3100 for Loki, 8080 for the demo web page, 12345 for the Alloy UI, and 12347 for the Faro receiver free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

The demo page loads the Faro Web SDK in the browser.
The SDK sends telemetry to Alloy's Faro receiver, and Alloy pushes log lines to Loki.

```text
+--------+     +-------------------+     +------+     +---------+
| Browser|     | Alloy             |     | Loki |     | Grafana |
| Faro   |---->| faro.receiver     |---->|:3100 |---->| :3000   |
| SDK    |     | :12347            |     |      |     |         |
+--------+     +-------------------+     +------+     +---------+
     ^
     | nginx serves app/index.html on :8080
```

- **web**: nginx serves the demo frontend on port 8080.
- **Alloy**: Runs `faro.receiver` on port 12347 with CORS enabled and forwards logs to Loki.
- **Loki**: Stores the frontend telemetry.
- **Grafana**: Queries logs through a provisioned Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/faro-frontend-observability`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh faro-frontend-observability`

3. Check that all containers are up: `cd alloy-scenarios/faro-frontend-observability && docker compose ps`

   Expect `web`, `alloy`, `loki`, and `grafana`.

## Explore the services

- **Demo web page** at http://localhost:8080: Frontend with the Faro Web SDK and telemetry buttons.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Faro receiver** at http://localhost:12347/collect: Collection endpoint the browser SDK posts to.
- **Loki** at http://localhost:3100: Log storage backend.
- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.

## Understand the configuration

The `config.alloy` pipeline has two components:

1. **`faro.receiver "default"`**: Listens on `0.0.0.0:12347` for Faro Web SDK payloads with `cors_allowed_origins = ["*"]` and forwards logs to `loki.write.local`.
2. **`loki.write "local"`**: Pushes log lines to Loki at `http://loki:3100/loki/api/v1/push`.

The demo page in `app/index.html` initializes the SDK with `url: 'http://localhost:12347/collect'` and `app.name: 'faro-demo'`.
The Alloy container runs with `--stability.level=experimental` because `faro.receiver` requires experimental stability.
`livedebugging` is enabled.

## Try it out

1. Open the demo web page at http://localhost:8080 and click the buttons to generate telemetry:

   - **Send Log**: pushes an info-level log message
   - **Throw Error**: catches and reports a JavaScript error
   - **Send Event**: sends a custom event with metadata
   - **Unhandled Error**: triggers an uncaught exception that Faro captures automatically

2. Open Grafana **Explore**, select the **Loki** data source, and try this LogQL query:

   - `{service_name="faro-demo"}`: all frontend telemetry from the demo app

3. Open the Alloy UI at http://localhost:12345 and use live debug on `faro.receiver.default` to watch payloads arrive from the browser.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `faro.receiver` reference: https://grafana.com/docs/alloy/latest/reference/components/faro/faro.receiver/
- Faro Web SDK: https://github.com/grafana/faro-web-sdk
