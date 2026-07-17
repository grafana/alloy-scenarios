# README authoring best practices

Best practices for creating and reviewing scenario README files in **alloy-scenarios**.

## Config-first workflow

Read the scenario configuration before writing or editing prose.

**Docker scenarios**

- `config.alloy`
- `docker-compose.yml` and `docker-compose.coda.yml` if present
- Backend configs in the scenario directory
- `app/` demo code when it affects **Try it out**

**Kubernetes scenarios**

- Helm values files in the scenario directory
- `kind.yml` when present

Don't invent components, ports, commands, or URLs that aren't supported by these files.
Don't edit these files.
Flag a config for the contributor instead of documenting it as-is if any of the following are true: two config files disagree with each other (for example a port in `docker-compose.yml` that doesn't match what `config.alloy` forwards to), a referenced file or service doesn't exist in the scenario directory, or a value contradicts the Alloy component reference per [`alloy-verification.md`](alloy-verification.md).

## Create or review with the same rules

| Task       | Starting point                             | Extra step                                                                |
| ---------- | ------------------------------------------ | ------------------------------------------------------------------------- |
| **Create** | Config files exist, README missing or stub | Draft from configs using the README template                              |
| **Review** | README already exists                      | Preserve every command, query, credential, and manifest from the original |

Style, structure, and verification rules are identical for both tasks.

## Pre-writing checklist

- [ ] Read [`repo-context.md`](repo-context.md) for repository layout
- [ ] Read the scenario config files in the target directory
- [ ] Read the closest baseline README named in `repo-context.md`
- [ ] Read [`style-guide.md`](style-guide.md)
- [ ] For rewrites, read the current README and note content that must be preserved

## Verification sources

1. Scenario config files in the directory
2. [`technical-verification.md`](technical-verification.md) for the review workflow
3. [`alloy-verification.md`](alloy-verification.md) for Alloy component claims
4. [`verification-checklist.md`](verification-checklist.md) before handoff

## Common pitfalls

### Invented pipeline details

**Problem**: Documenting components or labels that are not in `config.alloy`

**Solution**: Walk the README pipeline section in the same order as the config file and use exact block names

### Commands that don't match the repo

**Problem**: Guessing install or run commands

**Solution**: Copy commands from compose files, `run-example.sh` usage, or existing baseline READMEs for the same deployment pattern

### Lost content on rewrite

**Problem**: Improving style but dropping demo commands, queries, or credentials

**Solution**: Compare against the previous README and restore anything missing

### AI-tell phrasing

Refer to [`generated-content-review.md`](generated-content-review.md) for AI-tell patterns and how to report them.

### Weak examples

**Problem**: Queries or dashboards that don't match labels the scenario sets

**Solution**: Take query examples from labels and jobs defined in `config.alloy` or from the prior README

## Good patterns

**Introduction before the first heading**

State what the scenario collects, what the user runs, and which config file defines Alloy.

**Understand the configuration**

Name each Alloy block with the exact identifier from `config.alloy` and state what it forwards to next.

**Try it out**

Use numbered steps, put LogQL, PromQL, or TraceQL in sub-bullets, and end with Alloy UI live debug when the scenario supports it.

**Troubleshoot common problems**

Open with one sentence that states the scope, then use `###` subsections with imperative fix steps.

## Before handoff

Run [`verification-checklist.md`](verification-checklist.md).
