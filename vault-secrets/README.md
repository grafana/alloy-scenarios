# Vault secrets

This scenario shows how Grafana Alloy pulls [`remote.vault`](https://grafana.com/docs/alloy/latest/reference/components/remote/remote.vault/) credentials into a `prometheus.remote_write` `basic_auth` block at runtime.
Alloy scrapes `/metrics` through `prometheus.exporter.self` and remote-writes through an nginx basic-auth proxy, re-reading Vault every 30 seconds without a restart.
Use Grafana, the Alloy UI, and the steps below to rotate credentials and watch them update in nginx-auth and Vault.

## Before you begin

Ensure you have the following:

- [Docker][docker] and [Docker Compose][docker-compose].
- Ports 3000 for Grafana, 8080 for nginx-auth, 8200 for Vault, 9090 for Prometheus, and 12345 for the Alloy UI free on the host.

[docker]: https://docs.docker.com/get-docker/
[docker-compose]: https://docs.docker.com/compose/install/

## Compare with a related scenario

| Aspect            | [`self-monitoring/`](../self-monitoring/)          | `vault-secrets/`                               |
| ----------------- | -------------------------------------------------- | ---------------------------------------------- |
| Metrics exporter  | `prometheus.exporter.self`                         | `prometheus.exporter.self`                     |
| Remote write auth | Static endpoint in `config.alloy`                  | `basic_auth` from `remote.vault.creds`         |
| Backends          | Prometheus and Loki                                | Prometheus only                                |
| Scenario focus    | `prometheus.exporter.self` metrics and Docker logs | Runtime credential reload from HashiCorp Vault |

Use `self-monitoring/` to collect metrics from `prometheus.exporter.self` and logs with static configuration.
Use this scenario when you need `remote.vault` to supply remote-write credentials and pick up rotated values without restarting Alloy.

## Understand the architecture

Alloy reads credentials from Vault on a timer, then uses them when remote-writing metrics scraped by `prometheus.scrape.self` through nginx-auth to Prometheus.
Grafana queries Prometheus through a provisioned data source.

```text
+-------------+   vault kv put via rotate.sh
|    Vault    |<------------------------------+
+-------------+                               |
      |                                       |
      | reread 30s                            | updated htpasswd via rotate.sh
      | remote.vault                          |
      | (auth.token)                          |
      v                                       v
+-------------+                    +-----------------+      +------------+      +----------+
|    Alloy    |------------------->| nginx-auth      |----->| Prometheus |<-----| Grafana  |
+-------------+                    | (basic_auth)    |      +------------+      +----------+
 scrape self -> remote_write       +-----------------+
 (basic_auth from Vault)
```

The table below uses the same labels as the diagram and maps each hop to the file that sets it.

| Diagram label                    | Path                     | Where                | Setting                                                                                         |
| -------------------------------- | ------------------------ | -------------------- | ----------------------------------------------------------------------------------------------- |
| `reread 30s`                     | Vault to Alloy           | `config.alloy`       | `remote.vault.creds` with `reread_frequency = "30s"`                                            |
| `remote.vault`                   | Vault to Alloy           | `config.alloy`       | `remote.vault "creds"` at `http://vault:8200`, path `secret`, key `alloy/remote-write`          |
| `(auth.token)`                   | Vault to Alloy           | `config.alloy`       | `auth.token { token = "root-token-for-demo" }`                                                  |
| `scrape self -> remote_write`    | Inside Alloy             | `config.alloy`       | `prometheus.exporter.self`, `prometheus.scrape.self`, and `prometheus.remote_write.via_nginx`   |
| `(basic_auth from Vault)`        | Inside Alloy             | `config.alloy`       | `basic_auth` on `prometheus.remote_write.via_nginx` from `remote.vault.creds.data`              |
| `remote_write`                   | Alloy to nginx-auth      | `config.alloy`       | `url = "http://nginx-auth/api/v1/write"`                                                        |
| `(basic_auth)`                   | Inside nginx-auth        | `nginx.conf`         | `auth_basic` and `auth_basic_user_file /etc/nginx/htpasswd` on `/api/v1/write`                  |
| remote-write receiver            | nginx-auth to Prometheus | `nginx.conf`         | `proxy_pass http://prom/api/v1/write`                                                           |
| remote-write receiver            | Inside Prometheus        | `docker-compose.yml` | `--web.enable-remote-write-receiver`                                                            |
| Grafana to Prometheus            | Grafana to Prometheus    | `docker-compose.yml` | Grafana entrypoint provisions Prometheus at `http://prometheus:9090` as the default data source |
| `vault kv put via rotate.sh`     | Host to Vault            | `rotate.sh`          | `rotate.sh vault` or `rotate.sh both` writes `secret/alloy/remote-write`                        |
| `updated htpasswd via rotate.sh` | Host to nginx-auth       | `rotate.sh`          | `rotate.sh htpasswd` or `rotate.sh both` rewrites `auth/htpasswd` and reloads nginx-auth        |

- **Vault**: Dev-mode server on port 8200. The entrypoint seeds `secret/alloy/remote-write` with `username=alloy` and `password=initial-password` before the health check passes.
- **Alloy**: Runs `config.alloy` with live debugging enabled. It waits for Vault to become healthy before it starts.
- **nginx-auth**: Terminates basic auth on `/api/v1/write` and proxies to Prometheus. Access logs include `user=$remote_user` when you rotate credentials.
- **Prometheus**: Accepts remote writes on port 9090.
- **Grafana**: Anonymous admin access on port 3000 with a pre-provisioned Prometheus data source.

## Run the scenario

1. Clone the repository if you haven't already: `git clone https://github.com/grafana/alloy-scenarios.git`

2. Install the scenario with one of these options:

   **Option 1: From the scenario directory**

   Use the default image tags in `docker-compose.yml`.

   - Navigate to this scenario: `cd alloy-scenarios/vault-secrets`
   - Deploy the scenario: `docker compose up -d`

   **Option 2: From the repository root**

   Use pinned image versions from `image-versions.env` for Grafana, Prometheus, and Alloy.

   - Deploy the scenario: `./run-example.sh vault-secrets`

3. Check that all containers are up: `cd alloy-scenarios/vault-secrets && docker compose ps`
   Wait until the `vault` container is healthy before you check Alloy remote-write status.
   Alloy depends on the Vault health check, which only passes after `secret/alloy/remote-write` is seeded.

## Explore the services

- **Grafana** at http://localhost:3000: **Explore** and dashboards, with no login required.
- **Alloy UI** at http://localhost:12345: Pipeline graph, component health, and live debug views.
- **Prometheus** at http://localhost:9090: Query metrics directly.
- **Vault** at http://localhost:8200: Sign in with token `root-token-for-demo`.
- **nginx-auth** at http://localhost:8080: Basic auth required on `/api/v1/write`.

## Understand the configuration

The `config.alloy` pipeline has four Alloy blocks: `remote.vault.creds`, `prometheus.exporter.self`, `prometheus.scrape.self`, and `prometheus.remote_write.via_nginx`.

1. **`remote.vault.creds`**: Connects to Vault at `http://vault:8200`, reads KV mount `secret` and key `alloy/remote-write`, and re-reads every 30 seconds with `reread_frequency = "30s"`.
   Alloy handles the KV v2 `/data/` prefix internally.
   Authentication uses `auth.token` with `root-token-for-demo`.
2. **`prometheus.exporter.self`**: Exposes the `/metrics` endpoint that `prometheus.scrape.self` scrapes.
3. **`prometheus.scrape.self`**: Scrapes `prometheus.exporter.self.self.targets` every 10 seconds and forwards samples to `prometheus.remote_write.via_nginx.receiver`.
4. **`prometheus.remote_write.via_nginx`**: Remote-writes to `http://nginx-auth/api/v1/write` with `basic_auth` credentials from `remote.vault.creds.data`.
   The username uses `convert.nonsensitive` because `basic_auth.username` expects a plain string.
   The password is passed as a `Secret` directly and doesn't need that conversion.

`livedebugging` is enabled so you can inspect the pipeline in the Alloy UI.

**nginx-auth** uses `nginx.conf` to require basic auth on `/api/v1/write` and proxy authenticated requests to Prometheus at `http://prom:9090/api/v1/write`.
The htpasswd file lives at `auth/htpasswd` and is bind-mounted into the container.

**Vault** starts in dev mode from `docker-compose.yml`.
The entrypoint seeds `secret/alloy/remote-write` before the health check passes so the first credential read in Alloy succeeds.

**Prometheus** runs with `--web.enable-remote-write-receiver` so nginx-auth can forward remote writes from Alloy.

**Grafana** provisions a default Prometheus data source at `http://prometheus:9090` through the entrypoint script in `docker-compose.yml`.

## Try it out

1. Watch nginx-auth accept remote writes from Alloy:

   ```sh
   docker compose logs --tail=20 nginx-auth
   ```

   You should see `200` responses with `user=alloy`.

2. Check the seeded secret in Vault:

   ```sh
   docker exec -e VAULT_ADDR=http://127.0.0.1:8200 \
     -e VAULT_TOKEN=root-token-for-demo \
     vault-secrets-vault vault kv get secret/alloy/remote-write
   ```

3. Open the Alloy UI at http://localhost:12345 and check that `prometheus.remote_write.via_nginx` is healthy with no last-error.

4. Verify metrics reached Prometheus:

   ```sh
   curl -s 'http://localhost:9090/api/v1/query?query=up' | jq '.data.result'
   ```

5. Rotate credentials.
   When you rotate the nginx-auth `htpasswd` file first, nginx-auth returns `401` because Vault still holds the old password.
   Update Vault to match and `remote.vault` re-reads within 30 seconds so authenticated writes resume.

   Rotate `htpasswd` first:

   ```sh
   ./rotate.sh htpasswd hunter2
   ```

   Watch nginx-auth logs for 401s with `user=-`:

   ```sh
   docker compose logs -f nginx-auth
   ```

   Update Vault to the new value:

   ```sh
   ./rotate.sh vault hunter2
   ```

   Alloy catches up within `reread_frequency` and nginx-auth logs return to `200` with `user=alloy`.

   Or run both steps with a built-in 5s gap so the 401 window is easier to observe:

   ```sh
   ./rotate.sh both rotated-password
   ```

   You can also update Vault directly without the helper:

   ```sh
   docker exec -e VAULT_ADDR=http://127.0.0.1:8200 \
     -e VAULT_TOKEN=root-token-for-demo \
     vault-secrets-vault \
     vault kv put secret/alloy/remote-write username=alloy password=hunter2
   ```

6. Inspect Vault directly.
   Read the current secret:

   ```sh
   docker exec -e VAULT_ADDR=http://127.0.0.1:8200 \
     -e VAULT_TOKEN=root-token-for-demo \
     vault-secrets-vault vault kv get secret/alloy/remote-write
   ```

   Open the Vault UI at http://localhost:8200 and sign in with token `root-token-for-demo`.
   On macOS you can run `open http://localhost:8200`.

7. Open Grafana at http://localhost:3000, go to **Explore**, select the **Prometheus** data source, and run `up`.
   You should see an `up` result for `prometheus.scrape.self`.

## Customize the scenario

- **Change credential reload interval**: Edit `reread_frequency` in `remote.vault.creds` in `config.alloy`, for example `"60s"`.
- **Use a different Vault auth method**: Replace `auth.token` with `auth.approle` or `auth.kubernetes` in `config.alloy` for production-style authentication.
- **Read a different secret path**: Update `path` and `key` in `remote.vault.creds` and match the seed command in the Vault entrypoint or your own secret store.
- **Remove the nginx-auth layer**: Point `prometheus.remote_write.via_nginx` directly at `http://prometheus:9090/api/v1/write` and drop the `basic_auth` block when you only need to test Vault credential loading.
- **Use pinned image versions**: Run `./run-example.sh vault-secrets` from the repository root to pick up tags from `image-versions.env`.

## Troubleshoot common problems

Diagnose startup ordering, auth mismatches, configuration load errors, and port conflicts.

### Alloy reports 401 from nginx-auth

Check nginx-auth access logs with `docker compose logs nginx-auth`.
If you see `401` with `user=-`, Alloy is sending credentials nginx-auth doesn't accept.

Update `auth/htpasswd` and reload nginx-auth, then update the matching Vault secret.
Use `./rotate.sh both <password>` to keep both in sync.
If you update Vault but not `htpasswd`, Alloy won't recover until both match because nginx-auth remains the source of truth for the password nginx-auth validates.

### Config load fails with expected string, got secret

`remote.vault.creds.data.username` returns a `Secret`.
Wrap it with `convert.nonsensitive` before you assign it to `basic_auth.username`, as shown in `config.alloy`.
`basic_auth.password` accepts `Secret` directly and doesn't need conversion.

### Alloy starts before Vault credentials exist

The Vault health check in `docker-compose.yml` waits until `vault kv get secret/alloy/remote-write` succeeds.
If you replace the Vault entrypoint, keep an equivalent readiness gate so Alloy doesn't read an empty secret on first boot.

### Vault data resets after restart

Vault dev mode stores secrets in memory.
A `docker compose down` followed by `up` resets `secret/alloy/remote-write` to `initial-password`.
Re-sync `htpasswd` if you've changed it during a prior run.

### Port conflicts with other services

Ports 3000, 8080, 8200, 9090, and 12345 need to be free before you start the stack.
Edit the port mapping in `docker-compose.yml` for the conflicting service if another process is already using one of these ports.

### Basic auth over plain HTTP

`Authorization: Basic` values are base64-encoded, not encrypted.
Use TLS on the nginx-auth hop in production.
This scenario intentionally uses plain HTTP to keep the focus on Vault credential loading.

## Stop the scenario

Run `docker compose down --remove-orphans` from the `vault-secrets` directory.

## Next steps

- [`remote.vault` reference](https://grafana.com/docs/alloy/latest/reference/components/remote/remote.vault/)
- [`prometheus.remote_write` reference](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/)
- [`self-monitoring/`](../self-monitoring/) for metrics from `prometheus.exporter.self` without Vault
- [`mssql-monitoring/`](../mssql-monitoring/) for a scenario that references Vault for production credential sourcing
- More examples: https://github.com/grafana/alloy-scenarios
