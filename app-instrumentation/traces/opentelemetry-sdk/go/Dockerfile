# Single-stage build. `go mod tidy` resolves the latest OpenTelemetry module
# versions from the proxy at build time, so no versions are pinned in go.mod.
FROM golang:1.26-alpine@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
