# Monitor Kubernetes traces with Grafana Alloy and Tempo

This scenario shows how to collect distributed traces with the [Kubernetes Monitoring Helm chart][k8s-monitoring] and forward them to Tempo.
You install Tempo, Grafana, and k8s-monitoring in the `meta` namespace.
Alloy reads `k8s-monitoring-values.yml` instead of your own `config.alloy`.

Applications in the cluster send traces to Alloy's OTLP endpoint on ports 4317 for gRPC and 4318 for HTTP.
Alloy forwards them to Tempo.

The chart also supports logs, metrics, and profiling in other `k8s/` scenarios.
For Pod logs and cluster events, use the [logs scenario](../logs).

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

## Compare with the logs scenario

| Aspect           | `k8s/tracing/`                               | `k8s/logs/`                                      |
| ---------------- | -------------------------------------------- | ------------------------------------------------ |
| Alloy deployment | `k8s-monitoring` Helm chart collector preset | `k8s-monitoring` Helm chart collector preset     |
| Backend          | Tempo                                        | Loki                                             |
| Collectors       | `alloy-receiver`                             | `alloy-logs` and `alloy-singleton`               |
| Scope            | OTLP traces from applications                | Pod logs and cluster events in `meta` and `prod` |
| Best for         | Distributed application tracing              | Production Kubernetes logs and events            |

## Understand the architecture

```text
+------------------+     +---------------------------+      +-------+       +---------+
| Applications in  |     | k8s-monitoring            | OTLP |       | query |         |
| meta and prod    |---->| alloy-receiver            |----->| Tempo |<------| Grafana |
|                  |     |                           |      |       |       |         |
+------------------+     +---------------------------+      +-------+       +---------+
```

- **Applications**: Send OTLP traces to the `alloy-receiver` collector in `meta`.
- **k8s-monitoring**: Deploys `alloy-receiver` to accept gRPC and HTTP OTLP and forward traces to Tempo.
- **Tempo**: Stores traces at `tempo.meta.svc.cluster.local`.
- **Grafana**: Queries traces through a configured Tempo data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/k8s/tracing`

3. Create a local Kind cluster:

   ```sh
   kind create cluster --config kind.yml
   ```

4. Create the `meta` and `prod` namespaces:

   ```sh
   kubectl create namespace meta && \
   kubectl create namespace prod
   ```

5. Install Tempo:

   ```sh
   helm install --values tempo-values.yml tempo grafana/tempo -n meta
   ```

   `tempo-values.yml` enables OTLP receivers and local trace storage for a single-binary deployment.

6. Install Grafana:

   ```sh
   helm install --values grafana-values.yml grafana grafana/grafana --namespace meta
   ```

   `grafana-values.yml` adds a Tempo data source in `datasources.datasources.yaml`.

7. Install the Kubernetes Monitoring Helm chart.

   Requires `grafana/k8s-monitoring` chart v4 or later.

   ```sh
   helm install --values ./k8s-monitoring-values.yml k8s grafana/k8s-monitoring --version "^4.0.0" -n meta
   ```

   `k8s-monitoring-values.yml` enables application observability with the `alloy-receiver` collector.
   Alloy receives OTLP traces on ports 4317 for gRPC and 4318 for HTTP, then forwards them to Tempo.

8. Wait until Pods are ready:

   ```sh
   kubectl get pods -n meta -w
   ```

## Access the services

Grafana and the Alloy UI don't listen on localhost.
Run one port-forward per service in a separate terminal and leave it open until you're done.
The chart creates multiple Alloy Pods. Port-forward the `alloy-receiver` Pod for the trace pipeline.

- Grafana at http://localhost:3000:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 3000
  ```

