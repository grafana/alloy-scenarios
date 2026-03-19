# Monitor Kubernetes Traces with Grafana Alloy and Tempo

> Note this scenario works using the K8s Monitoring Helm chart. This abstracts the need to configure Alloy and deploys best practices for monitoring Kubernetes clusters.

This scenario demonstrates how to set up the Kubernetes monitoring Helm chart with Tempo for distributed trace collection. This scenario will install three Helm charts: Tempo, Grafana, and k8s-monitoring. Tempo will store the traces, Grafana will visualize them, and Alloy (k8s-monitoring) will receive traces via OTLP and forward them to Tempo.

Applications send traces to Alloy's OTLP endpoint, which then forwards them to Tempo.

## Prerequisites

Clone the repository:

```bash
git clone https://github.com/grafana/alloy-scenarios.git
```

Change to the directory:

```bash
cd alloy-scenarios/k8s/tracing
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

## Create the `meta` and `prod` namespaces

```bash
kubectl create namespace meta && \
kubectl create namespace prod
```

## Install Tempo

```bash
helm install --values tempo-values.yml tempo grafana/tempo -n meta
```

## Install Grafana

```bash
helm install --values grafana-values.yml grafana grafana/grafana -n meta
```

## Install the K8s Monitoring Helm Chart

```bash
helm install --values k8s-monitoring-values.yml k8s grafana/k8s-monitoring -n meta
```

This configures Alloy to receive OTLP traces on ports 4317 (gRPC) and 4318 (HTTP), then forward them to Tempo.

## Accessing the Grafana UI

```bash
export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace meta port-forward $POD_NAME 3000
```

Open [http://localhost:3000](http://localhost:3000) and log in with `admin` / `adminadminadmin`.

## Accessing the Alloy UI

```bash
export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-receiver,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace meta port-forward $POD_NAME 12345
```

## Sending Traces

Applications in your cluster should set their OTLP exporter endpoint to the Alloy receiver service:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://k8s-alloy-receiver.meta.svc.cluster.local:4317
```

## Adding a Demo App

Deploy a sample instrumented application in the `prod` namespace to generate traces:

```bash
helm install tempo-distributed grafana/tempo-distributed -n prod
```

Or deploy any application instrumented with OpenTelemetry SDK pointing to the Alloy OTLP endpoint above.

## Explore Traces

In Grafana, go to **Explore** and select the **Tempo** datasource. Use TraceQL to search for traces:

* `{}` - View all traces
* `{resource.service.name="my-service"}` - Filter by service name
* `{status=error}` - Find error traces
