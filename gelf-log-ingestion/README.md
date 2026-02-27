# GELF Log Ingestion Scenario

This scenario demonstrates how to ingest GELF (Graylog Extended Log Format) logs using Grafana Alloy's `loki.source.gelf` component. A Python application sends structured GELF messages over UDP to Alloy, which relabels GELF metadata (host, level, facility) into Loki labels before forwarding to Loki for storage and querying in Grafana.

## Architecture

```
gelf-logger (Python/pygelf) --UDP:12201--> Alloy (loki.source.gelf) --> Loki --> Grafana
```

## Running the Demo

### Step 1: Clone the repository
```bash
git clone https://github.com/grafana/alloy-scenarios.git
```

### Step 2: Deploy the monitoring stack
```bash
cd alloy-scenarios/gelf-log-ingestion
docker-compose up -d
```

### Step 3: Access Grafana Alloy UI
Open your browser and go to `http://localhost:12345` to inspect the Alloy pipeline and live debugging output.

### Step 4: Access Grafana UI
Open your browser and go to `http://localhost:3000`. Navigate to **Explore** and select the **Loki** datasource. Query logs using `{host="gelf-logger"}` or filter by label (e.g., `{level="6"}` for INFO).

## GELF Level Mapping

| GELF Level | Syslog Severity |
|------------|-----------------|
| 0          | Emergency       |
| 1          | Alert           |
| 2          | Critical        |
| 3          | Error           |
| 4          | Warning         |
| 5          | Notice          |
| 6          | Informational   |
| 7          | Debug           |
