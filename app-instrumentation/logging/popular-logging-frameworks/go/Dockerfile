FROM golang:1.25-alpine@sha256:d9b2e14101f27ec8d09674cd01186798d227bb0daec90e032aeb1cd22ac0f029

WORKDIR /app

# Copy go.mod and go.sum for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY main.go .

RUN go build -o logging_example main.go

CMD ["./logging_example"] 