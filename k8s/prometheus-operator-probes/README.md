# Probe resources with Alloy as the blackbox prober

This scenario shows how `prometheus.operator.probes` scrapes [Prometheus Operator][prom-op] `Probe` resources when Alloy also runs `prometheus.exporter.blackbox` as the prober.

The important detail is `spec.prober`:

- `url` is Alloy's HTTP listen address (default port `12345`)
- `path` is the component API path ending in `/probe` (probe metrics), not `/metrics` (exporter operational metrics)

[prom-op]: https://github.com/prometheus-operator/prometheus-operator

## Before you begin

- [Kind](https://kind.sigs.k8s.io/), [kubectl](https://kubernetes.io/docs/tasks/tools/), and [Helm](https://helm.sh/docs/intro/install/) v3
- Helm repos:

  ```sh
  helm repo add grafana https://grafana.github.io/helm-charts
  helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
  helm repo update
  ```

## Run the scenario

1. Create a Kind cluster:

   ```sh
   kind create cluster --config kind.yml
   ```

2. Create namespaces:

   ```sh
   kubectl create namespace meta
   kubectl create namespace testns
   ```

3. Install the Prometheus Operator CRDs (includes `Probe`):

   ```sh
   helm install prometheus-operator-crds prometheus-community/prometheus-operator-crds -n meta
   ```

4. Install a small Prometheus with remote-write receiver enabled:

   ```sh
   helm install prometheus prometheus-community/prometheus -n meta \
     --set server.remoteWriteReceiver.enabled=true \
     --set alertmanager.enabled=false \
     --set kube-state-metrics.enabled=false \
     --set prometheus-node-exporter.enabled=false \
     --set prometheus-pushgateway.enabled=false
   ```

5. Install Alloy with the config from this directory:

   ```sh
   helm install alloy grafana/alloy -n meta \
     --set-file alloy.configMap.content=config.alloy \
     --set controller.type=deployment \
     --set service.enabled=true
   ```

6. Apply the Probe resource:

   ```sh
   kubectl apply -f probe.yaml
   ```

7. Port-forward Alloy UI and Prometheus if you want to inspect:

   ```sh
   kubectl -n meta port-forward svc/alloy 12345:12345
   kubectl -n meta port-forward svc/prometheus-server 9090:80
   ```

## What to look for

- Alloy UI at http://localhost:12345 should show `prometheus.exporter.blackbox.blackbox_exporter` and `prometheus.operator.probes.blackbox` healthy.
- Prometheus should receive series such as `probe_success` for the `https://grafana.com` target.
- If `spec.prober.path` points at `/metrics` instead of `/probe`, you get exporter process metrics, not blackbox probe results.

## Clean up

```sh
kind delete cluster
```
