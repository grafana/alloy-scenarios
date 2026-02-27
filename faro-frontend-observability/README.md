# Faro Frontend Observability

This scenario demonstrates collecting frontend web telemetry using Grafana Alloy's `faro.receiver` component and the [Grafana Faro Web SDK](https://github.com/grafana/faro-web-sdk).

The Faro Web SDK runs in the browser and captures logs, errors, events, and web vitals, then sends them to Alloy's Faro receiver endpoint. Alloy forwards the collected telemetry to Loki for storage and querying.

## Architecture

```
Browser (Faro Web SDK) --> Alloy (faro.receiver :12347) --> Loki (:3100)
                                                                |
                                                           Grafana (:3000)
```

## Getting Started

1. Start all services:

```bash
docker compose up -d
```

2. Open the demo web page at [http://localhost:8080](http://localhost:8080).

3. Click the buttons to generate telemetry:
   - **Send Log** -- pushes an info-level log message
   - **Throw Error** -- catches and reports a JavaScript error
   - **Send Event** -- sends a custom event with metadata
   - **Unhandled Error** -- triggers an uncaught exception (automatically captured by Faro)

4. View the collected telemetry in Grafana:
   - Open [http://localhost:3000](http://localhost:3000)
   - Go to **Explore** and select the **Loki** datasource
   - Query with `{service_name="faro-demo"}` to see all frontend telemetry

## Services

| Service | URL | Description |
|---------|-----|-------------|
| Web (nginx) | [http://localhost:8080](http://localhost:8080) | Demo frontend page with Faro Web SDK |
| Alloy | [http://localhost:12345](http://localhost:12345) | Alloy UI for pipeline debugging |
| Alloy Faro Receiver | `http://localhost:12347/collect` | Faro SDK collection endpoint |
| Loki | [http://localhost:3100](http://localhost:3100) | Log aggregation backend |
| Grafana | [http://localhost:3000](http://localhost:3000) | Visualization and querying |

## Alloy Pipeline

The `config.alloy` pipeline is straightforward:

1. **`faro.receiver`** -- listens on port 12347 for Faro Web SDK payloads with CORS enabled for all origins
2. **`loki.write`** -- forwards the received logs to Loki

## Cleanup

```bash
docker compose down
```
