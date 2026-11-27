# Single-stage build. `go mod tidy` resolves the latest prometheus/client_golang
# version from the proxy at build time, so nothing is pinned in go.mod.
FROM golang:1.26-alpine@sha256:ecb67f987aa1a57794c91d19ade7ae0209f2f0f5496aaef9e6ae85ddf92d02ab
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
