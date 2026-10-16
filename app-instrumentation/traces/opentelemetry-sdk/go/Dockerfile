# Single-stage build. `go mod tidy` resolves the latest OpenTelemetry module
# versions from the proxy at build time, so no versions are pinned in go.mod.
FROM golang:1.26-alpine@sha256:3082400e369fa24d5fc60bca20edab3f6d604e0c5a690ec66b295eff4dd87ade
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
