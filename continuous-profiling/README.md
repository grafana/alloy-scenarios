# Continuous Profiling

This scenario demonstrates continuous profiling of a Go application using Grafana Alloy's `pyroscope.scrape` and `pyroscope.write` components, with Grafana Pyroscope as the profiling backend.

## Overview

The example includes:
- **demo-app** -- A Go application that performs CPU-intensive and memory-intensive work, exposing standard pprof endpoints on port 6060
- **alloy** -- Grafana Alloy configured to scrape pprof profiles from the demo app and forward them to Pyroscope
- **pyroscope** -- Grafana Pyroscope for storing and querying profiling data
- **grafana** -- Grafana with the Pyroscope datasource pre-configured for visualizing profiles

## Running the Demo

1. Clone the repository:
   ```
   git clone https://github.com/grafana/alloy-scenarios.git
   cd alloy-scenarios
   ```

2. Navigate to this example directory:
   ```
   cd continuous-profiling
   ```

3. Run using Docker Compose:
   ```
   docker compose up -d
   ```

   Or use the centralized image management:
   ```
   cd ..
   ./run-example.sh continuous-profiling
   ```

4. Access Grafana at http://localhost:3000

## What to Expect

After starting the scenario, Alloy will scrape the following profile types from the demo app every 15 seconds:

- **CPU** -- Identifies functions consuming the most CPU time (the `cpuIntensive` goroutine)
- **Memory (heap)** -- Shows memory allocation patterns (the `memoryIntensive` goroutine allocating 1MB chunks)
- **Goroutine** -- Displays active goroutines and their stack traces
- **Mutex** -- Captures mutex contention profiles
- **Block** -- Captures blocking operation profiles

To view profiles:

1. Open Grafana at http://localhost:3000
2. Navigate to **Explore**
3. Select the **Pyroscope** datasource
4. Choose a profile type (e.g., `process_cpu`) and the `demo-app` service
5. You should see flame graphs showing where the application spends its time and allocates memory

## Architecture

```
┌───────────┐     scrape pprof     ┌───────────┐     push profiles     ┌────────────┐
│  demo-app │◀─────────────────────│   Alloy   │─────────────────────▶│ Pyroscope  │
│  :6060    │     /debug/pprof/*   │  :12345   │                      │   :4040    │
└───────────┘                      └───────────┘                      └─────┬──────┘
                                                                            │
                                                                            ▼
                                                                      ┌──────────┐
                                                                      │ Grafana  │
                                                                      │  :3000   │
                                                                      └──────────┘
```

## Useful Links

- Alloy UI: http://localhost:12345 -- Inspect the Alloy pipeline and component status
- Grafana: http://localhost:3000 -- Explore profiles via the Pyroscope datasource
- Pyroscope: http://localhost:4040 -- Direct access to the Pyroscope UI
- Demo app pprof index: http://localhost:6060/debug/pprof/ -- Raw pprof endpoints
