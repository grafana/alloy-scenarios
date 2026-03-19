#!/usr/bin/env bash
# Packer provisioner: set up coda CLI and systemd services on an AMI.
#
# Expects the alloy-scenarios repo to already be cloned to /opt/alloy-scenarios.
# This script is called by the consuming Packer template after cloning.
#
# It intentionally does NOT pre-build scenario images. Scenarios are built
# on demand by `coda start`, so new scenarios work without re-baking the AMI.
set -euo pipefail

INSTALL_DIR="${1:-/opt/alloy-scenarios}"

echo "==> Adding host aliases for alloy"
grep -qxF '127.0.0.1 alloy' /etc/hosts || echo '127.0.0.1 alloy' >> /etc/hosts

echo "==> Symlinking coda CLI"
chmod +x "${INSTALL_DIR}/coda"
ln -sf "${INSTALL_DIR}/coda" /usr/local/bin/coda

echo "==> Pre-pulling common base images"
# Only pull widely-shared base images to speed up first boot.
# Scenario-specific images are built on demand by `coda start`.
docker pull "python:3.11-slim" || true
docker pull "apache/kafka:3.9.0" || true

echo "==> Installing systemd services"
cp "${INSTALL_DIR}/.coda/coda-start.service" /etc/systemd/system/coda-start.service
install -m 0755 "${INSTALL_DIR}/.coda/coda-start.sh" /usr/local/bin/coda-start.sh
systemctl daemon-reload

echo "==> Done"
