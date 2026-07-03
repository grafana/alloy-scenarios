# Single-stage build. `go mod tidy` resolves the latest prometheus/client_golang
# version from the proxy at build time, so nothing is pinned in go.mod.
FROM golang:1.26-alpine@sha256:3ad57304ad93bbec8548a0437ad9e06a455660655d9af011d58b993f6f615648
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
