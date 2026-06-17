# Monitor Kubernetes profiles with Grafana Alloy and Pyroscope

This scenario shows how to collect continuous profiles from annotated Pods with the [Kubernetes Monitoring Helm chart][k8s-monitoring] and forward them to Pyroscope.
You install Pyroscope, Grafana, and k8s-monitoring in the `meta` namespace.
Alloy reads `k8s-monitoring-values.yml` instead of your own `config.alloy`.

Alloy discovers Pods with profiling annotations and scrapes their pprof endpoints for CPU, memory, goroutine, and other profile types.

The chart also supports logs, metrics, and tracing in other `k8s/` scenarios.
For cluster and workload metrics, use the [metrics scenario](../metrics).

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

## Compare with the metrics scenario

| Aspect           | `k8s/profiling/`                             | `k8s/metrics/`                                   |
| ---------------- | -------------------------------------------- | ------------------------------------------------ |
| Alloy deployment | `k8s-monitoring` Helm chart collector preset | `k8s-monitoring` Helm chart collector preset     |
| Backend          | Pyroscope                                    | Prometheus                                       |
| Collectors       | `alloy-profiles`                             | `alloy-metrics`                                  |
| Scope            | pprof profiles from annotated Pods in `meta` | Cluster metrics and annotation autodiscovery     |
| Best for         | Continuous application profiling             | Production Kubernetes metrics                    |

## Understand the architecture

```text
+------------------+     +---------------------------+      +----------+       +---------+
| Annotated Pods   |     | k8s-monitoring            | push |          | query |         |
| with pprof in    |---->| alloy-profiles            |----->| Pyroscope|<------| Grafana |
| meta             |     |                           |      |          |       |         |
+------------------+     +---------------------------+      +----------+       +---------+
```

- **Annotated Pods**: Expose pprof endpoints for CPU, memory, and goroutine profiles.
- **k8s-monitoring**: Deploys `alloy-profiles` to discover and scrape annotated Pods.
- **Pyroscope**: Stores profiles at `pyroscope.meta.svc.cluster.local:4040`.
- **Grafana**: Queries profiles through the Pyroscope data source and the Pyroscope app.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/k8s/profiling`

3. Create a local Kind cluster:

   ```sh
   kind create cluster --config kind.yml
   ```

4. Create the `meta` namespace:

   ```sh
   kubectl create namespace meta
   ```

5. Install Pyroscope:

   ```sh
   helm install --values pyroscope-values.yml pyroscope grafana/pyroscope -n meta
   ```

   `pyroscope-values.yml` sets a 5-minute max block duration and resource requests for the Pyroscope server.

6. Install Grafana:

   ```sh
   helm install --values grafana-values.yml grafana grafana/grafana --namespace meta
   ```

   `grafana-values.yml` adds the Pyroscope data source and installs the `grafana-pyroscope-app` plugin.

7. Install the Kubernetes Monitoring Helm chart.

   Requires `grafana/k8s-monitoring` chart v4 or later.

   ```sh
   helm install --values ./k8s-monitoring-values.yml k8s grafana/k8s-monitoring --version "^4.0.0" -n meta
   ```

   `k8s-monitoring-values.yml` enables pprof profiling with the `alloy-profiles` collector.

8. Wait until Pods are ready:

   ```sh
   kubectl get pods -n meta -w
   ```

## Access the services

Grafana and the Alloy UI don't listen on localhost.
Run one port-forward per service in a separate terminal and leave it open until you're done.
The chart creates multiple Alloy Pods. Port-forward the `alloy-profiles` Pod for the profiling pipeline.

- Grafana at http://localhost:3000:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 3000
  ```

- Alloy UI at http://localhost:12345:

  ```sh
  export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-profiles,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
  kubectl --namespace meta port-forward $POD_NAME 12345
  ```

Run the port-forward commands again when you start a new session.

## Explore the services

- **Grafana** at http://localhost:3000: Open the **Pyroscope** app or query profiles in **Explore** with the Pyroscope data source.
  Log in as `admin` / `adminadminadmin`. Refer to `grafana-values.yml` for credentials.
- **Pyroscope app** at http://localhost:3000/a/grafana-pyroscope-app/explore: Browse profiles without writing queries.
- **Alloy UI** at http://localhost:12345: Component graph and live debug views for the `alloy-profiles` collector.
- **Pyroscope** at `pyroscope.meta.svc.cluster.local:4040`: Query through Grafana; Alloy reaches it inside the cluster.

## Understand the k8s-monitoring configuration

The `k8s-monitoring-values.yml` file sets collectors and destinations in chart values instead of `config.alloy`.

