# Java continuous profiling

This scenario shows zero-code JVM profiling with [`pyroscope.java`](https://grafana.com/docs/alloy/latest/reference/components/pyroscope/pyroscope.java/).
Alloy discovers a running JVM with `discovery.process`, attaches [async-profiler](https://github.com/async-profiler/async-profiler), and streams CPU and allocation profiles to Pyroscope.
The `config.alloy` file defines the pipeline.

The demo app in `app/Main.java` has two deterministic hot paths so flame graphs are easy to read:

- `Main.burnCpu`: dominates the CPU profile `process_cpu`
- `Main.churnAllocations`: dominates the allocation profile `memory:alloc_in_new_tlab_bytes`

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 4040 for Pyroscope, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Understand the architecture

Alloy joins the `java-app` container PID namespace, attaches async-profiler to the JVM, and forwards profiles to Pyroscope.

```text
+----------+     discovery + attach     +-------+     +-----------+     +---------+
| java-app |<-------------------------->| Alloy |---->| Pyroscope |---->| Grafana |
| JVM      |     async-profiler         |       |     |   :4040   |     |  :3000  |
+----------+                            +-------+     +-----------+     +---------+
```

- **java-app**: JVM workload with `Main.burnCpu` and `Main.churnAllocations` hot paths.
- **Alloy**: Discovers the JVM, attaches async-profiler, and forwards profiles to Pyroscope.
- **Pyroscope**: Stores and serves flame graphs on port 4040.
- **Grafana**: Visualizes profiles through a provisioned Pyroscope data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.
   The `java-app` image must be built on first run.

   - Navigate to this scenario: `cd alloy-scenarios/java-profiling`
   - Deploy the scenario: `docker compose up -d --build`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.
   Build `java-app` first if the image does not exist yet.

   - Build the demo app: `cd alloy-scenarios/java-profiling && docker compose build java-app`
   - Deploy the scenario: `./run-example.sh java-profiling`

3. Check that all containers are up: `cd alloy-scenarios/java-profiling && docker compose ps`

   Expect `java-app`, `alloy`, `pyroscope`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: **Drilldown → Profiles** or **Explore** with the Pyroscope data source, with no login required.
- **Pyroscope** at http://localhost:4040: Direct access to flame graphs and the service selector.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.

## Understand the configuration

`pyroscope.java` uses the JVM dynamic-attach mechanism, which requires Alloy and the target JVM to share a PID namespace and `/tmp` volume.

| Compose setting                                       | Why                                                                                                                                             |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `pid: "container:java-app"` on the `alloy` service    | Alloy must see the JVM in its own PID namespace for `discovery.process` and the attach handshake                                                |
| `cap_add: [SYS_PTRACE]`                               | The attach mechanism performs ptrace-style access checks                                                                                        |
| `jvm-tmp` volume mounted at `/tmp` in both containers | The JVM attach socket at `/tmp/.java_pid<PID>` and the async-profiler library Alloy extracts must be visible to both processes at the same path |
| `container_name: java-app`                            | Gives the `pid:` reference a stable target                                                                                                      |

No agent JAR, no `-javaagent` flag, and no code changes are required.
The JVM starts like any other application.
`discovery.process` requires root and PID-namespace visibility, which the compose settings above provide.

The `config.alloy` pipeline has four components:

1. **`discovery.process "all"`**: Discovers processes visible to Alloy every 5 seconds with executable and command-line metadata.
2. **`discovery.relabel "java"`**: Keeps only processes whose executable ends in `/java` and sets `service_name` to `java-app`.
3. **`pyroscope.java "jvm"`**: Attaches async-profiler with `interval = "15s"`, `event = "itimer"`, `cpu = true`, `alloc = "512k"`, `lock = "10ms"`, and `sample_rate = 100`, then forwards profiles to `pyroscope.write.default`.
4. **`pyroscope.write "default"`**: Sends profiles to Pyroscope at `http://pyroscope:4040`.

The `java-app` Dockerfile passes `-XX:+DebugNonSafepoints` so async-profiler reports accurate JIT frame names instead of `[unknown]` frames.
`livedebugging` is enabled.

## Try it out

Allow about 15 seconds after bring-up for the first profile collection interval.

1. Open Grafana at http://localhost:3000 and open **Drilldown → Profiles**, or open Pyroscope at http://localhost:4040.
   Select the `java-app` service and compare these profile types:

   - `process_cpu`: flame graph dominated by `Main.burnCpu`, `Main.countPrimes`, and `Main.isPrime`
   - `memory:alloc_in_new_tlab_bytes`: dominated by `Main.churnAllocations` allocating 256 KiB blocks through a bounded ring
   - `lock`: collected with `lock = "10ms"` in `profiling_config`

2. Verify from your terminal:

   ```sh
   curl -s 'http://localhost:4040/pyroscope/render?query=process_cpu:cpu:nanoseconds:cpu:nanoseconds%7Bservice_name%3D%22java-app%22%7D&from=now-5m&format=json' \
     | jq -r '.flamebearer.names[]' | grep Main.burnCpu
   ```

3. Open the Alloy UI at http://localhost:12345 and check `pyroscope.java.jvm` for discovered targets and attach status.

## Customize the scenario

- **Switch CPU sampling mode**: `event = "itimer"` samples CPU with setitimer signals and needs no `perf_event` kernel access, so it works in restricted environments such as CI runners and containers without extra privileges.
  Where the kernel allows perf events, set `event = "cpu"` in `pyroscope.java "jvm"` for kernel-stack visibility too.
- **Recreate the JVM container**: If you recreate `java-app`, restart the `alloy` container too. Its `pid: "container:java-app"` binding refers to the container instance that existed when Alloy started.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `pyroscope.java` reference: https://grafana.com/docs/alloy/latest/reference/components/pyroscope/pyroscope.java/
- eBPF host profiling scenario: [../ebpf-host-profiling/](../ebpf-host-profiling/)
- Go pprof scraping scenario: [../continuous-profiling/](../continuous-profiling/)
