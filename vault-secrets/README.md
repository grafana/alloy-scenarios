# Vault secrets with Grafana Alloy

Demonstrates Alloy's [`remote.vault`](https://grafana.com/docs/alloy/latest/reference/components/remote/remote.vault/) component pulling `prometheus.remote_write` basic_auth credentials from HashiCorp Vault at runtime, and shows that rotating the Vault secret is picked up without restarting Alloy.

## Overview

| Service       | Role                                                                |
| ------------- | ------------------------------------------------------------------- |
| `vault`       | HashiCorp Vault in dev mode. Stores credentials at `secret/alloy/remote-write`. |
| `vault-init`  | One-shot seeder that writes the initial secret then exits 0.        |
| `nginx-auth`  | Basic-auth reverse proxy in front of Prometheus's remote-write API. |
| `prometheus`  | Receives remote-writes from Alloy.                                  |
| `grafana`     | Pre-provisioned with Prometheus as the default datasource.          |
| `alloy`       | Scrapes its own `/metrics` and remote-writes via `nginx-auth`, with `basic_auth` credentials sourced from Vault. |

```
                                              ┌─────────────┐
                                  reread 30s  │             │
                ┌──── remote.vault ◀──────────│    Vault    │
                │   (auth.token)              │             │
                ▼                             └─────────────┘
            ┌────────┐                              ▲
            │ Alloy  │ scrape self → remote_write   │ vault kv put
            └────────┘    (basic_auth from Vault)   │ via rotate.sh
                │                                   │
                ▼                                   │
        ┌─────────────────┐   updated htpasswd     │
        │ nginx-auth      │◀────────────────────────┘
        │ (basic_auth)    │       via rotate.sh
        └─────────────────┘
                │
                ▼
          ┌────────────┐
          │ Prometheus │
          └────────────┘
                ▲
                │
          ┌────────────┐
          │  Grafana   │
          └────────────┘
```

## Running

```bash
docker compose up -d
# or, from the repo root:
./run-example.sh vault-secrets
```

| Service     | URL                                            |
| ----------- | ---------------------------------------------- |
| Grafana     | <http://localhost:3000>                        |
| Alloy UI    | <http://localhost:12345>                       |
| Prometheus  | <http://localhost:9090>                        |
| Vault       | <http://localhost:8200> (token: `root-token-for-demo`) |
| nginx-auth  | <http://localhost:8080> (basic-auth required)  |

## What to expect on a fresh boot

1. Watch nginx accept Alloy's writes:

   ```bash
   docker compose logs --tail=20 nginx-auth
   ```

   You should see `200` responses with `user=alloy`.

2. Confirm the seeded secret in Vault:

   ```bash
   docker exec -e VAULT_ADDR=http://127.0.0.1:8200 \
     -e VAULT_TOKEN=root-token-for-demo \
     vault-secrets-vault vault kv get secret/alloy/remote-write
   ```

3. Inspect the Alloy pipeline at <http://localhost:12345> — `prometheus.remote_write.via_nginx` should be healthy with no last-error.

4. Verify metrics flowed to Prometheus:

   ```bash
   curl -s 'http://localhost:9090/api/v1/query?query=up' | jq '.data.result'
   ```

## Demonstrating credential rotation

The interesting moment is the `401 → 200` transition: rotating nginx's htpasswd makes Alloy fail auth immediately, then Alloy recovers automatically once the Vault secret is updated and `remote.vault` re-reads (≤ 30 s).

```bash
# Step 1 — rotate htpasswd, reload nginx. Alloy starts 401-ing.
./rotate.sh htpasswd hunter2

# Watch nginx logs for 401s with user=-
docker compose logs -f nginx-auth

# Step 2 — update Vault to the new value. Alloy catches up within
# reread_frequency (30s) and goes back to 200 with user=alloy.
./rotate.sh vault hunter2

# Or do both in one go with a built-in 5s gap to make the 401 window
# observable:
./rotate.sh both rotated-password
```

You can also rotate Vault directly without the helper:

```bash
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 \
  -e VAULT_TOKEN=root-token-for-demo \
  vault-secrets-vault \
  vault kv put secret/alloy/remote-write username=alloy password=hunter2
```

## Inspecting Vault

```bash
# Read the current secret
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 \
  -e VAULT_TOKEN=root-token-for-demo \
  vault-secrets-vault vault kv get secret/alloy/remote-write

# Open the UI
open http://localhost:8200
# Token: root-token-for-demo
```

## Notes and caveats

- **Root token is hardcoded.** `root-token-for-demo` is fine for a demo, never for production. The real-world swap-in is `auth.approle` (with a wrapped role-id/secret-id) or `auth.kubernetes` — same component, different `auth.*` block.
- **`convert.nonsensitive` on `basic_auth.username`.** `remote.vault.creds.data.username` is a `Secret`; `basic_auth.username` expects a plain `string`, so it has to be unwrapped. `basic_auth.password` accepts `Secret` directly, so it doesn't need the conversion. Forgetting `convert.nonsensitive` on the username is the single most common mistake — the error is "expected string, got secret" at config load.
- **nginx is the source of truth for the credential.** If you update Vault but forget to update the htpasswd file, Alloy will 401 forever — that's the deliberate demo property, not a bug.
- **Vault dev-mode is in-memory.** A `docker compose down` followed by `up` resets the secret to `initial-password`.
- **Production caveat for the basic-auth path itself:** `Authorization: Basic …` is base64-encoded, not encrypted. In production this hop must be TLS — out of scope for this demo.

## Stopping

```bash
docker compose down --remove-orphans
```
