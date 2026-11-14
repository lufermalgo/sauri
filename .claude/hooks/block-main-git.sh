#!/usr/bin/env bash
# PreToolUse guard for the Bash tool: blocks `git commit` / `git push` while the
# current branch is `main`, before the command even runs. This is a friendlier,
# earlier version of the same policy enforced by .githooks/pre-commit and
# .githooks/pre-push (the authoritative backstop — see AGENTS.md: Code changes and Git protection).
#
# GitHub-side branch protection isn't available on this repo (private + Free
# plan), so this pair of local mechanisms is the enforcement of record.

cmd="$(jq -r '.tool_input.command // empty')"

if ! echo "$cmd" | grep -qE '(^|[;&|]|\s)git\s+(commit|push)(\s|$)'; then
  exit 0
fi

# `git push --delete`/`-d` removes a remote ref (e.g. cleaning up a merged
# branch) — it can't land commits on main, so it's exempt from this check.
# The git-native pre-push hook (.githooks/pre-push) still inspects the
# actual ref being pushed for every other case.
if echo "$cmd" | grep -qE '(^|[;&|]|\s)git\s+push\b.*(--delete|\s-d\s)'; then
  exit 0
fi

# Respect a leading `cd <dir> &&`/`;` so a worktree command (e.g.
# `cd .worktrees/feature-x && git commit ...`) is checked against
# that directory's branch, not this hook process's own cwd.
dir="."
leading_cd="$(echo "$cmd" | grep -oE '^[[:space:]]*cd[[:space:]]+[^;&]+' | head -1)"
if [ -n "$leading_cd" ]; then
  dir="$(echo "$leading_cd" | sed -E 's/^[[:space:]]*cd[[:space:]]+//' | sed -E "s/^['\"]|['\"]\$//g" | sed -E 's/[[:space:]]+$//')"
fi

branch="$(git -C "$dir" symbolic-ref --short HEAD 2>/dev/null)"

if [ "$branch" = "main" ]; then
  reason="Direct git commit/push on 'main' is blocked by project policy (AGENTS.md: Code changes and Git protection). Create or enter a worktree first: _tools/new-worktree.sh <branch-name>, then cd into the printed path and retry there."
  jq -n --arg reason "$reason" \
    '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $reason}}'
  exit 0
fi

exit 0