- Alloy UI at http://localhost:12345:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-receiver,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 12345
  ```

Run the port-forward commands again when you start a new session.

## Explore the services

- **Grafana** at http://localhost:3000: Query traces in **Explore** with the Tempo data source.
  Log in as `admin` / `adminadminadmin`. Refer to `grafana-values.yml` for credentials.
- **Alloy UI** at http://localhost:12345: Component graph and live debug views for the `alloy-receiver` collector.
- **Tempo** at `tempo.meta.svc.cluster.local`: Query through Grafana; Alloy reaches it inside the cluster.

## Understand the k8s-monitoring configuration

The `k8s-monitoring-values.yml` file sets collectors and destinations in chart values instead of `config.alloy`.

- **`destinations.tempo`**: Sends traces over OTLP to `http://tempo.meta.svc.cluster.local:4317`.
- **`applicationObservability`**: Enables the `alloy-receiver` collector for application traces.
- **`applicationObservability.receivers.otlp`**: Turns on gRPC and HTTP OTLP receivers on the Alloy receiver.
- **`collectors`**: Deploys `alloy-receiver` with the `deployment` preset.

## Try it out

1. Start the Grafana port-forward, then open http://localhost:3000.

2. Deploy a workload in `prod` to generate traces.

   Install Tempo distributed as an example workload:

   ```sh
   helm install tempo-distributed grafana/tempo-distributed -n prod
   ```

   This chart doesn't send application traces to Alloy by default.
   Point any OpenTelemetry-instrumented app at the Alloy OTLP endpoint in **Customize the scenario**, or configure the demo workload to export traces there.

3. After a workload exports OTLP traces to Alloy, open Grafana **Explore**, select the **Tempo** data source, and search with TraceQL:

   - All traces: `{}`
   - Filter by service name: `{resource.service.name="my-service"}`
   - Error traces: `{status=error}`

4. Start the Alloy UI port-forward, then open http://localhost:12345.
   Select an `alloy-receiver` collector in the component graph to use live debug.

## Customize the scenario

- **Toggle application observability**: Set `applicationObservability.enabled` in `k8s-monitoring-values.yml`.
- **Point at your own Tempo**: Update the `destinations.tempo.url` value in `k8s-monitoring-values.yml` and remove the in-cluster Tempo Helm release.
- **Send traces from your apps**: Set the OTLP exporter endpoint on instrumented workloads.
  Use gRPC on port 4317 or HTTP on port 4318:

  ```text
  OTEL_EXPORTER_OTLP_ENDPOINT=http://k8s-alloy-receiver.meta.svc.cluster.local:4317
  OTEL_EXPORTER_OTLP_PROTOCOL=grpc
  ```

  For HTTP OTLP, use port 4318 and set `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`.

- **Add demo workloads**: Install additional Helm releases in `prod`, similar to the Tempo distributed example in **Try it out**.

After you edit `k8s-monitoring-values.yml`, upgrade the release:

```sh
helm upgrade k8s grafana/k8s-monitoring --version "^4.0.0" -n meta --values ./k8s-monitoring-values.yml
```

## Troubleshoot common problems

Diagnose Pod startup failures, missing traces in Grafana, Helm install errors, and port-forward problems.

### Pods didn't start or aren't ready

Run `kubectl get pods -n meta`.
If a Pod isn't running, run `kubectl describe pod <POD_NAME> -n meta`.
For Alloy collectors, check the k8s-monitoring release with `helm status k8s -n meta`.

### No data appears in Grafana after a few minutes

Open the Alloy UI and check that the `alloy-receiver` collector is healthy.
Use live debug to verify traces arrive.
In Grafana, select the **Tempo** data source in **Explore** and run `{}`.
If no traces appear, verify a workload exports OTLP to the Alloy receiver endpoint from **Customize the scenario**.

### Kubernetes Monitoring Helm chart install failed

Install Tempo and Grafana before k8s-monitoring.
Requires `grafana/k8s-monitoring` chart v4 or later.
Run `helm list -n meta` to verify the releases.
Wait until the `meta` namespace Pods are ready before you query traces.

### Port-forward connection refused

Check that the target Pod is `Running`, then rerun the port-forward commands from **Access the services**.
If the Grafana or Alloy Pod restarted, export `POD_NAME` again before you port-forward.

## Stop the scenario

Run `kind delete cluster` to tear down the local Kind cluster and all workloads.

## Next steps

- Kubernetes Monitoring Helm chart: https://github.com/grafana/k8s-monitoring-helm
- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- Tempo documentation: https://grafana.com/docs/tempo/latest/
- Logs scenario: [Monitor Kubernetes logs with Grafana Alloy and Loki](../logs)
- More examples: https://github.com/grafana/alloy-scenarios
