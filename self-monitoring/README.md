# Self-Monitoring with Grafana Alloy

This example demonstrates how to configure Grafana Alloy to monitor itself, collecting both its own metrics and logs alongside other Docker containers.

## Prerequisites
- Docker
- Docker Compose
- Git

## Running the Demo

### Step 1: Clone the repository
```bash
git clone https://github.com/grafana/alloy-scenarios.git
```

### Step 2: Deploy the monitoring stack
```bash
cd alloy-scenarios/self-monitoring
docker-compose up -d
```

### Step 3: Access Grafana Alloy UI
Open your browser and go to `http://localhost:12345`. 

### Step 4: Access Prometheus UI
Open your browser and go to `http://localhost:9090`.

### Step 5: Access Loki
Loki is available at `http://localhost:3100`.

## What This Demo Shows

This scenario demonstrates:

- **Metrics Collection**: Using `prometheus.exporter.self` to export Alloy's own internal metrics
- **Log Collection**: Using `loki.source.docker` to collect logs from all Docker containers, including Alloy itself
- **Service Discovery**: Automatic discovery of Docker containers with proper labeling
- **Remote Write**: Sending metrics to Prometheus and logs to Loki

## Key Configuration Elements

### Self-Monitoring Metrics

The `prometheus.exporter.self` component exposes Alloy's internal metrics:
- Memory usage
- CPU utilization
- Component health
- Scrape statistics

### Docker Log Collection

The configuration automatically discovers and collects logs from all Docker containers running on the host, including:
- Alloy's own logs
- Prometheus logs
- Loki logs
- Any other containers running on the same Docker host


