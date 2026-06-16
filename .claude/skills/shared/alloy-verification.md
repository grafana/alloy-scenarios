# Alloy technical verification

Use this guide when a README names Alloy components, arguments, endpoints, or pipeline behavior.

## Primary source

Verify against the latest Grafana Alloy component reference:

https://grafana.com/docs/alloy/latest/reference/components/

Search for the exact block type named in `config.alloy`, for example `loki.source.file`, `prometheus.scrape`, or `otelcol.receiver.otlp`.

## Secondary source

Verify deployment commands, ports, service names, and URLs against files in the scenario directory:

- `config.alloy`
- `docker-compose.yml` and `docker-compose.coda.yml`
- Backend configs such as `loki-config.yaml`, `prom-config.yaml`, `tempo-config.yaml`
- Helm values files in `k8s/` scenarios

The scenario configs outrank the README when they disagree.

## What to verify

| Claim type                                        | Check against                                              |
| ------------------------------------------------- | ---------------------------------------------------------- |
| Component block names                             | `config.alloy` and Alloy component reference               |
| `forward_to`, labels, scrape intervals, endpoints | `config.alloy`                                             |
| Ports and localhost URLs                          | `docker-compose.yml` port mappings                         |
| Backend URLs inside the stack                     | compose files or backend configs                           |
| Helm chart names, release names, values keys      | scenario Helm values files                                 |
| Image tags when documented                        | `image-versions.env` and compose `${VAR:-default}` entries |

## Risk levels

**High risk** — always verify:

- Exact `config.alloy` block names users will search for in the Alloy UI
- Commands users copy and paste
- Ports, URLs, and credentials
- Query examples tied to labels the scenario actually sets

**Medium risk** — verify when stated explicitly:

- What a component does in this scenario's pipeline
- Optional features enabled or disabled in config
- Number of parallel paths or sources

**Low risk** — spot-check:

- General descriptions of Grafana, Loki, Prometheus, or Tempo roles in the stack

## When Alloy docs and configs disagree

1. Don't change or edit the scenario config files
2. If the config looks wrong and doesn't match the Alloy documentation, flag it for the contributor to investigate instead of inventing behavior from memory

## Preservation on rewrite

When reviewing an existing README, verify that commands, queries, credentials, env vars, and demo manifests from the original file still appear in the updated version.
Use `git show HEAD:<scenario>/README.md` or the branch base for comparison.
