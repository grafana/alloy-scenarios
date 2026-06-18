FROM golang:1.26-alpine@sha256:3ad57304ad93bbec8548a0437ad9e06a455660655d9af011d58b993f6f615648

WORKDIR /app

# Copy go.mod and go.sum for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY main.go .

RUN go build -o logging_example main.go

CMD ["./logging_example"] 