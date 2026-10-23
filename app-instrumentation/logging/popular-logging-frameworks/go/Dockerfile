FROM golang:1.26-alpine@sha256:27f2d3b83cfc5803c8078f8e730af0f7c431bf067afaec8f60a36fb763187cba

WORKDIR /app

# Copy go.mod and go.sum for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY main.go .

RUN go build -o logging_example main.go

CMD ["./logging_example"] 