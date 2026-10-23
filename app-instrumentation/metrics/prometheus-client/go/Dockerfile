# Single-stage build. `go mod tidy` resolves the latest prometheus/client_golang
# version from the proxy at build time, so nothing is pinned in go.mod.
FROM golang:1.26-alpine@sha256:27f2d3b83cfc5803c8078f8e730af0f7c431bf067afaec8f60a36fb763187cba
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
