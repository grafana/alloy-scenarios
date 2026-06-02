# eBPF host profiling

Profile every process on a Linux host with Grafana Alloy's `pyroscope.ebpf` component -- no language agents, no application code changes, no `pprof` endpoints to expose. The kernel does the sampling and Alloy ships CPU stack traces to Grafana Pyroscope.

## What this scenario demonstrates

- **`pyroscope.ebpf`** -- host-wide eBPF CPU sampler that profiles every process the Alloy container can see through the host PID namespace.
- **Docker container discovery** -- `discovery.docker` enumerates running containers and `discovery.relabel` turns each container name into a `service_name` so the flame graph is grouped per workload.
- **`pyroscope.write`** -- pushes the collected profiles to a local Pyroscope server.
- **Two workloads** -- `stress-cpu` and `stress-mem` run a small, dependency-free Go load generator (`app/main.go`) that ships with the scenario, so the demo owns its workload instead of pulling a third-party stress image. They give the profiler something interesting to sample and let you switch the service filter to see how the flame graph changes.

This is the "no-instrumentation" alternative to the `continuous-profiling/` scenario. That scenario scrapes a Go application's `/debug/pprof` endpoints; this one needs nothing from the workloads themselves -- the kernel samples them via eBPF with no `pprof` endpoint and no SDK.

## Overview

The example includes:

- **alloy** -- runs with `privileged: true` and `pid: host` so the eBPF loader can attach perf events in the host kernel and follow PIDs of other containers.
- **pyroscope** -- profile storage and query backend at port 4040.
- **grafana** -- pre-configured with the Pyroscope datasource for flame graphs.
- **stress-cpu** -- the bundled Go app in CPU mode (`go run . cpu`); tight arithmetic loops, so the flame graph is dominated by `main.cpuLoop`.
- **stress-mem** -- the same app in memory mode (`go run . mem`); a rolling 128 MiB of allocations and writes, so its flame graph splits between `main.memLoop` and the Go runtime's allocation/`memclr` paths and looks visibly different from `stress-cpu`.

Both run on the official, multi-arch `golang` image, so they build and run natively on amd64 and arm64 (Apple Silicon) -- the flame graph shows real Go frames rather than QEMU emulation internals.

## Prerequisites

- A **Linux host** (kernel 5.4+ recommended), or **Docker Desktop** on macOS / Windows -- the eBPF loader attaches perf events on the Linux kernel that Docker Desktop runs the engine in, and this scenario has been verified working on Docker Desktop (Apple Silicon) out of the box. Running it inside another container (nested Docker) is *not* supported -- the inner container cannot raise `RLIMIT_MEMLOCK` even with `privileged: true`.
- Docker and Docker Compose.
- Root or `sudo` to start the `privileged` Alloy container.

## Running the demo

1. Clone the repository:
   ```
   git clone https://github.com/grafana/alloy-scenarios.git
   cd alloy-scenarios
   ```

2. Navigate to this example directory:
   ```
   cd ebpf-host-profiling
   ```

3. Start the stack:
   ```
   docker compose up -d
   ```

   Or, from the repository root, with centralized image versions:
   ```
   ./run-example.sh ebpf-host-profiling
   ```

4. Access Grafana at <http://localhost:3000>.

## What to expect

Within ~30 seconds, Alloy starts pushing CPU profiles to Pyroscope. The eBPF profiler samples at 19 Hz by default (`sample_rate = 19`) and Alloy flushes a batch every 15 seconds (`collect_interval = "15s"`).

To view flame graphs:

1. Open Grafana at <http://localhost:3000>.
2. Go to **Explore** and pick the **Pyroscope** datasource.
3. Choose the profile type **`process_cpu` / cpu (nanoseconds)**.
4. In the query, set the service filter to `service_name="stress-cpu"`. You should see a tall, narrow flame graph dominated by `main.cpuLoop` (and the `math/rand` calls it makes) -- because `stress-cpu` does nothing but burn CPU.
5. Change the filter to `service_name="stress-mem"`. The flame graph now splits between `main.memLoop` and the Go runtime's allocation paths (`runtime.mallocgc`, `runtime.memclrNoHeapPointers`, GC). Switching filters this way is the test for "the eBPF profiler attributes samples to the right container."

