# Monitor Kubernetes logs with Grafana Alloy and Loki

This scenario shows how to collect Pod logs and Kubernetes cluster events with the [Kubernetes Monitoring Helm chart][k8s-monitoring] and forward them to Loki.
You install Loki, Grafana, and k8s-monitoring in the `meta` namespace.
Alloy reads `k8s-monitoring-values.yml` instead of your own `config.alloy`.

Alloy collects from the `meta` and `prod` namespaces:

- Pod logs through the Kubernetes API
- Kubernetes cluster events

The chart also supports metrics, profiling, and tracing in other `k8s/` scenarios.
For cluster events with plain manifests, use the [events scenario](../events).

[k8s-monitoring]: https://github.com/grafana/k8s-monitoring-helm

## Before you begin

Ensure you have the following:

- [Kind][kind] to create a local Kubernetes cluster.
- [kubectl][kubectl] configured to talk to your cluster.
- [Helm][helm] v3.
- The Grafana Helm repository:

  ```sh
  helm repo add grafana https://grafana.github.io/helm-charts
  helm repo update
  ```

- Ports 3000 and 12345 free on your machine for Grafana and Alloy UI port-forwards.

[kind]: https://kind.sigs.k8s.io/docs/user/quick-start/
[kubectl]: https://kubernetes.io/docs/tasks/tools/
[helm]: https://helm.sh/docs/intro/install/

## Compare with the events scenario

| Aspect                          | `k8s/logs/`                                  | `k8s/events/`                                                             |
| ------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------- |
| Alloy deployment                | `k8s-monitoring` Helm chart collector preset | Plain `kubectl apply` of ConfigMap, RBAC, and Deployment                  |
| `loki.source.kubernetes_events` | Hidden inside the chart                      | In `alloy-config.yaml`                                                    |
| Scope                           | Pod logs and cluster events                  | Cluster events only with `type`, `reason`, `namespace`, and `kind` labels |
| Best for                        | Production Kubernetes monitoring             | Learn or extend the events collector                                      |

## Understand the architecture

```text
+------------------+     +---------------------------+      +------+       +---------+
| Pods and         |     | k8s-monitoring            | push |      | query |         |
| cluster events   |---->| alloy-logs +              |----->| Loki |<------| Grafana |
| in meta and prod |     | alloy-singleton           |      |      |       |         |
+------------------+     +---------------------------+      +------+       +---------+
```

- **Kubernetes API**: Supplies Pod logs and cluster events from the `meta` and `prod` namespaces.
- **k8s-monitoring**: Deploys `alloy-logs` for Pod logs and `alloy-singleton` for cluster events.
- **Loki**: Stores log entries at `loki-gateway.meta.svc.cluster.local`.
- **Grafana**: Queries logs through a configured Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/k8s/logs`

3. Create a local Kind cluster:

   ```sh
   kind create cluster --config kind.yml
   ```

4. Create the `meta` and `prod` namespaces:

   ```sh
   kubectl create namespace meta && \
   kubectl create namespace prod
   ```

5. Install Loki:

   ```sh
   helm install --values loki-values.yml loki grafana/loki -n meta
   ```

   `loki-values.yml` sets `deploymentMode: SingleBinary`.
   Refer to the [Loki deployment modes documentation](https://grafana.com/docs/loki/latest/get-started/deployment-modes/).

6. Install Grafana:

   ```sh
   helm install --values grafana-values.yml grafana grafana/grafana --namespace meta
   ```

   `grafana-values.yml` adds a Loki data source in `datasources.datasources.yaml`.

7. Install the Kubernetes Monitoring Helm chart.

   Requires `grafana/k8s-monitoring` chart v4 or later.

   ```sh
   helm install --values ./k8s-monitoring-values.yml k8s grafana/k8s-monitoring --version "^4.0.0" -n meta --create-namespace
   ```

   `k8s-monitoring-values.yml` enables Pod log and cluster event collection in `meta` and `prod`.

8. Wait until Pods are ready:

   ```sh
   kubectl get pods -n meta -w
   ```

## Access the services

Grafana and the Alloy UI don't listen on localhost.
Run one port-forward per service in a separate terminal and leave it open until you're done.
The chart creates multiple Alloy Pods. Port-forward the `alloy-logs` Pod for the Pod log pipeline.

- Grafana at http://localhost:3000:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 3000
  ```

- Alloy UI at http://localhost:12345 for Pod logs:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-logs,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 12345
  ```

- Alloy UI for cluster events: port-forward the `alloy-singleton` Pod instead when you want to debug the events pipeline:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-singleton,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 12345
  ```

