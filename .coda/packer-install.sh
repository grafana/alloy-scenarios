#!/usr/bin/env bash
# Packer provisioner: install alloy-scenarios and coda CLI on an EC2 AMI
set -euo pipefail

REPO_URL="https://github.com/grafana/alloy-scenarios.git"
INSTALL_DIR="/opt/alloy-scenarios"

echo "==> Cloning alloy-scenarios to ${INSTALL_DIR}"
git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"

echo "==> Adding host aliases for alloy"
grep -qxF '127.0.0.1 alloy' /etc/hosts || echo '127.0.0.1 alloy' >> /etc/hosts

echo "==> Symlinking coda CLI"
chmod +x "${INSTALL_DIR}/coda"
ln -sf "${INSTALL_DIR}/coda" /usr/local/bin/coda

echo "==> Pre-pulling base images"
docker pull "python:3.11-slim"
docker pull "apache/kafka:3.9.0"

echo "==> Pre-building Dockerfile-based app images"
scenarios_with_build=(
  otel-basic-tracing
  otel-tail-sampling
  otel-tracing-service-graphs
  otel-examples/cost-control
  otel-examples/count-connector
  otel-examples/resource-enrichment
  otel-examples/kafka-buffer
  otel-examples/pii-redaction
  otel-examples/ottl-transform
  otel-examples/multi-pipeline-fanout
)
for scenario in "${scenarios_with_build[@]}"; do
  compose_file="${INSTALL_DIR}/${scenario}/docker-compose.coda.yml"
  if [[ -f "$compose_file" ]]; then
    echo "  Building: ${scenario}"
    docker compose -f "$compose_file" --env-file "${INSTALL_DIR}/image-versions.env" build || true
  fi
done

echo "==> Installing systemd bootstrap service"
cp "${INSTALL_DIR}/.coda/coda-bootstrap.service" /etc/systemd/system/coda-bootstrap.service
cp "${INSTALL_DIR}/.coda/bootstrap.sh" /opt/alloy-scenarios/.coda/bootstrap.sh
chmod +x /opt/alloy-scenarios/.coda/bootstrap.sh
systemctl daemon-reload
systemctl enable coda-bootstrap.service

echo "==> Done"
