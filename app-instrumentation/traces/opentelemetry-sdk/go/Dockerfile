# Single-stage build. `go mod tidy` resolves the latest OpenTelemetry module
# versions from the proxy at build time, so no versions are pinned in go.mod.
FROM golang:1.25-alpine
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
