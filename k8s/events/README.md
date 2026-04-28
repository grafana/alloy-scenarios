# Kubernetes events to Loki — without the k8s-monitoring Helm chart

A focused scenario showing how `loki.source.kubernetes_events` works under the hood: Alloy is deployed as a plain `Deployment` with explicit RBAC and an Alloy `ConfigMap`, instead of being abstracted behind the [`k8s-monitoring` Helm chart](https://github.com/grafana/k8s-monitoring-helm) used in [`k8s/logs/`](../logs/).

## How this differs from `k8s/logs/`

| Aspect | `k8s/logs/` (existing) | `k8s/events/` (this) |
|---|---|---|
| Alloy deployment | `k8s-monitoring` Helm chart (collector preset) | Plain `kubectl apply` of ConfigMap + RBAC + Deployment |
| `loki.source.kubernetes_events` | Hidden inside the chart | **Visible directly in `alloy-config.yaml`** |
| Scope | Pod logs + cluster events (mixed) | **Cluster events only** with `type` / `reason` / `namespace` / `kind` labels |
| Demo intent | "ship everything for K8s monitoring" | "show how events ingestion actually works" |

If you want production-grade Kubernetes observability, use `k8s/logs/`. If you're learning the component or want to extend it (custom filtering, namespace scoping, alerting on event reasons), this scenario is the minimal moving-parts version.

## Prerequisites

- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/)
- [Helm](https://helm.sh/docs/intro/install/)
- The Grafana Helm repo: `helm repo add grafana https://grafana.github.io/helm-charts`

## Step 1 — Create the cluster

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/k8s/events

kind create cluster --config kind.yml
```

## Step 2 — Create the `meta` namespace and install Loki + Grafana

```bash
kubectl create namespace meta

helm install --values loki-values.yml loki    grafana/loki    -n meta
helm install --values grafana-values.yml grafana grafana/grafana -n meta
```

Wait for them to be ready:

```bash
kubectl get pods -n meta -w
```

## Step 3 — Apply Alloy

```bash
kubectl apply -f alloy-rbac.yaml
kubectl apply -f alloy-config.yaml
kubectl apply -f alloy-deployment.yaml
```

The RBAC grants cluster-wide `get/list/watch` on `events` (and only that). The ConfigMap holds the Alloy pipeline. The Deployment is **single-replica on purpose** — events are cluster-scoped, so multiple Alloy replicas would produce duplicate log lines.

## Step 4 — Open Grafana

```bash
kubectl port-forward -n meta svc/grafana 3000:80
```

Username `admin`, password `adminadminadmin` (it's a dev scenario — see `grafana-values.yml`).

## Step 5 — Generate some events

```bash
# Trigger Created/Started/Pulled events
kubectl run events-test --image=nginx --restart=Never

# Trigger BackOff/Failed events
kubectl run events-fail --image=does-not-exist --restart=Never

# Wait, then trigger Killing
sleep 30
kubectl delete pod events-test events-fail
```

## Step 6 — Query in Loki

```logql
# All events
{job="kubernetes-events"}

# Just warnings
{job="kubernetes-events", type="Warning"}

# Pod events in default namespace
{job="kubernetes-events", namespace="default", kind="Pod"}

# Pull failures
{job="kubernetes-events", reason="Failed"}

# Backoff loops
{job="kubernetes-events", reason="BackOff"}
```

The promoted labels are `type`, `reason`, `namespace`, and `kind`. The involved-object name (`name`) is kept as **structured metadata** — high cardinality, but searchable via `| json` filters.

## Inspecting the Alloy pipeline

```bash
kubectl port-forward -n meta svc/alloy 12345:12345
```

Open http://localhost:12345 to see the component graph and use **livedebugging** to inspect events flowing through each stage.

## Tear down

```bash
kind delete cluster
```

## Customization ideas

- **Namespace scoping**: add `namespaces = ["prod", "default"]` to the `loki.source.kubernetes_events` block to filter at the source rather than at query time.
- **Drop noisy reasons**: add a `stage.match` block dropping `reason=~"Pulled|Pulling|Created"` if you only care about Warnings.
- **Alerting**: pair this with a Grafana alert on `count_over_time({type="Warning"}[5m])` for cluster-health monitoring.
