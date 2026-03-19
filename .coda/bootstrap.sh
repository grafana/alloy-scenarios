#!/usr/bin/env bash
# Boot-time bootstrap: read scenario from EC2 user_data via IMDSv2
set -euo pipefail

SCENARIO_DIR="/etc/coda"
SCENARIO_FILE="${SCENARIO_DIR}/scenario"

echo "==> Fetching scenario name from EC2 user_data (IMDSv2)"

# Get IMDSv2 token
TOKEN=$(curl -sf -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600") || {
  echo "Warning: could not obtain IMDS token (not running on EC2?)" >&2
  exit 0
}

# Fetch user_data
USER_DATA=$(curl -sf -H "X-aws-ec2-metadata-token: ${TOKEN}" \
  "http://169.254.169.254/latest/user-data") || {
  echo "Warning: could not fetch user_data" >&2
  exit 0
}

# Extract scenario name — expects plain text or key=value format
SCENARIO=""
if echo "$USER_DATA" | grep -q '='; then
  SCENARIO=$(echo "$USER_DATA" | grep '^scenario=' | cut -d= -f2- | tr -d '[:space:]')
else
  SCENARIO=$(echo "$USER_DATA" | tr -d '[:space:]')
fi

if [[ -z "$SCENARIO" ]]; then
  echo "Warning: no scenario found in user_data" >&2
  exit 0
fi

mkdir -p "$SCENARIO_DIR"
echo "$SCENARIO" > "$SCENARIO_FILE"
echo "==> Scenario set to: ${SCENARIO}"
