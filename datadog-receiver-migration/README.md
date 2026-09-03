# datadog-receiver-migration

This scenario demonstrates a migration path from Datadog to Grafana Alloy using the `otelcol.receiver.datadog` component. It allows teams to put Alloy in place of, or in front of, the Datadog Agent, forwarding Datadog format metrics and traces to Prometheus and Tempo without requiring a Datadog account or vendor lock-in.

## What is demonstrated
* Using `otelcol.receiver.datadog` to ingest Datadog Agent metrics and traces.
* Forwarding Datadog metrics to Prometheus using `otelcol.exporter.prometheus`.
* Forwarding Datadog traces to Tempo using `otelcol.exporter.otlp`.

## Architecture
1. **Generator**: A Python application using DogStatsD and `ddtrace` to generate traces and metrics.
2. **Datadog Agent**: Receives metrics and traces from the generator and forwards them to Alloy instead of Datadog HQ.
3. **Grafana Alloy**: Acts as the backend for the Datadog Agent, receiving its payloads via `otelcol.receiver.datadog` and exporting them to Prometheus and Tempo.
4. **Prometheus & Tempo**: Store the metrics and traces respectively.
5. **Grafana**: Visualizes the stored data.

## Running the scenario
1. Start the environment:
   ```bash
   docker compose up -d
   ```
2. Open Grafana at http://localhost:3000
3. Navigate to Explore to see the Datadog traces in Tempo and the `example_work_count` / `example_work_duration` metrics in Prometheus.
4. Clean up the environment:
   ```bash
   docker compose down -v
   ```
