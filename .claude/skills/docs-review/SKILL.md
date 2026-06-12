---
name: docs-review
description: >-
  Create or review scenario README files in alloy-scenarios from existing
  Docker Compose, Helm, and config.alloy files. Use when drafting a new scenario
  README, rewriting an existing README, checking Writers Toolkit style, or
  verifying README accuracy against scenario configs and Grafana Alloy
  documentation.
---

# Scenario README create and review

Create or update a single scenario `README.md` in **alloy-scenarios**.
This repository documents scenarios only through per-directory README files.

Do not create other documentation pages.
Do not edit scenario configuration files.
Do not commit, push, or open pull requests unless the user explicitly asks.

## Before you begin

Read these shared files in order:

1. [`../shared/repo-context.md`](../shared/repo-context.md)
2. [`../shared/style-guide.md`](../shared/style-guide.md)
3. [`../shared/best-practices.md`](../shared/best-practices.md)

Then read every configuration file in the target scenario directory.
See **Config files to read** in [`../shared/best-practices.md`](../shared/best-practices.md).

Ask the user for the scenario directory path if it is not clear from context.

## Step 1: Choose create or review

| Condition                                        | Path       |
| ------------------------------------------------ | ---------- |
| `README.md` is missing, empty, or a stub         | **Create** |
| `README.md` already exists with scenario content | **Review** |

Create and review use the same style, structure, and verification rules.

## Step 2: Create a new README

1. Read the closest baseline README listed in [`../shared/repo-context.md`](../shared/repo-context.md).
2. Draft `README.md` using the template in [`../shared/style-guide.md`](../shared/style-guide.md).
3. Derive every command, port, URL, component name, and query from the scenario config files.
4. Omit optional template sections that do not apply.
5. Follow [`../shared/technical-verification.md`](../shared/technical-verification.md).
6. Verify Alloy component claims with [`../shared/alloy-verification.md`](../shared/alloy-verification.md).
7. Run through [`../shared/verification-checklist.md`](../shared/verification-checklist.md).
8. Present the draft README to the user. Do not commit.

## Step 3: Review an existing README

1. Read the current `README.md` alongside the scenario config files.
2. Load the previous version for preservation checks:

   ```sh
   git show HEAD:<scenario-dir>/README.md
   ```

   If the file is new on this branch, compare against the merge base or ask the user which version to preserve against.

3. Classify the change:

   - **Style/editorial** — wording and structure only, no new technical claims
   - **Technical** — commands, ports, component names, queries, credentials, or pipeline behavior

   When in doubt, treat it as **technical**.

4. Follow [`../shared/technical-verification.md`](../shared/technical-verification.md).
5. Verify Alloy component claims with [`../shared/alloy-verification.md`](../shared/alloy-verification.md).
6. Apply [`../shared/style-guide.md`](../shared/style-guide.md) and [`../shared/best-practices.md`](../shared/best-practices.md).
7. Confirm every command, query, credential, env var, and demo manifest from the original README is still present unless the configs changed.
8. Run through [`../shared/verification-checklist.md`](../shared/verification-checklist.md).
9. Apply fixes to `README.md` only. Present results to the user. Do not commit.

## Style and format requirements

Apply every rule in [`../shared/style-guide.md`](../shared/style-guide.md). In particular:

- Active voice, second person, present tense, contractions
- Sentence case for headings and emphasis used as subheadings
- No gerunds in headings
- No parentheses or brackets in prose
- "Refer to" not "see"
- "Check" not "confirm" in troubleshoot steps
- Every fenced code block must have a language tag

Remove AI-tell phrasing listed in [`../shared/best-practices.md`](../shared/best-practices.md).

## Technical verification

Scenario config files outrank the README when they disagree.
Fix the README to match the configs.
If a config looks wrong, flag it for the contributor instead of changing it.

For Alloy component names, arguments, and behavior, verify against the latest reference:

https://grafana.com/docs/alloy/latest/reference/components/

Follow [`../shared/technical-verification.md`](../shared/technical-verification.md) for the full workflow.

## Handoff

Present a summary that includes:

1. **Task** — create or review
2. **Scenario directory**
3. **Changes made** — or the full draft for create
4. **Style issues** found and fixed
5. **Technical verification** — claims checked against configs and Alloy docs, with any divergences
6. **Preservation** — on review, any content from the original README that was kept, restored, or intentionally dropped
7. **Open questions** — config problems or claims you could not verify
8. **Checklist** — note any items from [`../shared/verification-checklist.md`](../shared/verification-checklist.md) the user should confirm before submitting

## Reference

| File | Purpose |
| ---- | ------- |
| [`../shared/repo-context.md`](../shared/repo-context.md) | Repository layout and baseline READMEs |
| [`../shared/style-guide.md`](../shared/style-guide.md) | Style rules and README template |
| [`../shared/best-practices.md`](../shared/best-practices.md) | Config-first workflow and pitfalls |
| [`../shared/technical-verification.md`](../shared/technical-verification.md) | Technical review steps |
| [`../shared/alloy-verification.md`](../shared/alloy-verification.md) | Alloy docs cross-check |
| [`../shared/verification-checklist.md`](../shared/verification-checklist.md) | Pre-submit checklist |
