# Monitor Kubernetes Profiles with Grafana Alloy and Pyroscope

> Note this scenario works using the K8s Monitoring Helm chart. This abstracts the need to configure Alloy and deploys best practices for monitoring Kubernetes clusters.

This scenario demonstrates how to set up the Kubernetes monitoring Helm chart with Pyroscope for continuous profiling. This scenario will install three Helm charts: Pyroscope, Grafana, and k8s-monitoring. Pyroscope will store the profiles, Grafana will visualize them, and Alloy (k8s-monitoring) will scrape pprof endpoints from pods.

Alloy discovers pods with profiling annotations and scrapes their pprof endpoints (CPU, memory, goroutine, etc.).

## Prerequisites

Clone the repository:

```bash
git clone https://github.com/grafana/alloy-scenarios.git
```

Change to the directory:

```bash
cd alloy-scenarios/k8s/profiling
```

Next you will need a Kubernetes cluster. An example Kind cluster configuration is provided in the `kind.yml` file:

```bash
kind create cluster --config kind.yml
```

Install Helm and add the Grafana Helm repository:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

## Create the `meta` namespace

```bash
kubectl create namespace meta
```

## Install Pyroscope

```bash
helm install --values pyroscope-values.yml pyroscope grafana/pyroscope -n meta
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
export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-profiles,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace meta port-forward $POD_NAME 12345
```

## Enabling Profiling on Your Pods

To profile a Go application, ensure it exposes a pprof endpoint (typically at `:6060/debug/pprof/`) and add these annotations to the pod:

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

## Adding a Demo App

Deploy Pyroscope's demo Ride Share app to generate profiles:

```bash
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

## Explore Profiles

In Grafana, navigate to the **Pyroscope** app or use **Explore** with the Pyroscope datasource. You can view:

* CPU profiles - flame graphs showing where CPU time is spent
* Memory profiles - heap allocation and usage
* Goroutine profiles - concurrent goroutine analysis