You can also open Pyroscope's own UI directly at <http://localhost:4040> and use its service selector for the same comparison.

### Useful endpoints

- Alloy UI: <http://localhost:12345> -- inspect the pipeline. Open `pyroscope.ebpf.default` to see the component status, the discovered targets, and any eBPF loader errors.
- Pyroscope UI: <http://localhost:4040>.
- Grafana: <http://localhost:3000>.

## Architecture

```
                                              host PID namespace (shared)
                          ┌──────────────────────────────────────────────────────┐
                          │                                                      │
   ┌────────────┐         │    perf events / eBPF probes                         │
   │ stress-cpu │◀────────┤                                                      │
   └────────────┘         │              ┌───────────┐                           │
                          │              │   alloy   │   push profiles           │
   ┌────────────┐         │◀─────────────│ (privileged)─────────────────────────▶┌──────────┐
   │ stress-mem │◀────────┤              │  pyroscope│                           │Pyroscope │
   └────────────┘         │              │   .ebpf   │                           │  :4040   │
                          │              └─────┬─────┘                           └────┬─────┘
                          └────────────────────│─────────────────────────────────────┼──────┘
                                          discover via                               ▼
                                        /var/run/docker.sock                   ┌──────────┐
                                                                               │ Grafana  │
                                                                               │  :3000   │
                                                                               └──────────┘
```

`pid: host` lets the Alloy container see other containers' PIDs, and the `__container_id__` label (added automatically by `discovery.docker`) lets `pyroscope.ebpf` map each kernel sample back to the container that produced it.

## Key configuration

Two things in `docker-compose.yml` are non-negotiable for `pyroscope.ebpf` to work:

- **`privileged: true`** -- the eBPF loader needs to raise `RLIMIT_MEMLOCK` and load BPF programs into the kernel. Without `privileged`, you can grant a narrower set of capabilities -- `BPF`, `PERFMON`, `SYS_PTRACE`, `CHECKPOINT_RESTORE`, `SYS_RESOURCE`, `DAC_READ_SEARCH`, `SYSLOG` -- but `privileged` is the simplest setting for a demo.
- **`pid: host`** -- without this, Alloy only sees its own PID; with it, Alloy sees every process on the host and can map samples to the right container.

In `config.alloy`:

- `discovery.docker` reads the container list from the Docker socket so the profiler knows which `container_id` belongs to which container name.
- `discovery.relabel` rewrites `__meta_docker_container_name` (`/stress-cpu`) into a clean `service_name` (`stress-cpu`). `pyroscope.ebpf` requires a `service_name` on every target.
- `pyroscope.ebpf` uses default settings (`collect_interval = "15s"`, `sample_rate = 19`). For tighter sampling, lower `collect_interval` -- but at the cost of more samples shipped per minute.

## Customize

- **Profile only one container**: filter `discovery.relabel.containers.output` with a regex on `__meta_docker_container_name` (or set `__process_pid__` directly).
- **Profile bare-metal processes too**: add an extra `targets` entry of the form `{"__process_pid__" = "<pid>", "service_name" = "..."}`. eBPF will sample that PID alongside the container ones.
- **Capture off-CPU profiles**: set `off_cpu_threshold` in the `pyroscope.ebpf` block (see the [component reference](https://grafana.com/docs/alloy/latest/reference/components/pyroscope/pyroscope.ebpf/)).
- **Profile interpreted languages**: `pyroscope.ebpf` includes interpreter tracers for Python, Ruby, PHP, Perl, V8 (Node.js), and the JVM by default. Add a workload such as a Python or Node.js script and its frames will show up in the flame graph without any extra setup.

## Stop

```
docker compose down
```
