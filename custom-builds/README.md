# Custom Alloy builds

These scenarios show how to build a tailored image based on Grafana Alloy or OpenTelemetry Collector instead of the default `grafana/alloy` image.
You'll use this approach when you want a smaller OpenTelemetry Collector image for a focused pipeline, or when you need custom build behavior.

## How custom Alloy builds work

Grafana Alloy includes an OpenTelemetry engine.
It uses the OpenTelemetry Collector runtime and OpenTelemetry YAML configuration for that engine.
Refer to the published documentation for [OpenTelemetry in Alloy](https://grafana.com/docs/alloy/latest/introduction/otel_alloy/).

You can build custom images with two common paths:

1. **Build a custom OpenTelemetry Collector distribution with OCB.**
   The [OpenTelemetry Collector Builder](https://opentelemetry.io/docs/collector/custom-collector/) builds a Collector distribution from modules you list in a manifest.
   Alloy documentation describes OCB custom builds in [Grafana Alloy maintenance scope](https://grafana.com/docs/alloy/latest/reference/release-information/alloy-maintenance/).

2. **Fork Alloy and add a Go component.**
   You add a component in source code and rebuild Alloy.
   This path targets advanced customizations in Alloy syntax pipelines.
   Grafana Alloy public docs focus on OCB custom builds.
   For this workflow, refer to the developer guide in the Alloy repository: [Add OpenTelemetry components](https://github.com/grafana/alloy/blob/main/docs/developer/add-otel-component.md).

> **Note:** Alloy also includes [custom components](https://grafana.com/docs/alloy/latest/get-started/components/custom-components/) through `declare` and `import` blocks.
> That feature composes existing components in Alloy syntax.
> It doesn't build a custom binary.

## Scenarios

| Scenario                      | Description                                                                                                                             | Build method |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| [minimal-otel](minimal-otel/) | Build a collector with only the OpenTelemetry components you need for OTLP receive, batch and memory limit processing, and OTLP export. | OCB          |

## Known limits

- The `alloy otel` command is experimental.
  Refer to the published [otel command reference](https://grafana.com/docs/alloy/latest/reference/cli/otel/).
- Custom builds can include behavior outside standard maintenance scope.
  Refer to [Grafana Alloy maintenance scope](https://grafana.com/docs/alloy/latest/reference/release-information/alloy-maintenance/).
- `minimal-otel` uses standalone OpenTelemetry Collector build output and OpenTelemetry YAML configuration.
