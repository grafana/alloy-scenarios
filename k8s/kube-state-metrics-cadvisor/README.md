# Monitor Kubernetes with kube-state-metrics and cAdvisor using a standalone Alloy DaemonSet

> Unlike the other scenarios in `k8s/`, this one does **not** use the k8s-monitoring Helm chart. It deploys Alloy directly with the [grafana/alloy](https://github.com/grafana/alloy/tree/main/operations/helm/charts/alloy) chart so you can see the raw collection pipeline — `discovery.kubernetes` → `prometheus.scrape` → `prometheus.remote_write` — that higher-level charts generate for you.

This scenario demonstrates the canonical Kubernetes metrics pair:

* **kube-state-metrics (KSM)** — cluster *state* as metrics: `kube_pod_status_ready`, `kube_node_info`, `kube_deployment_status_replicas_available`, ...
* **cAdvisor** — container *resource usage* from each node's kubelet: `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`, ...

Alloy runs as a DaemonSet with [clustering](https://grafana.com/docs/alloy/latest/get-started/clustering/) enabled, so scrape targets are consistent-hashed across the Alloy pods and each kubelet and KSM endpoint is scraped exactly once. The cAdvisor scrape goes straight to the kubelet over HTTPS (`/metrics/cadvisor`), authenticated with the pod's ServiceAccount bearer token — the Alloy chart's default RBAC already includes `nodes/metrics`.

## Prerequisites

Clone the repository:

```bash
git clone https://github.com/grafana/alloy-scenarios.git
```

Change to the directory:

```bash
cd alloy-scenarios/k8s/kube-state-metrics-cadvisor
```

Next you will need a Kubernetes cluster. An example Kind cluster configuration is provided in the `kind.yml` file:

```bash
kind create cluster --config kind.yml
```

Install Helm and add the required repositories:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

## Create the `meta` namespace

```bash
kubectl create namespace meta
```

## Install the charts

Install kube-state-metrics (chart 7.4.0 / KSM v2.19.0 at the time of writing):

```bash
helm install kube-state-metrics prometheus-community/kube-state-metrics -f ksm-values.yml -n meta
```

Install Prometheus with the remote-write receiver enabled (the bundled KSM, node-exporter, Alertmanager, and Pushgateway are disabled — Alloy does the collecting here):

```bash
helm install prometheus prometheus-community/prometheus -f prometheus-values.yml -n meta
```

Install Grafana with the Prometheus datasource and two dashboards provisioned:

```bash
helm install grafana grafana/grafana -f grafana-values.yml -n meta
```

Install Alloy as a clustered DaemonSet with the scrape pipeline inlined in `alloy-values.yml`:

```bash
helm install alloy grafana/alloy -f alloy-values.yml -n meta
```

Wait for everything to come up:

```bash
kubectl wait --for=condition=Ready pods --all -n meta --timeout=10m
```

## Explore

Port-forward Grafana and log in with `admin` / `adminadminadmin`:

```bash
kubectl -n meta port-forward svc/grafana 3000:80
```

Two dashboards are provisioned out of the box:

* **Kubernetes Cluster Overview (KSM + cAdvisor)** — a compact overview where every panel is answerable from this scenario's pipeline.
* **Kubernetes / Views / Namespaces** ([Grafana dashboard 15758](https://grafana.com/grafana/dashboards/15758-k8s-views-namespaces/)) — a popular community dashboard that only uses KSM v2 and cAdvisor metric names.

To query directly, port-forward Prometheus:

```bash
kubectl -n meta port-forward svc/prometheus-server 9090:80
```

Try the scenario's two acceptance queries:

```promql
kube_pod_status_ready{condition="true"}
```

```promql
sum(rate(container_cpu_usage_seconds_total[5m]))
```

You can also inspect the Alloy pipeline and cluster state in the Alloy UI:

```bash
kubectl -n meta port-forward svc/alloy 12345:12345
```

Open http://localhost:12345 and check the **Clustering** page — you should see one Alloy instance per node, each owning a share of the scrape targets.

## How the pipeline works

`alloy-values.yml` inlines the whole Alloy configuration:

1. `discovery.kubernetes "nodes"` discovers every node; targets point at the kubelet (port 10250).
2. `prometheus.scrape "cadvisor"` scrapes `https://<node>:10250/metrics/cadvisor` with the ServiceAccount bearer token (`insecure_skip_verify` because kubelet certificates are self-signed).
3. `discovery.kubernetes "endpoints"` + a `discovery.relabel` keep-rule select the `kube-state-metrics` service endpoints.
4. Both scrape components run with `clustering { enabled = true }` for target dedup across the DaemonSet.
5. `prometheus.remote_write` pushes everything to Prometheus in the `meta` namespace.

## Clean up

```bash
helm uninstall alloy grafana prometheus kube-state-metrics -n meta
kind delete cluster
```
