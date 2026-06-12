# Monitor Kubernetes metrics with Grafana Alloy and Prometheus

This scenario shows how to collect cluster metrics and scrape annotated Pods with the [Kubernetes Monitoring Helm chart][k8s-monitoring] and forward samples to Prometheus.
You install Prometheus, Grafana, and k8s-monitoring in the `meta` namespace.
Alloy reads `k8s-monitoring-values.yml` instead of your own `config.alloy`.

Alloy collects:

- Cluster metrics from kube-state-metrics, kubelet, cAdvisor, and node exporters
- Pod metrics from Pods with Prometheus-style scrape annotations

The chart also supports logs, profiling, and tracing in other `k8s/` scenarios.
For Pod logs and cluster events, use the [logs scenario](../logs).

[k8s-monitoring]: https://github.com/grafana/k8s-monitoring-helm

## Before you begin

Ensure you have the following:

- [Kind][kind] to create a local Kubernetes cluster.
- [kubectl][kubectl] configured to talk to your cluster.
- [Helm][helm] v3.
- The Grafana and Prometheus Community Helm repositories:

  ```sh
  helm repo add grafana https://grafana.github.io/helm-charts
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
  helm repo update
  ```

- Ports 3000 and 12345 free on your machine for Grafana and Alloy UI port-forwards.

[kind]: https://kind.sigs.k8s.io/docs/user/quick-start/
[kubectl]: https://kubernetes.io/docs/tasks/tools/
[helm]: https://helm.sh/docs/intro/install/

## Compare with the logs scenario

| Aspect           | `k8s/metrics/`                               | `k8s/logs/`                                      |
| ---------------- | -------------------------------------------- | ------------------------------------------------ |
| Alloy deployment | `k8s-monitoring` Helm chart collector preset | `k8s-monitoring` Helm chart collector preset     |
| Backend          | Prometheus                                   | Loki                                             |
| Collectors       | `alloy-metrics`                                | `alloy-logs` and `alloy-singleton`               |
| Scope            | Cluster metrics and annotation autodiscovery   | Pod logs and cluster events in `meta` and `prod` |
| Best for         | Production Kubernetes metrics                | Production Kubernetes logs and events            |

## Understand the architecture

```text
+------------------+     +---------------------------+      +-------------+       +---------+
| Cluster and      |     | k8s-monitoring            | write|             | query |         |
| annotated Pods   |---->| alloy-metrics             |----->| Prometheus  |<------| Grafana |
| in meta          |     |                           |      |             |       |         |
+------------------+     +---------------------------+      +-------------+       +---------+
```

- **Kubernetes cluster**: Supplies kubelet, cAdvisor, and node metrics from the Kind cluster nodes.
- **k8s-monitoring**: Deploys `alloy-metrics` for cluster metrics and annotation-based Pod scraping.
- **Prometheus**: Stores metrics at `prometheus-server.meta.svc.cluster.local`.
- **Grafana**: Queries metrics through a configured Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/k8s/metrics`

3. Create a local Kind cluster with the example configuration in `kind.yml`:

   ```sh
   kind create cluster --config kind.yml
   ```

4. Create the `meta` namespace:

   ```sh
   kubectl create namespace meta
   ```

5. Install Prometheus:

   ```sh
   helm install --values prometheus-values.yml prometheus prometheus-community/prometheus -n meta
   ```

   `prometheus-values.yml` enables the Prometheus remote write receiver and turns off bundled kube-state-metrics and node exporters.
   k8s-monitoring deploys those collectors instead.

6. Install Grafana:

   ```sh
   helm install --values grafana-values.yml grafana grafana/grafana --namespace meta
   ```

   `grafana-values.yml` adds a Prometheus data source in `datasources.datasources.yaml`.

7. Install the Kubernetes Monitoring Helm chart.

   Requires `grafana/k8s-monitoring` chart v4 or later.

   ```sh
   helm install --values ./k8s-monitoring-values.yml k8s grafana/k8s-monitoring --version "^4.0.0" -n meta
   ```

   `k8s-monitoring-values.yml` enables cluster metrics and annotation autodiscovery with the `alloy-metrics` collector.

8. Wait until Pods are ready:

   ```sh
   kubectl get pods -n meta -w
   ```

## Access the services

Grafana and the Alloy UI don't listen on localhost.
Run one port-forward per service in a separate terminal and leave it open until you're done.
The chart creates multiple Alloy Pods. Port-forward the `alloy-metrics` Pod for the metrics pipeline.

- Grafana at http://localhost:3000:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 3000
  ```

