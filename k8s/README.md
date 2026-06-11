
# Monitor Kubernetes Grafana Alloy

> Note this scenario works using the K8s Monitoring Helm chart. This abstracts the need to configure Loki and deploys best practices for monitoring Kubernetes clusters. The chart supports; metrics, logs, profiling, and tracing.

In this directory you will find a series of scenarios that demonstrate how to setup Alloy via the Kubernetes monitoring helm chart. Examples specific to each telemetry source are provided in the respective directories.

| Scenario | Description |
| --- | --- |
| [Logs](./logs) | Monitor Kubernetes logs with Grafana Alloy and Loki |
| [Metrics](./metrics) | Monitor Kubernetes metrics with Grafana Alloy and Prometheus |
| [Profiling](./profiling) | Monitor Kubernetes profiling with Grafana Alloy and Pyroscope |
| [Tracing](./tracing) | Monitor Kubernetes tracing with Grafana Alloy and Tempo |
| [kube-state-metrics + cAdvisor](./kube-state-metrics-cadvisor) | Scrape kube-state-metrics and the kubelet cAdvisor endpoint with a standalone Alloy DaemonSet — no k8s-monitoring chart |

