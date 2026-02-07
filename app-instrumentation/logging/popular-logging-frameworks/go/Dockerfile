FROM golang:1.24-alpine@sha256:6b597b1078d050ed09eb75bc1942e1085ce2da15905190b4d01044f7bc612b81

WORKDIR /app

# Copy go.mod and go.sum for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY main.go .

RUN go build -o logging_example main.go

CMD ["./logging_example"] 