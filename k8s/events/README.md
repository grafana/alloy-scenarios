# Collect Kubernetes events with Grafana Alloy

This scenario shows how `loki.source.kubernetes_events` collects cluster events and forwards them to Loki.
Alloy deploys as a plain `Deployment` with RBAC and a `ConfigMap` you can edit directly.
The [logs scenario](../logs) covers the same signal through the [Kubernetes Monitoring Helm chart][k8s-monitoring], which hides the collector configuration behind chart values.

Use the logs scenario when you want a full Kubernetes monitoring setup.
Use this scenario when you want to see how the events collector works or how you can change filtering, namespace scoping, or alerting.

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

| Aspect                          | `k8s/logs/`                                  | `k8s/events/`                                                             |
| ------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------- |
| Alloy deployment                | `k8s-monitoring` Helm chart collector preset | Plain `kubectl apply` of ConfigMap, RBAC, and Deployment                  |
| `loki.source.kubernetes_events` | Hidden inside the chart                      | Visible directly in `alloy-config.yaml`                                   |
| Scope                           | Pod logs and cluster events                  | Cluster events only with `type`, `reason`, `namespace`, and `kind` labels |
| Best for                        | Production Kubernetes monitoring             | Learning or extending the events collector                                |

## Understand the architecture

```text
+------------------+     +---------------------------+      +------+       +---------+
| Kubernetes API   |     | Alloy                     | push |      | query |         |
| cluster events   |---->| kubernetes_events +       |----->| Loki |<------| Grafana |
|                  |     | process + write           |      |      |       |         |
+------------------+     +---------------------------+      +------+       +---------+
```

- **Kubernetes API**: Emits cluster-scoped events when pods start, fail, pull images, or terminate.
- **Alloy**: Watches events through `loki.source.kubernetes_events`, parses JSON, promotes labels, and pushes entries to Loki.
  Run one replica only. Multiple replicas would write duplicate lines for the same event.
- **Loki**: Stores the event log entries.
- **Grafana**: Queries events through a pre-configured Loki data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Navigate to this scenario: `cd alloy-scenarios/k8s/events`

3. Create a local Kind cluster:

   ```sh
   kind create cluster --config kind.yml
   ```

4. Create the `meta` namespace and install Loki and Grafana:

   ```sh
   kubectl create namespace meta

   helm install --values loki-values.yml loki grafana/loki -n meta
   helm install --values grafana-values.yml grafana grafana/grafana -n meta
   ```

5. Wait until pods are ready:

   ```sh
   kubectl get pods -n meta -w
   ```

6. Apply the Alloy manifests:

   ```sh
   kubectl apply -f alloy-rbac.yaml
   kubectl apply -f alloy-config.yaml
   kubectl apply -f alloy-deployment.yaml
   ```

   RBAC grants cluster-wide `get`, `list`, and `watch` on `events` for the core and `events.k8s.io` API groups.
   The ConfigMap mounts as `config.alloy` at `/etc/alloy/config.alloy` in the Alloy Pod.

## Access the services

Grafana and the Alloy UI aren't exposed on localhost.
Run one port-forward command per service in a separate terminal, and leave that terminal open until you're done.
Use a second terminal if you need Grafana and the Alloy UI at the same time.

**Grafana**

```sh
kubectl port-forward -n meta svc/grafana 3000:80
```

Open http://localhost:3000.

**Alloy UI**

```sh
kubectl port-forward -n meta svc/alloy 12345:12345
```

Open http://localhost:12345.

Run the command again when you start a new session.

## Explore the services

- **Grafana** at http://localhost:3000: Query events in **Explore** with the Loki data source.
  Log in as `admin` / `adminadminadmin`. Refer to `grafana-values.yml` for credentials.
- **Alloy UI** at http://localhost:12345: Component graph and live debug.
- **Loki** at `loki-gateway.meta.svc.cluster.local`: Query through Grafana; Alloy reaches it inside the cluster.

## Understand the Alloy pipeline

The `alloy-config.yaml` ConfigMap defines three components:

1. **`loki.source.kubernetes_events.cluster`**: Watches cluster-wide Kubernetes events with `job_name = "kubernetes-events"` and `log_format = "json"`.
   Adds `job`, `namespace`, and `instance` labels to each entry and forwards to `loki.process.events`.
