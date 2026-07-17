## Style guide

Always strictly adhere to the documentation style guide.

### Scope

This repository documents scenarios through **one file per scenario**: `<scenario-dir>/README.md`.
Each README is a single-page workflow that explains how to install, run, explore, customize, and stop the demo.
Do not create other documentation pages in this repository.

Write for someone who wants to run the scenario end to end with minimal prior Alloy knowledge.

### Product naming (Grafana organization)

- Write for Grafana Labs users, not staff
- Do not document how to develop on the Alloy project
- Do not document deployment for Grafana Cloud products
- Use long product names with "Grafana" in the README title
- Use short product names without "Grafana" in the README body
- Always use "Grafana Cloud," not "Cloud."
- Mention metrics, logs, traces, profiles in this order

### Style

- Follow Every Page is Page One
- Keep READMEs short and focused
- Use present simple tense, second-person, and active voice
- Use simple words, short sentences, and few adjectives or adverbs
- Prefer contractions
- Use sentence case for titles, headings, and UI
- Bold UI text
- Reference UI text, not element types such as button or tab
- Do not use gerunds in headings
- Do not use parentheses or brackets in prose

### Structure

- Write a short introduction before the first `##` heading
- Add a brief overview sentence after each `##` and `###` heading where it helps
- Structure content under `##` headings
- Use `###` for troubleshoot subsections and related subsections
- Do not use lists as a substitute for paragraphs
- Use ", for example," for examples
- Use relative links for other scenarios in this repository
- Use "refer to" instead of "see."
- Separate code and output blocks
- Use `<VARIABLE>` in commands and _VARIABLE_ in prose for placeholders

### README conventions

- Always add a language tag to fenced code blocks. Do not use bare ` ``` ` fences.
- Common tags: `sh` for shell commands, `yaml` for Kubernetes and Helm manifests, `alloy` for `config.alloy` excerpts, `text` for ASCII diagrams and env var lines, `markdown` for README examples
- Use `config.alloy` block names exactly as they appear in the scenario file
- Capitalize **Pod** in prose; use lowercase in `kubectl` commands and YAML
- Docker scenarios may document two run options: `docker compose up -d` from the scenario directory, or `./run-example.sh <scenario-dir>` from the repository root

## README template

Always use this template for scenario `README.md` files.
Derive commands, component names, and URLs from the scenario config files.
Apply the style guide above.

```markdown
# <Scenario title>

Introduction explaining what the scenario demonstrates, which telemetry it collects, what you install or run, and how Alloy is configured.

## Before you begin

List prerequisites, tools, and ports that must be free.

## Compare with a related scenario

Optional. Include this section only when repo-context.md's baseline README table lists another scenario with the same deployment pattern (Docker vs. Kubernetes) and overlapping telemetry type (logs, metrics, traces).
Name that scenario directly.
If no such scenario is listed there, omit this section.
Don't search for or invent a comparison.

## Understand the architecture

Short overview, ASCII diagram, and labeled bullets for each component in the flow.

## Run the scenario

Numbered setup steps. Include clone, deploy or install commands, and a step to confirm the stack is ready.

## Access the services

Optional. Explain how to reach services that are not available on localhost.

## Explore the services

List each service URL, what you can do there, and login credentials when required.

## Understand the configuration

Walk through how Alloy and the backends are configured, in pipeline or dependency order.

## Try it out

Steps to generate telemetry, run queries or open dashboards, and inspect the pipeline in the Alloy UI.

## Customize the scenario

Include this section if any of the following appear in the scenario's configs: an environment variable, a `.env` setting, a commented out configuration line, a port mapping, a file path, a scrape or scrape_interval value, a retention setting, a backend endpoint URL, or a label or job name used for filtering.
For each one, name the setting and explain what changing it does, matching the style of existing scenario READMEs rather than citing file names or line numbers.
Omit this section only if none of the items above appear anywhere in `config.alloy`, the compose file, backend configs, or Helm values.

## Troubleshoot common problems

Overview sentence, then h3 subsections for each common failure and its fix.

## Stop the scenario

Command to tear down the demo environment.

## Next steps

Links to related Alloy documentation, sibling scenarios, and other examples in this repository.
```

Omit optional sections that do not apply to the scenario.
Skip **Access the services** when all services are already reachable on localhost.
