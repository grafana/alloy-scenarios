
# Monitor Kubernetes Logs with Grafana Alloy and Loki

> Note this scenario works using the K8s Monitoring Helm chart. This abstracts the need to configure Alloy and deploys best practices for monitoring Kubernetes clusters. The chart supports; metrics, logs, profiling, and tracing. For this scenario, we will use the K8s Monitoring Helm chart to monitor Kubernetes logs. 

This scenario demonstrates how to setup the Kubernetes monitoring helm and Loki. This scenario will install three Helm charts: Loki, Grafana, and k8s-monitoring-helm. Loki will be used to store the logs, Grafana will be used to visualize the logs, and Alloy (k8s-monitoring-helm) will be used to collect three different log sources:
* Pod Logs
* Kubernetes Events

## Prerequisites

Clone the repository:

```bash
git clone https://github.com/grafana/alloy-scenarios.git
```

Change to the directory:

```bash
cd alloy-scenarios/k8s-logs
```

Next you will need a Kubernetes cluster (In this example, we will configure a local Kubernetes cluster using [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/))

An example kind cluster configuration is provided in the `kind.yml` file. To create a kind cluster using this configuration, run the following command:

```bash
kind create cluster --config kind.yml
```

Lastly you will need to make sure you install Helm on your local machine. You can install Helm by following the instructions [here](https://helm.sh/docs/intro/install/). You will also need to install the Grafana Helm repository:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
```

## Create the `meta` and `prod` namespaces

The first step is to create the `meta` and `prod` namespaces. To create the namespaces, run the following commands:

```bash
kubectl create namespace meta && \
kubectl create namespace prod
```


## Install the Loki Helm Chart

The first step is to install the Loki Helm chart. This will install Loki in the `meta` namespace. The `loki-values.yml` file contains the configuration for the Loki Helm chart. To install Loki, run the following command:

```bash
helm install --values loki-values.yml loki grafana/loki -n meta
```

This installs Loki in monolithic mode. For more information on Loki modes, see the [Loki documentation](https://grafana.com/docs/loki/latest/get-started/deployment-modes/).

## Install the Grafana Helm Chart

The next step is to install the Grafana Helm chart. This will install Grafana in the `meta` namespace. The `grafana-values.yml` file contains the configuration for the Grafana Helm chart. To install Grafana, run the following command:

```bash
helm install --values grafana-values.yml grafana grafana/grafana --namespace meta
```
Note that within the `grafana-values.yml` file, the `grafana.ini` configuration is set to use the Loki data source. This is done by setting the `datasources.datasources.yaml` field to the Loki data source configuration.

## Install the K8s Monitoring Helm Chart

The final step is to install the K8s monitoring Helm chart. This will install Alloy in the `meta` namespace. The `k8s-monitoring-values.yml` file contains the configuration for the K8s monitoring Helm chart. To install the K8s monitoring Helm chart, run the following command:

```bash
helm install --values ./k8s-monitoring-values.yml k8s grafana/k8s-monitoring -n meta --create-namespace
```
Within the `k8s-monitoring-values.yml` file we declare the Alloy configuration. This configuration specifies the log sources that Alloy will collect logs from. In this scenario, we are collecting logs from two different sources: Pod Logs and Kubernetes Events.

## Accessing the Grafana UI

To access the Grafana UI, you will need to port-forward the Grafana pod to your local machine. First, get the name of the Grafana pod:

```bash
export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=grafana,app.kubernetes.io/instance=grafana" -o jsonpath="{.items[0].metadata.name}")
```

Next, port-forward the Grafana pod to your local machine:

```bash
ls $POD_NAME 3000
```

Open your browser and go to [http://localhost:3000](http://localhost:3000). You can log in with the default username `admin` and password `adminadminadmin`.

## Accessing the Alloy UI

To access the Alloy UI, you will need to port-forward the Alloy pod to your local machine. First, get the name of the Alloy pod:

```bash
export POD_NAME=$(kubectl get pods --namespace meta -l "app.kubernetes.io/name=alloy-logs,app.kubernetes.io/instance=k8s" -o jsonpath="{.items[0].metadata.name}")
```

Next, port-forward the Alloy pod to your local machine:

```bash
kubectl --namespace meta port-forward $POD_NAME 12345
```

## View the logs using Explore Logs in Grafana

Explore Logs is a new feature in Grafana which provides a queryless way to explore logs. To access Explore Logs. To access Explore logs open a browser and go to [http://localhost:3000/a/grafana-lokiexplore-app](http://localhost:3000/a/grafana-lokiexplore-app).

## Adding a demo prod app

The k8s monitoring app is configured to collect logs from two namespaces: `meta` and `prod`. To add a demo prod app, run the following command:

```bash
helm install tempo grafana/tempo-distributed -n prod
```

This will install the Tempo distributed tracing system in the `prod` namespace.