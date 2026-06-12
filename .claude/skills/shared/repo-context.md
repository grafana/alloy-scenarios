# alloy-scenarios repository context

Read this file before creating or reviewing a scenario README.

## What this repository documents

- **Only** `<scenario-dir>/README.md` files
- Each README is a self-contained install, run, and explore workflow
- The root `README.md` is a scenario index, not a substitute for per-scenario READMEs

## Scenario layout

Most scenarios are **Docker-based**:

```text
scenario-name/
├── docker-compose.yml       # LGMT stack + Alloy
├── docker-compose.coda.yml  # Optional demo app services
├── config.alloy             # Alloy pipeline
├── loki-config.yaml         # When Loki is used
├── prom-config.yaml         # When Prometheus is used
├── tempo-config.yaml        # When Tempo is used
├── README.md                # Scenario documentation
└── app/                     # Optional demo application
```

Kubernetes scenarios live under `k8s/` and use Helm values files instead of Docker Compose. Treat them as an exception, not the default pattern.

## Contributor workflow

1. Create or update the scenario configuration files first
2. Create or update `README.md` to match those files
3. Verify the README against scenario configs and the Alloy component reference

The README skill supports two paths with the same rules:

- **Review** — README already exists; improve style and fix inaccuracies without dropping content
- **Create** — README does not exist yet; draft from configs using the README template

## Running scenarios

From a scenario directory:

```sh
docker compose up -d
```

From the repository root with pinned image versions:

```sh
./run-example.sh <scenario-dir>
```

Image versions are centralized in `image-versions.env`. Compose files reference them with `${VAR:-default}` syntax.

## Baseline README examples

Use these as structure and tone references:

| Pattern                  | Example                                                       |
| ------------------------ | ------------------------------------------------------------- |
| Docker, full workflow    | `linux/README.md`                                             |
| Docker, shorter          | `kafka/README.md`                                             |
| Docker, processing focus | `log-api-gateway/README.md`, `log-secret-filtering/README.md` |
| Kubernetes Helm          | `k8s/logs/README.md`                                          |
| Kubernetes manifests     | `k8s/events/README.md`                                        |

## Other repo references

- `CLAUDE.md` — project conventions and scenario checklist
- `.cursor/docker-example.mdc` — Docker scenario boilerplate
- `.cursor/k8s-example.mdc` — Kubernetes scenario boilerplate
