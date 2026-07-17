# Shared resources for README skills

Foundation files for creating and reviewing scenario `README.md` files in **alloy-scenarios**.

This repository documents scenarios through one README per directory. These files do not support Hugo pages, release notes, or product reference documentation.

## Files

| File                                                     | Purpose                                                           |
| -------------------------------------------------------- | ----------------------------------------------------------------- |
| [`repo-context.md`](repo-context.md)                     | Repository layout, contributor workflow, baseline README examples |
| [`style-guide.md`](style-guide.md)                       | Writers Toolkit rules and README template                         |
| [`best-practices.md`](best-practices.md)                 | Config-first workflow, pitfalls, and good patterns                |
| [`alloy-verification.md`](alloy-verification.md)         | How to verify Alloy claims against external docs                  |
| [`technical-verification.md`](technical-verification.md) | End-to-end technical review workflow for README claims            |
| [`verification-checklist.md`](verification-checklist.md) | Handoff checklist before submitting README changes                |

## Workflow

### Create a new README

1. Read [`repo-context.md`](repo-context.md)
2. Read the scenario config files
3. Draft with the README template in [`style-guide.md`](style-guide.md)
4. Follow [`best-practices.md`](best-practices.md)
5. Check the draft against [`generated-content-review.md`](generated-content-review.md)
6. Run [`verification-checklist.md`](verification-checklist.md)

### Review an existing README

1. Read [`repo-context.md`](repo-context.md)
2. Read the scenario config files and the current README
3. Compare against the previous README to preserve commands, queries, and credentials
4. Apply [`style-guide.md`](style-guide.md) and [`best-practices.md`](best-practices.md)
5. Follow [`technical-verification.md`](technical-verification.md) and [`alloy-verification.md`](alloy-verification.md)
6. Check the draft against [`generated-content-review.md`](generated-content-review.md)
7. Run [`verification-checklist.md`](verification-checklist.md)

## Skills that use these files

- [`../docs-review/SKILL.md`](../docs-review/SKILL.md) — create or review scenario README files

See [`../README.md`](../README.md) for the skills library overview.

## Maintenance

Update these files when:

- Baseline scenario README structure changes
- New verification patterns are discovered
- Repository layout or run workflow changes
