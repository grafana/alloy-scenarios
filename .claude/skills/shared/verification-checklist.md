# README verification checklist

Use this checklist when creating or reviewing a scenario `README.md`.

## Pre-writing

- [ ] Read [`repo-context.md`](repo-context.md)
- [ ] Read all config files in the scenario directory
- [ ] Read the closest baseline README for structure and tone
- [ ] For rewrites, captured commands, queries, and credentials that must be preserved

## Scenario config verification

- [ ] Run and install commands match `docker-compose.yml`, Helm values, or the existing README
- [ ] Ports and localhost URLs match compose port mappings or documented port-forwards
- [ ] Service names and in-stack URLs match compose or backend configs
- [ ] `config.alloy` block names in the README match the file exactly
- [ ] Pipeline order in the README matches the config file
- [ ] Backend endpoints match `loki.write`, `prometheus.remote_write`, or equivalent blocks
- [ ] Image version notes match `image-versions.env` when the README mentions pinned versions

## Alloy documentation verification

Follow [`alloy-verification.md`](alloy-verification.md).

- [ ] Each named Alloy component exists in the latest component reference
- [ ] Arguments and behavior described in the README match the reference and the scenario config
- [ ] High-risk claims such as block names, ports, and copy-paste commands are verified

## README structure

- [ ] Follows the README template in [`style-guide.md`](style-guide.md)
- [ ] Optional sections omitted when they do not apply
- [ ] Introduction appears before the first `##` heading

## Style guide compliance

- [ ] Active voice, second person, present tense
- [ ] Sentence case for headings and emphasis used as subheadings
- [ ] Contractions used naturally
- [ ] "Refer to" used instead of "see"
- [ ] "Check" used instead of "confirm" in troubleshoot steps
- [ ] No gerunds in headings
- [ ] No parentheses or brackets in prose
- [ ] Brief overview after major headings where helpful
- [ ] Prose explanations, not bullet lists standing in for paragraphs
- [ ] Every fenced code block has a language tag

## Example and query quality

- [ ] Examples reflect what this scenario actually collects
- [ ] LogQL, PromQL, TraceQL, or dashboard steps use labels and jobs from the config
- [ ] Demo commands and manifests from the original README are preserved on rewrite

## Preservation check (rewrite only)

- [ ] All shell commands from the original README are still present
- [ ] Credentials and default URLs preserved
- [ ] Query examples preserved or intentionally replaced with equivalent coverage
- [ ] Install order and Helm release names unchanged unless configs changed

## Generated-content review

Follow [`generated-content-review.md`](generated-content-review.md).

- [ ] Checked for structural padding, sentence-level tics, formatting tics, and content-level tells
- [ ] Leftover chat artifacts and invented or stale cross-references specifically checked
- [ ] Findings split into style-guide violations and likely AI-origin content issues, not lumped together

## Final review

- [ ] Read the README as a first-time user would
- [ ] Every technical claim traces to a scenario config file or Alloy reference page
- [ ] **Stop the scenario** and **Next steps** sections are present
- [ ] Relative links to sibling scenarios resolve
