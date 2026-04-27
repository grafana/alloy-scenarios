#!/bin/bash

# Usage check
if [ $# -lt 1 ]; then
    echo "Usage: $0 <example-directory>"
    echo "Available examples:"
    ls -d */ | grep -v "k8s\|img\|.git" | tr -d '/'
    exit 1
fi

EXAMPLE_DIR=$1

# Check if the example directory exists
if [ ! -d "$EXAMPLE_DIR" ]; then
    echo "Error: Example directory '$EXAMPLE_DIR' not found."
    exit 1
fi

# Check if a docker-compose file exists in the example directory.
# Some scenarios use .yaml instead of .yml; accept either.
if [ ! -f "$EXAMPLE_DIR/docker-compose.yml" ] && [ ! -f "$EXAMPLE_DIR/docker-compose.yaml" ]; then
    echo "Error: No docker-compose.yml or docker-compose.yaml found in '$EXAMPLE_DIR'."
    exit 1
fi

# Source the image versions
if [ ! -f "image-versions.env" ]; then
    echo "Error: image-versions.env file not found."
    exit 1
fi

# Run docker-compose in the example directory with the environment variables
echo "Starting example: $EXAMPLE_DIR"
(cd "$EXAMPLE_DIR" && docker compose --env-file ../image-versions.env up -d)

echo "Example started successfully."
echo "Access Grafana at http://localhost:3000"
echo "To stop the example, run: cd $EXAMPLE_DIR && docker compose down" 