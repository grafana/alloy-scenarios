# Probe resources with Grafana Alloy as the blackbox prober

This scenario shows how Alloy runs `prometheus.exporter.blackbox` as a blackbox prober and `prometheus.operator.probes` discovers and scrapes Prometheus Operator `Probe` resources that target it. Alloy collects probe metrics and forwards them to Prometheus.

The key to this setup is the `spec.prober` configuration in the Probe resource: the `path` must point to the Alloy component API path ending in `/probe` (probe metrics), not `/metrics` (exporter operational metrics). Alloy's HTTP server is exposed on port `12345` by default.

[Probe]: https://github.com/prometheus-operator/prometheus-operator

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

- Ports 12345 and 9090 free on your machine for Alloy UI and Prometheus port-forwards.

[kind]: https://kind.sigs.k8s.io/docs/user/quick-start/
[kubectl]: https://kubernetes.io/docs/tasks/tools/
[helm]: https://helm.sh/docs/intro/install/

## Understand the architecture

```text
+------------------+     +---------------------------+      +----------+       +---------+
| Probe resources  |     | Alloy                     | write|          | query |         |
| in testns        |---->| blackbox_exporter +       |----->|Prometheus|<------| Grafana |
|                  |     | operator.probes + write   |      |          |       |         |
+------------------+     +---------------------------+      +----------+       +---------+
```

- **Kubernetes API**: Serves Probe resources from the `testns` namespace.
- **Alloy**: Runs `prometheus.exporter.blackbox` as the HTTP prober and `prometheus.operator.probes` to discover and scrape Probe resources, then forwards metrics via `prometheus.remote_write`.
- **Prometheus**: Stores metrics sent from Alloy.
- **Grafana**: Queries metrics through Prometheus.

This scenario uses two key Alloy components to bridge Prometheus Operator and blackbox probing:

- `prometheus.exporter.blackbox`: Embeds the blackbox_exporter and exposes an HTTP endpoint for probing targets.
- `prometheus.operator.probes`: Discovers Probe resources from the Kubernetes API and scrapes them, forwarding metrics to a receiver.
- `prometheus.remote_write`: Sends metrics to Prometheus via the remote write API.

The Probe resource references Alloy's HTTP server by service name and port, then specifies the path to the blackbox exporter component inside Alloy. Alloy scrapes the probes on the interval defined in each Probe resource and forwards the results upstream.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/k8s/prometheus-operator-probes`

3. Create a Kind cluster:

   ```sh
   kind create cluster --config kind.yml
   ```

4. Create the `meta` and `testns` namespaces:

   ```sh
   kubectl create namespace meta
   kubectl create namespace testns
   ```

5. Install the Prometheus Operator CRDs (includes the `Probe` resource type):

   ```sh
   helm install prometheus-operator-crds prometheus-community/prometheus-operator-crds -n meta
   ```

6. Install Prometheus with the remote-write receiver enabled:

   ```sh
   helm install prometheus prometheus-community/prometheus -n meta \
     --set server.remoteWriteReceiver.enabled=true \
     --set alertmanager.enabled=false \
     --set kube-state-metrics.enabled=false \
     --set prometheus-node-exporter.enabled=false \
     --set prometheus-pushgateway.enabled=false
   ```

7. Install Alloy with the config from this directory:

   ```sh
   helm install alloy grafana/alloy -n meta \
     --set-file alloy.configMap.content=config.alloy \
     --set controller.type=deployment \
     --set service.enabled=true
   ```

8. Apply the Probe resource:

   ```sh
   kubectl apply -f probe.yaml
   ```

9. Wait until Pods are ready:

   ```sh
   kubectl get pods -n meta -w
   ```

## Access the services

Alloy and Prometheus don't listen on localhost.
Run one port-forward per service in a separate terminal and leave it open until you're done.

- Alloy UI at http://localhost:12345:

  ```sh
  kubectl -n meta port-forward svc/alloy 12345:12345
  ```

- Prometheus at http://localhost:9090:

  ```sh
  kubectl -n meta port-forward svc/prometheus-server 9090:80
  ```

Run the port-forward commands again when you start a new session.

## Explore the services

- **Alloy UI** at http://localhost:12345: Component graph and live debug views for the `prometheus.exporter.blackbox.blackbox_exporter` and `prometheus.operator.probes.blackbox` components.
- **Prometheus** at http://localhost:9090: Query probe metrics such as `probe_success` and `probe_duration_seconds` in **Explore**.

## Understand the configuration

The `config.alloy` file contains three components:

