---
name: sauri-git-recovery
description: Procedure for publishing to GitHub (issue, branch, PR) and recovering from git/gh failures such as EPERM on FETCH_HEAD, denied approvals and truncated callbacks.
---

# GitHub operations and failure recovery

- Before changing or publishing anything, report/check `pwd`, `git rev-parse --show-toplevel`, branch, `git status --short`, and the complete tracked/untracked inventory. Preserve all pre-existing user changes; never clean, reset, or stage them unless explicitly assigned.
- When the owner requests a PR, treat the request as end-to-end: verify or create the issue, use its dedicated worktree/branch, make and validate the scoped change, stage named files only, commit, fetch/rebase, push, and create the PR. An issue or local commit is not a completed PR. Do not stop with “I can continue” when no verified asynchronous job is running.
- Classify errors from their actual output. `EPERM` / `Operation not permitted` on `.git/worktrees/<name>/FETCH_HEAD` is a local filesystem-permission failure, not proof of network failure or remote branch state. Do not repeat the identical command, change permissions, remove Git metadata, recreate the worktree, edit `main`, or use another path to bypass the permission boundary. Preserve the checkout and report the exact failing command/error.
- If shell Git access fails, Ansel may use an already configured and authorized GitHub integration for the specific read or write operations it supports. A remote read can verify GitHub state but does not prove the local branch fetched/rebased. If an integration action is approval-denied or lacks write capability, do not retry or bypass it; report the denied action, what remains unpublished, and the exact permission/environment prerequisite.
- Do not claim a PR exists until verifying it on GitHub. Confirm its URL/number, base (`main`), head branch and SHA, issue reference, changed-file inventory, draft state, and mergeability. Distinguish “issue created,” “commit made,” “branch pushed,” and “PR opened.” Never claim sync/merge from a planned or failed command.
- If APX returns a truncated callback, recover the complete current-run result from its source session/tool output once when available. If it cannot be recovered, report only confirmed facts and mark the PR/result unconfirmed; do not invent the missing error or imply that a result is still running without a session/job ID.
- After the owner reports a merge, verify the PR is merged and linked issue closed. Update only a clean local `main` via fast-forward, verify it matches `origin/main`, then remove only that issue's worktree/branch using `_tools/remove-worktree.sh` and delete its remote branch per §7. Never clean another worktree.