Run the commands again when you start a new session.

## Explore the services

- **Grafana** at http://localhost:3000: Query logs in **Explore** with the Loki data source.
  Log in as `admin` / `adminadminadmin`. Refer to `grafana-values.yml` for credentials.
- **Alloy UI** at http://localhost:12345: Component graph and live debug views for the `alloy-logs` collector.
- **Loki** at `loki-gateway.meta.svc.cluster.local`: Query through Grafana; Alloy reaches it inside the cluster.
- **Explore Logs** at http://localhost:3000/a/grafana-lokiexplore-app

## Understand the k8s-monitoring configuration

The `k8s-monitoring-values.yml` file sets collectors and destinations in chart values instead of `config.alloy`.

- **`destinations.loki`**: Sends telemetry to `http://loki-gateway.meta.svc.cluster.local/loki/api/v1/push`.
- **`clusterEvents`**: Enables cluster event collection with the `alloy-singleton` collector in the `meta` and `prod` namespaces.
- **`podLogsViaKubernetesApi`**: Enables Pod log collection with the `alloy-logs` collector in the `meta` and `prod` namespaces.
  Sets `structuredMetadata` with `pod: pod` on Pod log entries.
- **`collectors`**: Deploys `alloy-singleton` with the `singleton` preset and `alloy-logs` with the `clustered` preset.

## Try it out

1. Start the Grafana port-forward, then open http://localhost:3000.

2. Open Explore Logs at http://localhost:3000/a/grafana-lokiexplore-app to browse logs without queries.

3. Add a demo app in the `prod` namespace:

   Install Tempo distributed tracing in `prod` to generate Pod logs:

   ```sh
   helm install tempo grafana/tempo-distributed -n prod
   ```

4. Start the Alloy UI port-forward for `alloy-logs`, then open http://localhost:12345.
   Select an `alloy-logs` collector in the component graph to use live debug for Pod logs.
   Port-forward `alloy-singleton` instead if you want to inspect the cluster events pipeline.

## Customize the scenario

- **Change collected namespaces**: Edit the `namespaces` lists under `clusterEvents` and `podLogsViaKubernetesApi` in `k8s-monitoring-values.yml`.
- **Adjust Pod log metadata**: Edit the `structuredMetadata` block under `podLogsViaKubernetesApi` in `k8s-monitoring-values.yml`.
- **Point at your own Loki**: Update the `destinations.loki.url` value in `k8s-monitoring-values.yml` and remove the in-cluster Loki Helm release.
- **Add demo workloads**: Install additional Helm releases in `prod` to generate Pod logs, similar to the Tempo example in **Try it out**.

After you edit `k8s-monitoring-values.yml`, upgrade the release:

```sh
helm upgrade k8s grafana/k8s-monitoring --version "^4.0.0" -n meta --values k8s-monitoring-values.yml
```

## Troubleshoot common problems

Diagnose Pod startup failures, missing logs in Grafana, Helm install errors, and port-forward problems.

### Pods didn't start or aren't ready

Run `kubectl get pods -n meta`.
If a Pod isn't running, run `kubectl describe pod <POD_NAME> -n meta`.
For Alloy collectors, check the k8s-monitoring release with `helm status k8s -n meta`.

### No data appears in Grafana after a few minutes

Open the Alloy UI and check that the `alloy-logs` collector is healthy.
Use live debug to verify logs arrive.
In Grafana, select the **Loki** data source in **Explore** or open Explore Logs.
If `prod` is empty, install a demo workload with the command in **Try it out**.

### Kubernetes Monitoring Helm chart install failed

Install Loki and Grafana before k8s-monitoring.
Requires `grafana/k8s-monitoring` chart v4 or later.
Run `helm list -n meta` to verify the releases.
Wait until the `meta` namespace Pods are ready before you query logs.

### Port-forward connection refused

Check that the target Pod is `Running`, then rerun the port-forward commands from **Access the services**.
If the Grafana or Alloy Pod restarted, export `POD_NAME` again before you port-forward.

## Stop the scenario

Run `kind delete cluster` to tear down the local Kind cluster and all workloads.

## Next steps

- Kubernetes Monitoring Helm chart: https://github.com/grafana/k8s-monitoring-helm
- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- Loki deployment modes: https://grafana.com/docs/loki/latest/get-started/deployment-modes/
- Events scenario: [Collect Kubernetes events with Grafana Alloy](../events)
- More examples: https://github.com/grafana/alloy-scenarios
