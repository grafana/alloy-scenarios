# Java Continuous Profiling with Grafana Alloy

This scenario demonstrates zero-code-change JVM profiling with Alloy's [`pyroscope.java`](https://grafana.com/docs/alloy/latest/reference/components/pyroscope/pyroscope.java/) component: Alloy discovers a running JVM with `discovery.process`, attaches [async-profiler](https://github.com/async-profiler/async-profiler) to it, and streams CPU and allocation profiles to Grafana Pyroscope.

The demo app (`app/Main.java`) has two deterministic hot paths so the flame graphs are easy to read:

* `Main.burnCpu` → dominates the **CPU** profile (`process_cpu`)
* `Main.churnAllocations` → dominates the **allocation** profile (`memory:alloc_in_new_tlab_bytes`)

## How the attach works (and why the compose file looks like this)

`pyroscope.java` uses the JVM dynamic-attach mechanism, which requires Alloy and the target JVM to effectively share a machine:

| Compose setting | Why |
|-----------------|-----|
| `pid: "container:java-app"` on the `alloy` service | Alloy must see the JVM in its own PID namespace for `discovery.process` and the attach handshake |
| `cap_add: [SYS_PTRACE]` | The attach mechanism performs ptrace-style access checks |
| `jvm-tmp` volume mounted at `/tmp` in **both** containers | The JVM's attach socket (`/tmp/.java_pid<PID>`) and the async-profiler library Alloy extracts must be visible to both processes at the same path |
| `container_name: java-app` | Gives the `pid:` reference a stable target |

No agent jar, no `-javaagent` flag, no code changes — the JVM is started like any other app.

## Prerequisites

- Docker and Docker Compose installed

## Getting Started

```bash
git clone https://github.com/grafana/alloy-scenarios.git
cd alloy-scenarios/java-profiling
docker compose up -d --build
```

## Access Points

| Service   | URL                    |
|-----------|------------------------|
| Grafana   | http://localhost:3000  |
| Pyroscope | http://localhost:4040  |
| Alloy UI  | http://localhost:12345 |

## What to Expect

Profiles arrive after the first collection interval (15 seconds in `config.alloy`). In Grafana, open **Drilldown → Profiles** (or the Pyroscope UI at http://localhost:4040) and select the `java-app` service:

* **process_cpu** — the flame graph is dominated by `Main.burnCpu` → `Main.countPrimes` → `Main.isPrime`, with real method names rather than `[unknown]` frames (the Dockerfile passes `-XX:+DebugNonSafepoints` for accurate JIT frame info).
* **memory:alloc_in_new_tlab_bytes** — dominated by `Main.churnAllocations` allocating 256 KiB blocks through a bounded ring.
* **lock** and **wall** profiles are also collected (`lock = "10ms"` in `profiling_config`).

To verify headlessly:

```bash
curl -s 'http://localhost:4040/pyroscope/render?query=process_cpu:cpu:nanoseconds:cpu:nanoseconds%7Bservice_name%3D%22java-app%22%7D&from=now-5m&format=json' \
  | jq -r '.flamebearer.names[]' | grep Main.burnCpu
```

## Configuration Notes

* `event = "itimer"` (the default) samples CPU with setitimer signals and needs no `perf_event` kernel access, so it works in restricted environments such as CI runners and containers without extra privileges. Where the kernel allows perf events, `event = "cpu"` gives kernel-stack visibility too.
* `discovery.process` requires root and PID-namespace visibility — both provided by the compose settings above.
* If you recreate the `java-app` container, restart the `alloy` container too: its `pid: "container:java-app"` binding refers to the container instance that existed when Alloy started.

## Stopping the Scenario

```bash
docker compose down
```
