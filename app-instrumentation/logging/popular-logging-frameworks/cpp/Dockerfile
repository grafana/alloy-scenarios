FROM ubuntu:26.04@sha256:f144425ff09be612d6d9ad965196e9cdc23dae1f42110a8a11a3e9a8198759f7

# Install build dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    g++ \
    make \
    git \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Build the application
RUN cmake -B build -S . && \
    cmake --build build --config Release

# Run the application
CMD ["./build/logging_example"] 