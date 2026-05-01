#!/usr/bin/env bash
# Demo helper for the vault-secrets scenario.
#
# Usage:
#   ./rotate.sh htpasswd <new-password>   # update nginx htpasswd + reload
#   ./rotate.sh vault    <new-password>   # update the Vault secret
#   ./rotate.sh both     <new-password>   # do both, with a 5s gap so the
#                                         # 401 window is visible

set -euo pipefail

cmd=${1:-}
pw=${2:-}

if [[ -z "$cmd" || -z "$pw" ]]; then
  echo "usage: rotate.sh htpasswd|vault|both <new-password>" >&2
  exit 2
fi

cd "$(dirname "$0")"

rotate_htpasswd() {
  echo ">> generating new bcrypt entry for alloy"
  docker run --rm httpd:2.4-alpine htpasswd -nbB -C 5 alloy "$pw" \
    > auth/htpasswd
  echo ">> reloading nginx"
  docker exec vault-secrets-nginx-auth nginx -s reload
}

rotate_vault() {
  echo ">> writing new credentials to Vault"
  docker exec \
    -e VAULT_ADDR=http://127.0.0.1:8200 \
    -e VAULT_TOKEN=root-token-for-demo \
    vault-secrets-vault \
    vault kv put secret/alloy/remote-write \
      username=alloy \
      password="$pw"
}

case "$cmd" in
  htpasswd) rotate_htpasswd ;;
  vault)    rotate_vault ;;
  both)
    rotate_htpasswd
    echo ">> nginx flipped; Alloy will 401 until Vault catches up. Sleeping 5s..."
    sleep 5
    rotate_vault
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
