# OTel Engine Examples

These scenarios use the **Alloy OTel Engine** -- an experimental feature introduced in Alloy v1.14 that lets you run standard [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) YAML configurations directly inside Alloy. Instead of writing Alloy's River/HCL syntax, you use the exact same YAML format that the upstream OTel Collector uses.

## What is the Alloy OTel Engine?

Grafana Alloy has traditionally used its own **River** configuration language (HCL-like syntax in `config.alloy` files). Starting with v1.14, Alloy ships an experimental **OTel Engine** that accepts standard OTel Collector YAML. This means:

- **No new language to learn** -- if you already know OTel Collector config, you can use Alloy directly
- **Copy-paste from upstream docs** -- OTel Collector examples work as-is
- **Migration path** -- move from vanilla OTel Collector to Alloy without rewriting configs
- **Best of both worlds** -- Alloy's single-binary distribution with OTel Collector's YAML config

The OTel Engine is started with:

```bash
alloy otel --config=<CONFIG_FILE>
```

You can validate configs before running:

```bash
alloy otel validate --config=<CONFIG_FILE>
```

## Running These Examples

Each scenario has a `docker-compose.yml` with the full stack:

```bash
cd <scenario-dir> && docker compose up -d
```

Or from the repo root with centralized image versions:

```bash
cd otel-examples/<scenario-dir> && docker compose --env-file ../../image-versions.env up -d
```

### Access the stack

- **Grafana**: [http://localhost:3000](http://localhost:3000) (no login required)
- **Alloy OTel Engine**: [http://localhost:8888](http://localhost:8888) (OTel engine HTTP server -- note: this is NOT the same as the River UI on port 12345)

### Stop

```bash
docker compose down
```

## Scenarios

| Scenario | Description | Key OTel Components |
|----------|-------------|-------------------|
| [filelog-processing](filelog-processing/) | Collect and parse mixed-format log files (JSON + plaintext) using the filelog receiver's operator chain | `filelog` receiver, `json_parser`, `regex_parser`, `severity_parser` operators |
| [pii-redaction](pii-redaction/) | Scrub credit cards, emails, and IP addresses from traces and logs using OTTL `replace_pattern` | `transform` processor (OTTL) |
| [routing-multi-tenant](routing-multi-tenant/) | Route logs to different Loki tenants based on resource attributes using fan-out + filter | `forward` connector, `filter` processor, `resource` processor |
| [cost-control](cost-control/) | Drop health checks, filter debug logs, and apply head-based sampling to reduce telemetry volume | `filter` processor, `probabilistic_sampler` processor |
| [resource-enrichment](resource-enrichment/) | Auto-discover and attach host/OS/Docker metadata to all telemetry signals | `resourcedetection` processor (env, system, docker) |
| [count-connector](count-connector/) | Derive count metrics (request rate, error rate) from traces and logs | `count` connector |
| [ottl-transform](ottl-transform/) | A cookbook of OTTL patterns: JSON parsing, severity mapping, attribute promotion, truncation | `transform` processor (OTTL) |
| [host-metrics](host-metrics/) | Collect CPU, memory, disk, network metrics -- an OTel-native replacement for node_exporter | `hostmetrics` receiver |
| [multi-pipeline-fanout](multi-pipeline-fanout/) | Send traces to two backends with different processing per destination (full vs. sampled) | `forward` connector, `probabilistic_sampler` processor |
| [kafka-buffer](kafka-buffer/) | Buffer traces through Kafka for durability and backpressure handling | `kafka` receiver/exporter |

## OTel Engine vs. River Configs

For comparison, the parent repo's existing scenarios (e.g., `otel-basic-tracing/`, `otel-span-metrics/`) also have OTel YAML alternatives alongside their River configs. Run those with:

```bash
docker compose -f docker-compose.yml -f docker-compose-otel.yml up -d
```

## Available Connectors

The Alloy OTel Engine supports these connectors: `count`, `grafanacloud`, `servicegraph`, `spanmetrics`, `forward`.

## Further Reading

- [Alloy OTel Engine Documentation](https://grafana.com/docs/alloy/latest/set-up/otel_engine/)
- [OpenTelemetry Collector Configuration](https://opentelemetry.io/docs/collector/configuration/)
- [OTTL (OpenTelemetry Transformation Language)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/pkg/ottl)