- **`destinations.pyroscope`**: Sends profiles to `http://pyroscope.meta.svc.cluster.local:4040`.
- **`profiling`**: Enables pprof profile collection with the `alloy-profiles` collector.
- **`profiling.pprof`**: Turns on pprof endpoint scraping for annotated Pods.
- **`collectors`**: Deploys `alloy-profiles` with the `privileged` and `daemonset` presets.

## Try it out

1. Start the Grafana port-forward, then open http://localhost:3000.

2. Deploy Pyroscope's demo Ride Share app in `meta` to generate profiles:

   ```sh
   kubectl apply -n meta -f - <<EOF
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: ride-share-go
   spec:
     replicas: 1
     selector:
       matchLabels:
         app: ride-share-go
     template:
       metadata:
         labels:
           app: ride-share-go
         annotations:
           profiles.grafana.com/memory.scrape: "true"
           profiles.grafana.com/memory.port: "6060"
           profiles.grafana.com/cpu.scrape: "true"
           profiles.grafana.com/cpu.port: "6060"
           profiles.grafana.com/goroutine.scrape: "true"
           profiles.grafana.com/goroutine.port: "6060"
       spec:
         containers:
         - name: ride-share-go
           image: grafana/pyroscope-rideshare-go:latest
           ports:
           - containerPort: 5000
             name: http
           - containerPort: 6060
             name: pprof
           env:
           - name: REGION
             value: us-east-1
   EOF
   ```

   Wait until the Pod is ready:

   ```sh
   kubectl get pods -n meta -l app=ride-share-go -w
   ```

3. Open the Pyroscope app at http://localhost:3000/a/grafana-pyroscope-app/explore, or select the **Pyroscope** data source in **Explore**.
   You can view these profile types:

   - CPU profiles: flame graphs that show where CPU time is spent
   - Memory profiles: heap allocation and usage
   - Goroutine profiles: concurrent goroutine analysis

4. Start the Alloy UI port-forward, then open http://localhost:12345.
   Select an `alloy-profiles` collector in the component graph to use live debug.

## Customize the scenario

- **Toggle profiling**: Set `profiling.enabled` in `k8s-monitoring-values.yml`.
- **Point at your own Pyroscope**: Update the `destinations.pyroscope.url` value in `k8s-monitoring-values.yml` and remove the in-cluster Pyroscope Helm release.
- **Profile a Go application**: Expose a pprof endpoint, typically at `:6060/debug/pprof/`, and add profiling annotations to the Pod:

  ```yaml
  metadata:
    annotations:
      profiles.grafana.com/memory.scrape: "true"
      profiles.grafana.com/memory.port_name: "http-metrics"
      profiles.grafana.com/cpu.scrape: "true"
      profiles.grafana.com/cpu.port_name: "http-metrics"
      profiles.grafana.com/goroutine.scrape: "true"
      profiles.grafana.com/goroutine.port_name: "http-metrics"
  ```

After you edit `k8s-monitoring-values.yml`, upgrade the release:

```sh
helm upgrade k8s grafana/k8s-monitoring --version "^4.0.0" -n meta --values ./k8s-monitoring-values.yml
```

## Troubleshoot common problems

Diagnose Pod startup failures, missing profiles in Grafana, Helm install errors, and port-forward problems.

### Pods didn't start or aren't ready

Run `kubectl get pods -n meta`.
If a Pod isn't running, run `kubectl describe pod <POD_NAME> -n meta`.
For Alloy collectors, check the k8s-monitoring release with `helm status k8s -n meta`.

### No data appears in Grafana after a few minutes

Open the Alloy UI and check that the `alloy-profiles` collector is healthy.
Use live debug to verify profiles arrive.
In Grafana, open the **Pyroscope** app or select the **Pyroscope** data source in **Explore**.
If no workloads expose pprof endpoints, deploy the Ride Share app from **Try it out**.

### Kubernetes Monitoring Helm chart install failed

Install Pyroscope and Grafana before k8s-monitoring.
Requires `grafana/k8s-monitoring` chart v4 or later.
Run `helm list -n meta` to verify the releases.
Wait until the `meta` namespace Pods are ready before you query profiles.

### Port-forward connection refused

Check that the target Pod is `Running`, then rerun the port-forward commands from **Access the services**.
If the Grafana or Alloy Pod restarted, export `POD_NAME` again before you port-forward.

## Stop the scenario

Run `kind delete cluster` to tear down the local Kind cluster and all workloads.

## Next steps

- Kubernetes Monitoring Helm chart: https://github.com/grafana/k8s-monitoring-helm
- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- Pyroscope documentation: https://grafana.com/docs/pyroscope/latest/
- Metrics scenario: [Monitor Kubernetes metrics with Grafana Alloy and Prometheus](../metrics)
- More examples: https://github.com/grafana/alloy-scenarios
