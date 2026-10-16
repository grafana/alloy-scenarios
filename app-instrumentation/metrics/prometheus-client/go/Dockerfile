# Single-stage build. `go mod tidy` resolves the latest prometheus/client_golang
# version from the proxy at build time, so nothing is pinned in go.mod.
FROM golang:1.26-alpine@sha256:3082400e369fa24d5fc60bca20edab3f6d604e0c5a690ec66b295eff4dd87ade
WORKDIR /app
COPY . .
RUN go mod tidy && go build -o app .
CMD ["./app"]
