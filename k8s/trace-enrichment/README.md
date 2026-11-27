# Enrich Kubernetes traces with pod metadata using Grafana Alloy

This scenario shows how to tag OTLP traces with the Kubernetes identity of the pod that sent them, using [`otelcol.processor.k8sattributes`][k8sattributes].
The demo app only sets `service.name`.
Alloy looks up the sending pod and adds `k8s.namespace.name`, `k8s.pod.name`, `k8s.node.name`, `k8s.deployment.name`, and a pod label, so you can filter traces in Tempo by workload.

Unlike the [tracing scenario](../tracing), this one doesn't use the k8s-monitoring Helm chart.
It deploys Alloy with the plain [grafana/alloy][alloy-chart] chart so the whole pipeline is in `alloy-values.yml`.

[k8sattributes]: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.k8sattributes/
[alloy-chart]: https://github.com/grafana/alloy/tree/main/operations/helm/charts/alloy

## Before you begin

Ensure you have the following:

- [Kind][kind] to create a local Kubernetes cluster.
- [kubectl][kubectl] configured to talk to your cluster.
- [Helm][helm] v3 or later.
- The Grafana Helm repository:

  ```sh
  helm repo add grafana https://grafana.github.io/helm-charts
  helm repo update
  ```

- Ports 3000 and 12345 free on your machine for the Grafana and Alloy UI port-forwards.

[kind]: https://kind.sigs.k8s.io/docs/user/quick-start/
[kubectl]: https://kubernetes.io/docs/tasks/tools/
[helm]: https://helm.sh/docs/intro/install/

## Understand the architecture

```text
+-------------------+      +--------------------------------------+      +-------+       +---------+
| prod/checkout     | OTLP | Alloy (meta)                         | OTLP |       | query |         |
| telemetrygen x2   |----->| otlp -> k8sattributes -> batch       |----->| Tempo |<------| Grafana |
+-------------------+      +--------------------------------------+      +-------+       +---------+
                                      |
                                      | watch pods, namespaces, replicasets
                                      v
                             Kubernetes API server
```

- **checkout**: Two telemetrygen pods in the `prod` namespace that send spans to `alloy.meta.svc.cluster.local:4317`.
- **Alloy**: A single Deployment that receives OTLP, enriches spans with pod metadata, and exports them to Tempo.
- **Tempo**: Stores traces at `tempo.meta.svc.cluster.local`.
- **Grafana**: Queries traces through a configured Tempo data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/k8s/trace-enrichment`

3. Create a local Kind cluster:

   ```sh
   kind create cluster --config kind.yml
   ```

4. Create the `meta` namespace:

   ```sh
   kubectl create namespace meta
   ```

5. Install Tempo and Grafana:

   ```sh
   helm install --values tempo-values.yml tempo grafana/tempo -n meta
   helm install --values grafana-values.yml grafana grafana/grafana -n meta
   ```

6. Install Alloy:

   ```sh
   helm install --values alloy-values.yml alloy grafana/alloy -n meta
   ```

7. Deploy the demo app:

   ```sh
   kubectl apply -f demo-app.yml
   ```

8. Wait until the pods are ready:

   ```sh
   kubectl get pods -n meta -w
   kubectl get pods -n prod
   ```

## Access the services

Run each port-forward in its own terminal and leave it open.

- Grafana at http://localhost:3000:

  ```sh
  kubectl --namespace meta port-forward svc/grafana 3000:80
  ```

- Alloy UI at http://localhost:12345:

  ```sh
  kubectl --namespace meta port-forward svc/alloy 12345
  ```

Log in to Grafana as `admin` / `adminadminadmin`.

## Try it out

1. Open Grafana **Explore**, select the **Tempo** data source, and run `{resource.service.name="checkout"}`.
2. Open any span and expand the resource attributes.
   You should see `k8s.namespace.name=prod`, `k8s.deployment.name=checkout`, `k8s.pod.name`, `k8s.node.name`, `k8s.pod.uid`, and `app=checkout`.
   None of these come from the app.
3. Filter by pod or node with TraceQL:

   - One namespace: `{resource.k8s.namespace.name="prod"}`
   - One pod: `{resource.k8s.pod.name=~"checkout-.*"}`
   - One node: `{resource.k8s.node.name="kind-worker"}`

4. In the Alloy UI, open `otelcol.processor.k8sattributes.default` and use live debugging to compare spans before and after enrichment.

## Understand the k8sattributes configuration

- **`extract.metadata`**: The pod fields copied onto each span's resource.
  `k8s.deployment.name` is derived from the pod's ReplicaSet name.
- **`extract.label`**: Copies the pod's `app.kubernetes.io/name` label to an `app` attribute.
  Leave out `tag_name` to get the semantic convention name `k8s.pod.label.app.kubernetes.io/name` instead.
- **`pod_association`**: How Alloy finds the pod for incoming data.
  It first checks for a `k8s.pod.ip` resource attribute, then falls back to the source IP of the connection.
  The connection IP works here because the apps send straight to the Alloy Service.
  If traffic goes through another collector or a proxy first, set `k8s.pod.ip` or `k8s.pod.uid` in the app, for example with the Downward API and `OTEL_RESOURCE_ATTRIBUTES`.

The Alloy chart's default ClusterRole already grants the `get`, `list`, and `watch` access on pods, namespaces, replicasets, and nodes that the processor needs.

## Customize the scenario

- **Send your own app's traces**: Point its OTLP exporter at the Alloy Service.

  ```text
  OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy.meta.svc.cluster.local:4317
  OTEL_EXPORTER_OTLP_PROTOCOL=grpc
  ```

  For HTTP, use port 4318 and set `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`.

- **Run Alloy as a DaemonSet**: Set `controller.type: daemonset` in `alloy-values.yml` and add a `filter { node = sys.env("K8S_NODE_NAME") }` block to the processor so each Alloy pod only watches pods on its own node.
  Expose the node name to Alloy with an environment variable from `spec.nodeName`.

- **Add more metadata**: Add fields such as `k8s.statefulset.name` or `container.image.name` to `extract.metadata`, or add `annotation` blocks.

After you edit `alloy-values.yml`, upgrade the release:

```sh
helm upgrade alloy grafana/alloy -n meta --values alloy-values.yml
```

## Troubleshoot common problems

### Spans have no k8s attributes

Check that the `checkout` pods are running with `kubectl get pods -n prod`.
If the spans reached Tempo but have no `k8s.*` attributes, Alloy couldn't match the connection to a pod.
That usually means the traffic came through a proxy or another collector, so the source IP isn't the pod IP.
Set `k8s.pod.ip` in the app or keep the apps sending straight to Alloy.

### No traces in Grafana

Open the Alloy UI and check that all components are healthy.
Run `kubectl logs -n prod deploy/checkout` to confirm telemetrygen can reach `alloy.meta.svc.cluster.local:4317`.

## Stop the scenario

Run `kind delete cluster` to tear down the cluster and everything in it.

## Next steps

- `otelcol.processor.k8sattributes` reference: https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.k8sattributes/
- Tracing with the k8s-monitoring chart: [Monitor Kubernetes traces with Grafana Alloy and Tempo](../tracing)
- More examples: https://github.com/grafana/alloy-scenarios