- **`prometheus.exporter.blackbox.blackbox_exporter`**: Embeds the blackbox_exporter and exposes an HTTP endpoint configured with the `http_2xx` module for HTTP probing with a 5-second timeout.
- **`prometheus.operator.probes.blackbox`**: Discovers Probe resources in the `testns` namespace and forwards probe results to the remote write receiver.
- **`prometheus.remote_write.local`**: Sends probe metrics to the Prometheus remote-write endpoint at `http://prometheus-server.meta.svc.cluster.local/api/v1/write`.

The Probe resource in `probe.yaml` specifies:

- **`url`**: `alloy.meta.svc.cluster.local:12345` — the Alloy service and HTTP listen port.
- **`path`**: `/api/v0/component/prometheus.exporter.blackbox.blackbox_exporter/probe` — the internal API path to access the blackbox exporter component's probe endpoint.
- **`targets`**: `https://grafana.com` — the target URL to probe.
- **`module`**: `http_2xx` — the blackbox module to use.
- **`interval`**: `30s` — how often to run the probe.

## Try it out

1. Check that both components are healthy in the Alloy UI:

   - Navigate to http://localhost:12345
   - The component graph shows `prometheus.exporter.blackbox.blackbox_exporter` and `prometheus.operator.probes.blackbox` in green (healthy)

2. Query probe results in Prometheus:

   - Navigate to http://localhost:9090
   - Run the query: `probe_success{job="blackbox"}`
   - The result should show a value of `1` (success) for the probe of `https://grafana.com`

3. Inspect probe details:

   - Run the query: `probe_duration_seconds{job="blackbox"}`
   - This shows how long each probe took

4. Check the Alloy debug endpoint to see discovered Probe resources:

   - The Alloy UI shows the debug information for `prometheus.operator.probes.blackbox` under the **Debug** tab

## Customize the scenario

- **Add more probe targets**: Edit `probe.yaml` to add additional `targets` or create new Probe resources in the `testns` namespace.
- **Change the blackbox module**: Edit the `config` in `prometheus.exporter.blackbox.blackbox_exporter` in `config.alloy` to add modules like `http_post_2xx` or `tcp_connect`. Refer to the [blackbox_exporter configuration documentation](https://github.com/prometheus/blackbox_exporter/blob/master/example.yml).
- **Scope to specific namespaces**: Add `namespaces = ["meta", "testns"]` to `prometheus.operator.probes.blackbox` in `config.alloy` to limit Probe discovery to certain namespaces.
- **Change the probe interval**: Edit `interval: 30s` in `probe.yaml` to run probes more or less frequently.
- **Point at your own Prometheus**: Update the `prometheus.remote_write.local` endpoint URL in `config.alloy` and remove the in-cluster Prometheus Helm release.

After you edit `config.alloy` or `probe.yaml`, reapply them and restart Alloy:

```sh
kubectl apply -f config.alloy probe.yaml
kubectl rollout restart deployment/alloy -n meta
```

## Troubleshoot common problems

Diagnose Probe discovery failures, missing probe metrics in Prometheus, Alloy component health issues, and port-forward problems.

### Probes not appearing in Prometheus

Check that the `testns` namespace exists: `kubectl get namespace testns`.
Verify the Probe resource was created: `kubectl get probe -n testns`.
Check the Alloy logs for permission errors: `kubectl logs -n meta -l app.kubernetes.io/name=alloy`.
Ensure the Alloy service is accessible: `kubectl get svc -n meta alloy`.

### Component shows as unhealthy in the Alloy UI

Check the Alloy logs: `kubectl logs -n meta -l app.kubernetes.io/name=alloy`.
Verify that the Probe resources are in the `testns` namespace: `kubectl get probe -n testns`.
Inspect the component configuration in `config.alloy` to ensure `prometheus.operator.probes.blackbox` references the correct namespace.

### Metrics not reaching Prometheus

Verify that Prometheus has the remote-write receiver enabled: `kubectl get statefulset -n meta prometheus`.
Check that Prometheus is receiving metrics: query `up{job="blackbox"}` in **Explore**.
Inspect the `prometheus.remote_write.local` configuration in `config.alloy` for the correct endpoint URL.

## Stop the scenario

Run `kind delete cluster` to tear down the local Kind cluster and all workloads.

## Next steps

- Prometheus Operator: https://github.com/prometheus-operator/prometheus-operator
- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- `prometheus.operator.probes`: https://grafana.com/docs/alloy/latest/reference/components/prometheus.operator.probes/
- `prometheus.exporter.blackbox`: https://grafana.com/docs/alloy/latest/reference/components/prometheus.exporter.blackbox/
- Prometheus remote write: https://prometheus.io/docs/prometheus/latest/configuration/configuration/#remote_write
- More examples: https://github.com/grafana/alloy-scenarios
