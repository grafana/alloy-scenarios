# Custom Alloy builds

These scenarios show how to **build a tailored Grafana Alloy / OpenTelemetry Collector image** instead of using the stock `grafana/alloy` distribution — for example when you want a slim collector that contains only the parts you use, or (later) when you need a component that doesn't ship by default.

## How building a custom Alloy works

Alloy is a single compiled Go binary. It has **no dynamic plugin system** — you can't drop a `.so` file next to it and have it loaded at runtime. Anything custom must be **compiled in**. There are two supported, documented ways to produce a tailored build:

1. **Build a custom OpenTelemetry Collector distribution with OCB.** The [OpenTelemetry Collector Builder (OCB)](https://github.com/open-telemetry/opentelemetry-collector/tree/main/cmd/builder) assembles a collector from only the modules you list in a manifest. Alloy itself uses OCB internally to generate its OpenTelemetry engine (see `collector/builder-config.yaml` in the Alloy repo). This is the right tool when your goal is "only what I need." It's what the scenario below demonstrates.

2. **Fork Alloy and add a Go component.** You add a package under `internal/component/...`, register it in `internal/component/all`, and rebuild with `make alloy`. The new component then works in normal Alloy (River) configuration, exactly like the built-in components. This is documented in Alloy's [developer guide for adding components](https://github.com/grafana/alloy/blob/main/docs/developer/add-otel-component.md). (Worked examples of this path may be added here later.)

> **Note:** Alloy also has a config-language feature called [**custom components**](https://grafana.com/docs/alloy/latest/get-started/components/custom-components/) — the `declare` and `import` blocks. That feature bundles *existing built-in* components into reusable units; it involves no Go and no rebuild. It is a different thing from what these scenarios teach (producing a custom image), which is why this directory is named `custom-builds` rather than `custom-components`.

## The scenarios

| Scenario | What it teaches | Build method |
| -------- | --------------- | ------------ |
| [minimal-otel](minimal-otel/) | Build a collector with **only the OTel parts you need** (OTLP in, batch/memory_limiter, OTLP out) and compare its image size to full Alloy. | OCB |

`minimal-otel` produces a **pure OpenTelemetry Collector** (Alloy's lineage), so it is configured with an OTel **YAML** file (`config.yaml`), not Alloy River syntax. The image versions in its `docker-compose.yml` are pinned to the values in the repo-root `image-versions.env`.

## Honest limitations (no hand-waving)

- There is **no build flag that slims the full Alloy (River) binary** to "only OTel." Alloy's `GO_TAGS` only toggle a few platform features (for example `netgo`, `embedalloyui`, `promtail_journal_enabled`). That is why `minimal-otel` uses OCB to produce a separate, minimal OTel Collector instead of a trimmed Alloy.
- Alloy ships an in-process, OCB-generated OTel engine you can run with `alloy otel`, but it is currently **experimental**, so `minimal-otel` anchors on standalone OCB and only mentions the engine as the Alloy-native equivalent.
