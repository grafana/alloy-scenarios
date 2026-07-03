# Zero-code instrumentation with Beyla

This scenario shows how Grafana Alloy uses `beyla.ebpf` to auto-instrument an HTTP service with eBPF.
Alloy attaches eBPF probes to the compiled `demo-app` binary and its sockets, so the service needs no OpenTelemetry SDK, no agent, and no code change of any kind.
Alloy forwards the RED metrics `beyla.ebpf` produces to Prometheus and the traces it produces to Tempo.
The `config.alloy` file defines the pipeline.

A `loadgen` container drives continuous traffic against `demo-app`, including a deliberate 404, so you have metrics and traces to explore as soon as the stack starts.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- A Linux host with kernel 5.8 or newer and BPF Type Format enabled, or Docker Desktop on macOS or Windows.
  BTF is on by default on kernel 5.14 and newer.
  The eBPF loader attaches to the Linux kernel that runs the Docker engine, so Docker Desktop's Linux VM works too.
  Nested Docker isn't supported because an inner container can't load eBPF programs into the outer host's kernel.
- Permission to start the `privileged` Alloy container.
- Ports 3000 for Grafana, 9090 for Prometheus, 3200 for Tempo, 8080 for `demo-app`, and 12345 for Alloy free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

| Aspect            | `beyla-zero-code-instrumentation/`             | [`app-instrumentation/traces/opentelemetry-sdk/`](../app-instrumentation/traces/opentelemetry-sdk/) |
| ------------------ | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Code changes       | None                                             | Add the OpenTelemetry SDK to the application                                                          |
| Collection         | eBPF probes on the compiled binary               | The SDK exports spans directly from the process                                                       |
| Host requirements  | `privileged: true` and a shared PID namespace    | Standard container                                                                                    |
| Span detail        | Generic RED metrics and transaction-level spans  | Full manual control over spans and attributes                                                         |

Use this scenario when you can't or don't want to touch application code.
Use the SDK scenario when you control the code and need fine-grained spans.

## Understand the architecture

`loadgen` sends HTTP traffic to `demo-app`.
Alloy shares `demo-app`'s PID namespace, so `beyla.ebpf` attaches eBPF probes to the running binary, turns the observed requests into RED metrics and traces, and forwards both onward.

```text
+---------+     +----------+
| loadgen |---->| demo-app |
+---------+     +----------+
                     ^
                     | shared PID namespace, eBPF probes
                     |
                +----------+     +------------+     +---------+
                |  alloy   |---->| Prometheus |---->|         |
                | (beyla.  |     +------------+     | Grafana |
                |  ebpf)   |---->|   Tempo    |---->|         |
                +----------+     +------------+     +---------+
```

- **loadgen**: Curls `demo-app` in a loop, including a request to a missing order so you see a 404 alongside the healthy routes.
- **demo-app**: A plain Go HTTP API with no instrumentation library of any kind.
- **Alloy**: Runs with `privileged: true` and `pid: "service:demo-app"`, and uses `beyla.ebpf` to instrument `demo-app` from outside the process.
- **Prometheus**: Stores the RED metrics `beyla.ebpf` produces.
- **Tempo**: Stores the traces `beyla.ebpf` produces.
- **Grafana**: Visualizes both through provisioned Prometheus and Tempo data sources.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/beyla-zero-code-instrumentation`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env`.

   - Deploy the scenario: `./run-example.sh beyla-zero-code-instrumentation`

3. Check that all containers are up: `cd alloy-scenarios/beyla-zero-code-instrumentation && docker compose ps`

   Expect `alloy`, `demo-app`, `loadgen`, `prometheus`, `tempo`, and `grafana`.

## Explore the services

- **Grafana** at http://localhost:3000: Query metrics and traces in **Explore**, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query the RED metrics directly.
- **Tempo** at http://localhost:3200: Trace storage backend.
- **demo-app** at http://localhost:8080: The uninstrumented target service. `curl http://localhost:8080/orders` to see it respond.

## Understand the configuration

The `config.alloy` pipeline has four components:

1. **`beyla.ebpf "default"`**: Instruments any process listening on port `8080` inside Alloy's shared PID namespace, labels it `demo-app`, and enables `application` metrics.
   It forwards the traces it generates to `otelcol.exporter.otlp.tempo`.
2. **`prometheus.scrape "beyla"`**: `beyla.ebpf` exposes its RED metrics as a Prometheus scrape target rather than pushing them, so this component pulls them into the pipeline and forwards the samples to `prometheus.remote_write.default`.
3. **`prometheus.remote_write "default"`**: Sends the scraped RED metrics to Prometheus at `http://prometheus:9090/api/v1/write`.
4. **`otelcol.exporter.otlp "tempo"`**: Sends the traces `beyla.ebpf` generates to Tempo at `tempo:4317`.

