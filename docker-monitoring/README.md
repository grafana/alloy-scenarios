# Docker Monitoring with Grafana Alloy

This example demonstrates how to monitor Docker containers using Grafana Alloy.
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
cd alloy-scenarios/docker-monitoring
docker-compose up -d
```

> **Note (macOS Docker Desktop):** If Alloy cannot connect to the Docker socket, you may need to change the volume mount in `docker-compose.yml` from `/var/run/docker.sock` to `/var/run/docker.sock.raw`. This is a workaround specific to some versions of Docker Desktop on macOS.

### Step 3: Access Grafana Alloy UI
Open your browser and go to `http://localhost:12345`. 

### Step 4: Access Grafana UI
Open your browser and go to `http://localhost:3000`.


