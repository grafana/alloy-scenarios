
# Monitor Kubernetes Metrics with Grafana Alloy and Prometheus

> Note this scenario works using the K8s Monitoring Helm chart. This abstracts the need to configure Alloy and deploys best practices for monitoring Kubernetes clusters.

This scenario demonstrates how to set up the Kubernetes monitoring Helm chart with Prometheus. This scenario will install three Helm charts: Prometheus, Grafana, and k8s-monitoring. Prometheus will be used to store the metrics, Grafana will be used to visualize the metrics, and Alloy (k8s-monitoring) will be used to collect:
* Cluster Metrics (kube-state-metrics, node-exporter, kubelet, cadvisor)
* Annotation-based autodiscovery (Prometheus-style annotations on pods)

## Prerequisites

Clone the repository:

```bash
git clone https://github.com/grafana/alloy-scenarios.git
```

Change to the directory:

```bash
cd alloy-scenarios/k8s/metrics
```

Next you will need a Kubernetes cluster. An example Kind cluster configuration is provided in the `kind.yml` file:

```bash
kind create cluster --config kind.yml
```

Install Helm and add required repositories:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

## Create the `meta` namespace

```bash
kubectl create namespace meta
```

## Install Prometheus

```bash
helm install --values prometheus-values.yml prometheus prometheus-community/prometheus -n meta
```

## Install Grafana

```bash
helm install --values grafana-values.yml grafana grafana/grafana -n meta
```

## Install the K8s Monitoring Helm Chart

```bash
helm install --values k8s-monitoring-values.yml k8s grafana/k8s-monitoring -n meta
```

## Accessing the Grafana UI

```bash
export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace meta port-forward $POD_NAME 3000
```

Open [http://localhost:3000](http://localhost:3000) and log in with `admin` / `adminadminadmin`.

## Accessing the Alloy UI

```bash
export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-metrics,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace meta port-forward $POD_NAME 12345
```

## Explore Metrics

In Grafana, go to **Explore** and select the **Prometheus** datasource. Try these queries:

* `up` - See all targets being scraped
* `container_cpu_usage_seconds_total` - Container CPU usage
* `container_memory_working_set_bytes` - Container memory usage
* `kube_pod_info` - Pod metadata from kube-state-metrics
