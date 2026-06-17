# Single-stage build. `go mod tidy` resolves the latest prometheus/client_golang
# version from the proxy at build time, so nothing is pinned in go.mod.
FROM golang:1.25-alpine
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