2. **`loki.process.events`**: Parses the JSON envelope and promotes labels.
   - `stage.json` extracts `type`, `reason`, `kind`, and `name` from the log line.
   - `stage.labels` promotes `type`, `reason`, and `kind` to indexed Loki labels.
   - `stage.structured_metadata` stores `name` as structured metadata instead of a label.
3. **`loki.write.loki`**: Pushes entries to `http://loki-gateway.meta.svc.cluster.local/loki/api/v1/push`.

`livedebugging{}` is enabled.

Indexed labels are `job`, `type`, `reason`, `namespace`, and `kind`.
The `instance` label identifies the Alloy component.
The involved-object `name` is structured metadata. It has high cardinality but you can search it with `| json`.

## Try it out

1. With the Grafana port-forward running, open http://localhost:3000.

2. Generate Kubernetes events:

   1. Create a pod that triggers Created, Started, and Pulled events.
   2. Create a pod with a bad image to trigger BackOff and Failed events.
   3. Wait, then delete both pods to trigger Killing events.

   Run these commands in order:

   ```sh
   kubectl run events-test --image=nginx --restart=Never
   kubectl run events-fail --image=does-not-exist --restart=Never
   sleep 30
   kubectl delete pod events-test events-fail
   ```

3. In Grafana **Explore**, select the **Loki** data source and try these queries:

   - All events: `{job="kubernetes-events"}`
   - Warnings only: `{job="kubernetes-events", type="Warning"}`
   - Pod events in the default namespace: `{job="kubernetes-events", namespace="default", kind="Pod"}`
   - Pull failures: `{job="kubernetes-events", reason="Failed"}`
   - Backoff loops: `{job="kubernetes-events", reason="BackOff"}`

4. With the Alloy UI port-forward running, open http://localhost:12345.
   Select `loki.source.kubernetes_events.cluster`, `loki.process.events`, or `loki.write.loki` for live debug.

## Customize the scenario

- **Scope to specific namespaces**: Add `namespaces = ["prod", "default"]` to the `loki.source.kubernetes_events.cluster` block in the `config.alloy` section of `alloy-config.yaml`.
- **Drop noisy reasons**: Add a `stage.match` block that drops `reason=~"Pulled|Pulling|Created"` in `loki.process.events`.
- **Add alerting**: Alert on `count_over_time({type="Warning"}[5m])` in Grafana.

After you edit `alloy-config.yaml`, reapply it and restart Alloy:

```sh
kubectl apply -f alloy-config.yaml
kubectl rollout restart deployment/alloy -n meta
```

## Troubleshoot common problems

Diagnose pod startup failures, missing events in Grafana, RBAC permission errors, duplicate log lines, and port-forward problems.

### Pods didn't start or aren't ready

Run `kubectl get pods -n meta`.
If a Pod isn't running, run `kubectl describe pod <POD_NAME> -n meta`.
For Alloy, check the `config.alloy` block in `alloy-config.yaml` for syntax errors.

### No data appears in Grafana after a few minutes

Open the Alloy UI and confirm components are healthy.
Use live debug on `loki.source.kubernetes_events.cluster` to verify events arrive.
In Grafana, select the **Loki** data source and run `{job="kubernetes-events"}`.
If the cluster is idle, generate test events with the commands in **Try it out**.

### Alloy can't read Kubernetes events

Apply `alloy-rbac.yaml` before the Deployment.
The Alloy Pod must use the `alloy` ServiceAccount in `meta`.
Check permissions with `kubectl auth can-i list events --as=system:serviceaccount:meta:alloy`.

### Duplicate event log lines appear in Loki

Events are cluster-scoped.
Keep the Deployment at `replicas: 1` in `alloy-deployment.yaml`.

### Port-forward connection refused

Confirm the Pod is `Running`, then rerun the port-forward command from **Access the services**.

## Stop the scenario

```sh
kind delete cluster
```

## Next steps

- `loki.source.kubernetes_events` reference: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.kubernetes_events/
- Alloy components: https://grafana.com/docs/alloy/latest/reference/components/
- Logs scenario: [Monitor Kubernetes logs with Grafana Alloy and Loki](../logs)
- More examples: https://github.com/grafana/alloy-scenarios
