#!/usr/bin/env bash
set -euo pipefail

SCENARIO_FILE="/etc/coda/scenario"
REPO_DIR="/opt/alloy-scenarios"

# Wait for the scenario file to be written by user_data
echo "Waiting for ${SCENARIO_FILE}..."
timeout=120
elapsed=0
while [[ ! -f "$SCENARIO_FILE" ]]; do
  sleep 2
  elapsed=$((elapsed + 2))
  if [[ $elapsed -ge $timeout ]]; then
    echo "Timed out waiting for ${SCENARIO_FILE} after ${timeout}s" >&2
    exit 1
  fi
done

SCENARIO="$(cat "$SCENARIO_FILE")"
echo "Scenario: ${SCENARIO}"

# Pull latest changes so new scenarios are always available
echo "Updating alloy-scenarios repo..."
git -C "$REPO_DIR" pull --ff-only || echo "Warning: git pull failed, using baked version"

# Start the scenario (builds images on demand)
exec "$REPO_DIR/coda" start "$SCENARIO"
