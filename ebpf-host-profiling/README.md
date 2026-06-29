# eBPF host profiling

This scenario shows how Grafana Alloy profiles every process on a Linux host with `pyroscope.ebpf`.
The kernel samples CPU stacks through eBPF, so workloads need no language agents, no SDK, and no `pprof` endpoints.
Alloy discovers Docker containers, maps samples to a `service_name`, and forwards profiles to Grafana Pyroscope.
The `config.alloy` file defines the pipeline.

Two bundled Go workloads, `stress-cpu` and `stress-mem`, give the profiler distinct flame graphs to compare.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- A Linux host with kernel 5.4 or newer, or Docker Desktop on macOS or Windows.
  The eBPF loader attaches to the Linux kernel that runs the Docker engine.
  Nested Docker is not supported because an inner container cannot raise `RLIMIT_MEMLOCK` even with `privileged: true`.
- Permission to start the `privileged` Alloy container.
- Ports 3000 for Grafana, 4040 for Pyroscope, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

| Aspect            | `ebpf-host-profiling/`             | [`continuous-profiling/`](../continuous-profiling/) |
| ----------------- | ---------------------------------- | --------------------------------------------------- |
| Collection        | `pyroscope.ebpf` kernel sampling   | `pyroscope.scrape` of `/debug/pprof`                |
| Workload setup    | None required                      | App must expose pprof on port 6060                  |
| Host requirements | `privileged: true` and `pid: host` | Standard container                                  |

Use this scenario when you want host-wide profiling with no application instrumentation.
Use `continuous-profiling/` when you control the app and can expose pprof.

## Understand the architecture

Alloy attaches eBPF probes in the host kernel, attributes samples to discovered containers, and pushes profiles to Pyroscope.

```text
                          host PID namespace (shared)
                     +---------------------------------------+
                     |                                       |
   +------------+    |    perf events / eBPF probes          |
   | stress-cpu |<---|                                       |
   +------------+    |    +-----------------+                |
                     |    |   alloy         |  push profiles |   +-----------+
   +------------+    |<---| (privileged)    |------------------->| Pyroscope |
   | stress-mem |<---|    |  pyroscope.ebpf |                |   |  :4040    |
   +------------+    |    +-----------------+                |   +-----------+
                     |             ^                         |         |
                     +-------------|-------------------------+         |
                                   |                                   v
                                discover via                      +----------+
                                /var/run/docker.sock              | Grafana  |
                                                                  |  :3000   |
                                                                  +----------+
```

- **stress-cpu**: Bundled Go app in CPU mode.
  The flame graph is dominated by `main.cpuLoop` and `math/rand` calls.
- **stress-mem**: Same app in memory mode with a rolling 128 MiB working set.
  Its flame graph splits between `main.memLoop` and Go runtime allocation paths.
- **Alloy**: Runs with `privileged: true` and `pid: host`, discovers containers through the Docker socket, and profiles with `pyroscope.ebpf`.
- **Pyroscope**: Stores profiles on port 4040.
- **Grafana**: Visualizes flame graphs through a provisioned Pyroscope data source.

Both workloads use the official multi-arch `golang` image, so they run natively on amd64 and arm64.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/ebpf-host-profiling`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh ebpf-host-profiling`

3. Check that all containers are up: `cd alloy-scenarios/ebpf-host-profiling && docker compose ps`

   Expect `alloy`, `pyroscope`, `grafana`, `stress-cpu`, and `stress-mem`.

## Explore the services

- **Grafana** at http://localhost:3000: Query profiles in **Explore** with the Pyroscope data source, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Pyroscope** at http://localhost:4040: Profile storage backend and UI.

## Understand the configuration

The `config.alloy` pipeline has four components:

1. **`discovery.docker "local_containers"`**: Reads the container list from the Docker socket.
2. **`discovery.relabel "containers"`**: Sets `service_name` from the container name.
   `pyroscope.ebpf` requires a `service_name` on every target.
3. **`pyroscope.ebpf "default"`**: Host-wide eBPF CPU profiler that forwards samples to `pyroscope.write.default`.
   Default settings use `collect_interval = "15s"` and `sample_rate = 19`.
4. **`pyroscope.write "default"`**: Sends profiles to Pyroscope at `http://pyroscope:4040`.

Two settings in `docker-compose.yml` are required for eBPF profiling:

- **`privileged: true`**: Lets the eBPF loader raise `RLIMIT_MEMLOCK` and load BPF programs into the kernel.
- **`pid: host`**: Lets Alloy see every process on the host and map samples to the right container.

`pid: host` shares the host PID namespace.
The `__container_id__` label from `discovery.docker` lets `pyroscope.ebpf` map kernel samples back to a container.

`livedebugging` is enabled.

## Try it out

Allow about 30 seconds after bring-up for Alloy to start pushing CPU profiles to Pyroscope.

1. Open Grafana at http://localhost:3000, open **Explore**, and select the **Pyroscope** data source.

2. Choose the profile type `process_cpu` and set the service filter to `service_name="stress-cpu"`.
   Expect a tall flame graph dominated by `main.cpuLoop`.

3. Change the filter to `service_name="stress-mem"`.
   The flame graph splits between `main.memLoop` and Go runtime allocation paths such as `runtime.mallocgc` and `runtime.memclrNoHeapPointers`.

4. Open the Alloy UI at http://localhost:12345 and check `pyroscope.ebpf.default` for component status, discovered targets, and any eBPF loader errors.

5. Open Pyroscope at http://localhost:4040 and use the service selector for the same comparison.

## Customize the scenario

- **Profile one container**: Filter `discovery.relabel.containers.output` with a regex on `__meta_docker_container_name`, or set `__process_pid__` directly.
- **Profile a host process**: Add a target such as `{"__process_pid__" = "<pid>", "service_name" = "..."}` to `pyroscope.ebpf "default"`.
- **Capture off-CPU profiles**: Set `off_cpu_threshold` in the `pyroscope.ebpf` block.
- **Profile interpreted languages**: `pyroscope.ebpf` includes interpreter tracers for Python, Ruby, PHP, Perl, V8, and the JVM by default.
- **Lower collect interval**: Reduce `collect_interval` on `pyroscope.ebpf "default"` for tighter sampling at the cost of more data shipped per minute.

## Troubleshoot common problems

Use these steps when profiles don't appear, eBPF fails to load, or ports conflict.

### No profiles appear in Grafana

Open the Alloy UI at http://localhost:12345 and check `pyroscope.ebpf.default` for eBPF loader errors.
Check that `alloy` runs with `privileged: true` and `pid: host` in `docker-compose.yml`.
Allow about 30 seconds after the stack starts.

### eBPF fails inside nested Docker

Run this scenario on the Docker host or in Docker Desktop, not inside another container.

### Port conflicts with other services

Ports 3000, 4040, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `pyroscope.ebpf` reference: https://grafana.com/docs/alloy/latest/reference/components/pyroscope/pyroscope.ebpf/
- Continuous profiling scenario: [../continuous-profiling/](../continuous-profiling/)
