# Monitor Kubernetes with Grafana Alloy

> **Note**
>
> The logs, metrics, profiling, and tracing scenarios use the Kubernetes Monitoring Helm chart.
> The chart deploys Grafana Alloy with recommended collectors so you don't configure Alloy by hand.
> The chart supports metrics, logs, profiling, and tracing.
> The Events scenario uses plain Kubernetes manifests instead.

This directory contains scenarios that show how to collect telemetry from Kubernetes with Grafana Alloy.
Each subdirectory focuses on one telemetry type.

| Scenario                 | Description                                                                          |
| ------------------------ | ------------------------------------------------------------------------------------ |
| [Events](./events)       | Collect Kubernetes cluster events with Grafana Alloy and Loki using plain manifests. |
| [Logs](./logs)           | Collect Kubernetes logs with Grafana Alloy and Loki.                                 |
| [Metrics](./metrics)     | Collect Kubernetes metrics with Grafana Alloy and Prometheus.                        |
| [Profiling](./profiling) | Collect Kubernetes profiles with Grafana Alloy and Pyroscope.                        |
| [Tracing](./tracing)     | Collect Kubernetes traces with Grafana Alloy and Tempo.                              |
