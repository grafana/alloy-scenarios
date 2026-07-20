# Build a minimal OpenTelemetry Collector with the OpenTelemetry Collector
# Builder (OCB), then package the single static binary into a tiny runtime image.
#
# OCB reads builder-config.yaml, generates the collector's main package with only
# the listed components, and compiles it. Because we list just OTLP + batch +
# memory_limiter + debug, the binary is a fraction of the size of full Alloy.

ARG GO_VERSION=1.25
FROM golang:${GO_VERSION} AS build

# OCB version. Keep this in step with the otelcol_version in builder-config.yaml.
ARG OCB_VERSION=v0.147.0

# Static binary so it runs on a distroless/scratch base.
ENV CGO_ENABLED=0

WORKDIR /build
COPY builder-config.yaml .

# Generate and compile the distribution. Output binary: ./_build/minimal-otelcol
RUN go run go.opentelemetry.io/collector/cmd/builder@${OCB_VERSION} --config builder-config.yaml

# Minimal runtime: distroless static (no shell, no package manager).
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /build/_build/minimal-otelcol /minimal-otelcol
ENTRYPOINT ["/minimal-otelcol"]
CMD ["--config=/etc/otelcol/config.yaml"]
