---
name: merge-chore-prs
description: >-
  Approve and merge open Renovate chore(deps) dependency-update pull requests
  on grafana/alloy-scenarios using the GitHub CLI. Use when asked to clear
  out, approve, or merge Renovate PRs, dependency bump PRs, or "chore" PRs.
  Does not touch feature or fix PRs.
---

# Approve and merge chore(deps) PRs

Approve and merge open Renovate dependency-update pull requests on
**grafana/alloy-scenarios**. This skill only ever touches automated
`chore(deps): ...` PRs opened by the Renovate bot. It never modifies,
merges, or comments on any other pull request.

## Hard rules

- Only act on PRs authored by `app/renovate-sh-app` whose title starts with
  `chore(deps):`. If a PR looks like a chore PR but isn't from that author,
  skip it and flag it to the user instead of guessing.
- Never run a manual `git merge`/`git push` into `main`. Always merge through
  `gh pr merge`, which goes through the GitHub API and respects branch
  protection (required checks, required reviews). A local merge pushed
  directly to `main` bypasses that protection.
- Never push commits to a PR branch to "fix" it (no `git push` to
  `renovate/*` branches, no using the GitHub UI edit feature). This repo's
  branch protection requires an approving review from someone other than the
  last pusher — pushing to the branch yourself would make you the last
  pusher and block your own approval, and it also means you're editing a bot
  PR, which this skill must not do. If a PR needs a change, leave it for a
  human or for Renovate to update.
- Skip anything that is a draft, has failing/pending required checks, has
  merge conflicts (`mergeable != MERGEABLE`), or already has a review
  decision other than none/approved. Report skipped PRs; do not force them.
- Do not touch non-chore PRs (feature branches, fix branches, PRs authored
  by humans) even if they appear in the same list.

## Steps

1. List open PRs and inspect author, title, draft state, and mergeability:

   ```sh
   gh pr list --repo grafana/alloy-scenarios --state open \
     --json number,title,author,isDraft,mergeable,mergeStateStatus
   ```

2. Filter to PRs where `author.login == "app/renovate-sh-app"`,
   `isDraft == false`, and the title matches `^chore\(deps\):`.

3. For each candidate, confirm checks are green and a review is actually
   required/missing before approving:

   ```sh
   gh pr view <number> --repo grafana/alloy-scenarios \
     --json number,title,reviewDecision,statusCheckRollup,mergeable,mergeStateStatus
   ```

   Skip the PR if any required check is not `SUCCESS`/`COMPLETED`, or if
   `mergeable` is not `MERGEABLE`.

4. Approve, then merge with squash and branch cleanup:

   ```sh
   gh pr review <number> --repo grafana/alloy-scenarios --approve \
     -b "Approving automated dependency update."
   gh pr merge <number> --repo grafana/alloy-scenarios --squash --delete-branch
   ```

5. After processing every candidate, verify the merges landed:

   ```sh
   gh pr list --repo grafana/alloy-scenarios --state merged --limit 20 \
     --json number,title,mergedAt
   ```

## Handoff

Report back:

1. **Merged** — PR numbers and titles that were approved and merged
2. **Skipped** — any chore PR left untouched, with the reason (failing
   check, conflict, draft, unexpected author, etc.)
3. **Not touched** — any non-chore PRs seen in the listing, left alone
