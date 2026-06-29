# Continuous profiling

This scenario shows how Grafana Alloy collects continuous profiles from a Go application with `pyroscope.scrape` and `pyroscope.write`.
A `demo-app` container runs CPU-intensive and memory-intensive work and exposes pprof endpoints on port 6060.
Alloy scrapes five profile types every 15 seconds and forwards them to Grafana Pyroscope.
The `config.alloy` file defines the pipeline.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 4040 for Pyroscope, 6060 for the demo app, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Alloy scrapes pprof profiles from the demo app and pushes them to Pyroscope for querying in Grafana.

```text
+----------+     scrape pprof    +-------+     push profiles    +-----------+
| demo-app |<--------------------| Alloy |--------------------->| Pyroscope |
| :6060    |    /debug/pprof/*   |       |                      | :4040     |
+----------+                     +-------+                      +-----+-----+
                                                                     |
                                                                     v
                                                                +---------+
                                                                | Grafana |
                                                                +---------+
```

- **demo-app**: A Go application that exposes standard pprof endpoints on port 6060.
- **Alloy**: Scrapes profiles from `demo-app:6060` and forwards them to Pyroscope.
- **Pyroscope**: Stores and serves profiling data on port 4040.
- **Grafana**: Visualizes profiles through a provisioned Pyroscope data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/continuous-profiling`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh continuous-profiling`

3. Check that all containers are up: `cd alloy-scenarios/continuous-profiling && docker compose ps`

   Expect `demo-app`, `alloy`, `pyroscope`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query profiles in **Explore** with the Pyroscope data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Pyroscope** at http://localhost:4040: Profiling storage backend and UI.
- **Demo app pprof** at http://localhost:6060/debug/pprof/: Raw pprof endpoints on the host.

## Understand the configuration

The `config.alloy` pipeline has two components:

1. **`pyroscope.scrape "default"`**: Scrapes pprof profiles from `demo-app:6060` every 15 seconds with `service_name="demo-app"`.
   Enabled profile types are `process_cpu`, `memory`, `goroutine`, `mutex`, and `block`.
2. **`pyroscope.write "default"`**: Forwards profiles to Pyroscope at `http://pyroscope:4040`.

`livedebugging` is enabled.

## Try it out

1. Open Grafana at http://localhost:3000, open **Explore**, and select the **Pyroscope** data source.

2. Choose a profile type, for example `process_cpu`, and the `demo-app` service.
   Expect flame graphs that show where the application spends time and allocates memory.

3. Alloy scrapes these profile types every 15 seconds:

   - `process_cpu`: functions consuming the most CPU time in the `cpuIntensive` goroutine
   - `memory`: allocation patterns from the `memoryIntensive` goroutine, which allocates 1MB chunks
   - `goroutine`: active goroutines and their stack traces
   - `mutex`: mutex contention profiles
   - `block`: blocking operation profiles

4. Open the Alloy UI at http://localhost:12345 and use live debug on `pyroscope.scrape.default` to watch profiles flow through the pipeline.

## Customize the scenario

Add another target to the `targets` list in `pyroscope.scrape "default"`, enable or disable profile types under `profiling_config`, or change `scrape_interval`.

## Troubleshoot common problems

Use these steps when profiles don't appear or ports conflict.

### No profiles appear in Grafana

Check that `demo-app` is running with `docker compose ps`.
Open http://localhost:6060/debug/pprof/ and check that pprof endpoints respond.
Open the Alloy UI at http://localhost:12345 and check that `pyroscope.scrape.default` and `pyroscope.write.default` are healthy.
Allow one scrape interval, 15 seconds, after the app starts.

### Port conflicts with other services

Ports 3000, 4040, 6060, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `pyroscope.scrape` reference: https://grafana.com/docs/alloy/latest/reference/components/pyroscope/pyroscope.scrape/
- `pyroscope.write` reference: https://grafana.com/docs/alloy/latest/reference/components/pyroscope/pyroscope.write/
- eBPF host profiling scenario: [../ebpf-host-profiling/](../ebpf-host-profiling/)