Two settings in `docker-compose.yml` are required for `beyla.ebpf` to work:

- **`privileged: true`**: Lets Alloy load eBPF programs and read the kernel structures `beyla.ebpf` depends on.
- **`pid: "service:demo-app"`**: Shares `demo-app`'s PID namespace with Alloy, the pattern Beyla's own Docker documentation recommends for instrumenting a single container.
  Without it, `beyla.ebpf` can't see the `demo-app` process to attach probes to it.

`livedebugging` is enabled.

## Try it out

Allow about 15 seconds after bring-up for `loadgen` to start sending traffic and for `beyla.ebpf` to attach to `demo-app`.

1. Open Grafana at http://localhost:3000, open **Explore**, and select the **Tempo** data source.
   Search for `service.name = demo-app` and open a trace.
   Expect spans named `GET /`, `GET /orders`, `GET /orders/`, and `POST /checkout`, with some `POST /checkout` spans marked as errors.

2. Switch to the **Prometheus** data source in **Explore** and run:

   ```promql
   sum by (http_route, http_response_status_code) (rate(http_server_request_duration_seconds_count{job="demo-app"}[1m]))
   ```

   Expect series for `/`, `/orders`, `/orders/`, and `/checkout` with a mix of `200`, `201`, `404`, and `500` status codes.
   The `404` comes from `loadgen` requesting a nonexistent order at `/orders/99`, and the `500` comes from `demo-app`'s simulated checkout failures.

3. Open the Alloy UI at http://localhost:12345 and select `beyla.ebpf.default` to check its health and the process it instruments.
   Select `prometheus.scrape.beyla` and use live debug to watch the RED metrics pass through the pipeline.

## Customize the scenario

- **Instrument your own service**: Point `discovery.instrument.open_ports` and `discovery.instrument.name` in `beyla.ebpf "default"` at your service's port and name, then change `pid: "service:demo-app"` in `docker-compose.yml` to `pid: "service:<YOUR_SERVICE>"`.
- **Add network-level metrics**: Add `"network"` to the `features` list in the `metrics` block of `beyla.ebpf "default"`.
- **Sample traces**: Add a `traces` block with a `sampler` sub-block, for example `name = "traceidratio"` and `arg = "0.1"`, to keep 10% of traces.
- **Group dynamic routes**: Add a `routes` block with `unmatched = "heuristic"` to `beyla.ebpf "default"` so paths such as `/orders/1` and `/orders/2` group into a single route instead of showing up as unmatched.

## Troubleshoot common problems

Use these steps when telemetry doesn't appear, `beyla.ebpf` fails to load, or ports conflict.

### beyla.ebpf instruments the process but no traces or metrics appear

This scenario pins `demo-app` to Go 1.24 for a reason.
`beyla.ebpf` reads Go runtime-internal offsets to track goroutines across a request, and those offsets are specific to each Go version.
When the target binary uses a Go version `beyla.ebpf` doesn't yet support, it still reports the process as instrumented and logs no fatal error, but every trace and RED metric silently drops.

If you point this scenario at your own Go service and see the same symptom, set `debug = true` on `beyla.ebpf "default"` and run `docker compose logs alloy`.
A repeating `can't read newproc1 invocation metadata` message confirms a Go version mismatch.
Rebuild your service with an older, more established Go release and retry.

### No data appears in Grafana after a few minutes

Open the Alloy UI at http://localhost:12345 and check that `beyla.ebpf.default`, `prometheus.scrape.beyla`, and `otelcol.exporter.otlp.tempo` all show a healthy status.
Check that `alloy` runs with `privileged: true` and `pid: "service:demo-app"` in `docker-compose.yml`.

### eBPF fails inside nested Docker

Run this scenario on the Docker host or in Docker Desktop, not inside another container.

### Port conflicts with other services

Ports 3000, 8080, 9090, 3200, and 12345 must be free before you start the stack.
If another service uses one of these ports, edit the port mapping in `docker-compose.yml` before you run `docker compose up -d`.

## Stop the scenario

Run `docker compose down` from the scenario directory.

## Next steps

- `beyla.ebpf` reference: https://grafana.com/docs/alloy/latest/reference/components/beyla/beyla.ebpf/
- Grafana Beyla documentation: https://grafana.com/docs/beyla/latest/
- Beyla security, permissions, and capabilities: https://grafana.com/docs/beyla/latest/security/
- SDK-based tracing scenario: [`app-instrumentation/traces/opentelemetry-sdk/`](../app-instrumentation/traces/opentelemetry-sdk/)
- Related eBPF scenario: [`ebpf-host-profiling/`](../ebpf-host-profiling/)
