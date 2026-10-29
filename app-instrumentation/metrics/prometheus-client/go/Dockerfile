# Single-stage build. `go mod tidy` resolves the latest prometheus/client_golang
# version from the proxy at build time, so nothing is pinned in go.mod.
FROM golang:1.26-alpine@sha256:a2012b4a1d1f9f7e9f44e0d39b805a901e856b1dd80b4e6ee4338db547050308
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