- Alloy UI at http://localhost:12345:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-metrics,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 12345
  ```

Run the commands again when you start a new session.

## Explore the services

- **Grafana** at http://localhost:3000: Query metrics in **Explore** with the Prometheus data source.
  Log in as `admin` / `adminadminadmin`. Refer to `grafana-values.yml` for credentials.
- **Alloy UI** at http://localhost:12345: Component graph and live debug views for the `alloy-metrics` collector.
- **Prometheus** at `prometheus-server.meta.svc.cluster.local`: Query through Grafana; Alloy reaches it inside the cluster.

## Understand the k8s-monitoring configuration

The `k8s-monitoring-values.yml` file sets collectors and destinations in chart values instead of `config.alloy`.

- **`destinations.prometheus`**: Remote-writes metrics to `http://prometheus-server.meta.svc.cluster.local:80/api/v1/write`.
- **`clusterMetrics`**: Enables cluster metric collection with kube-state-metrics, kubelet, cAdvisor, and node exporters through the `alloy-metrics` collector.
- **`annotationAutodiscovery`**: Scrapes Pods that carry Prometheus-style scrape annotations through the `alloy-metrics` collector.
- **`collectors`**: Deploys `alloy-metrics` with the `clustered` and `statefulset` presets.
- **`telemetryServices.kube-state-metrics`**: Deploys kube-state-metrics for Kubernetes object metrics.

## Try it out

1. Start the Grafana port-forward, then open http://localhost:3000.

2. In Grafana **Explore**, select the **Prometheus** data source and try these queries:

   - All scrape targets: `up`
   - Container CPU usage: `container_cpu_usage_seconds_total`
   - Container memory usage: `container_memory_working_set_bytes`
   - Pod metadata from kube-state-metrics: `kube_pod_info`

3. Start the Alloy UI port-forward, then open http://localhost:12345.
   Select an `alloy-metrics` collector in the component graph to use live debug.

## Customize the scenario

- **Toggle cluster metrics**: Set `clusterMetrics.enabled` in `k8s-monitoring-values.yml`.
- **Toggle annotation autodiscovery**: Set `annotationAutodiscovery.enabled` in `k8s-monitoring-values.yml`.
- **Point at your own Prometheus**: Update the `destinations.prometheus.url` value in `k8s-monitoring-values.yml` and remove the in-cluster Prometheus Helm release.
- **Scrape a workload**: Add `prometheus.io/scrape: "true"` and `prometheus.io/port` annotations to a Pod or Deployment in `meta`.

After you edit `k8s-monitoring-values.yml`, upgrade the release:

```sh
helm upgrade k8s grafana/k8s-monitoring --version "^4.0.0" -n meta --values k8s-monitoring-values.yml
```

## Troubleshoot common problems

Diagnose Pod startup failures, missing metrics in Grafana, Helm install errors, and port-forward problems.

### Pods didn't start or aren't ready

Run `kubectl get pods -n meta`.
If a Pod isn't running, run `kubectl describe pod <POD_NAME> -n meta`.
For Alloy collectors, check the k8s-monitoring release with `helm status k8s -n meta`.

### No data appears in Grafana after a few minutes

Open the Alloy UI and check that the `alloy-metrics` collector is healthy.
Use live debug to verify samples arrive.
In Grafana, select the **Prometheus** data source in **Explore** and run `up`.
Wait until cluster scrapes complete before you query workload metrics.

### Kubernetes Monitoring Helm chart install failed

Install Prometheus and Grafana before k8s-monitoring.
Requires `grafana/k8s-monitoring` chart v4 or later.
Run `helm list -n meta` to verify the releases.
Wait until the `meta` namespace Pods are ready before you query metrics.

### Port-forward connection refused

Check that the target Pod is `Running`, then rerun the port-forward commands from **Access the services**.
If the Grafana or Alloy Pod restarted, export `POD_NAME` again before you port-forward.

## Stop the scenario

Run `kind delete cluster` to tear down the local Kind cluster and all workloads.

## Next steps

- Kubernetes Monitoring Helm chart: https://github.com/grafana/k8s-monitoring-helm
- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- Prometheus remote write: https://prometheus.io/docs/prometheus/latest/configuration/configuration/#remote_write
- Logs scenario: [Monitor Kubernetes logs with Grafana Alloy and Loki](../logs)
- More examples: https://github.com/grafana/alloy-scenarios
