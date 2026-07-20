# Technical verification

When creating or reviewing a scenario README, treat every factual claim about commands, ports, components, queries, or pipeline behavior as verifiable.

## 1. Identify verifiable claims

Flag statements about:

- `config.alloy` block names, labels, endpoints, and `forward_to` wiring
- Docker Compose commands, ports, and service names
- Helm chart names, release names, and values file keys
- LogQL, PromQL, TraceQL, or dashboard examples
- Credentials, URLs, and install order

## 2. Verify against scenario files first

Read the scenario directory configs listed in [`repo-context.md`](repo-context.md).

Use the **Scenario config verification** and **Preservation check (rewrite only)** sections of [`verification-checklist.md`](verification-checklist.md).

## 3. Verify Alloy claims against external docs

Follow [`alloy-verification.md`](alloy-verification.md).

Use the latest component reference at https://grafana.com/docs/alloy/latest/reference/components/

## 4. Prioritize by risk

- **High risk** — copy-paste commands, ports, block names, credentials, query labels. Always verify.
- **Medium risk** — component behavior described in prose, optional pipeline paths. Verify against config and Alloy docs.
- **Low risk** — general role of Grafana or a backend in the stack. Spot-check.

If you cannot verify a claim, flag it for the contributor instead of assuming it is correct.

## 5. Report findings

For each divergence, note:

- The claim as written in the README
- What the scenario config or Alloy reference says
- Whether they match

Present technical findings separately from style issues.
