#!/usr/bin/env bash
# Removes a worktree created by scripts/dev/new-worktree.sh once its PR has merged
# (clean up branches and worktrees after merge).
#
# Usage: scripts/dev/remove-worktree.sh <branch-name>
#   e.g.: scripts/dev/remove-worktree.sh feature/issue-12-silero-vad

set -euo pipefail

branch="${1:?Usage: scripts/dev/remove-worktree.sh <branch-name>}"

git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
repo_root="$(cd "$(dirname "$git_common_dir")" && pwd)"
worktrees_dir="${repo_root}/.worktrees"
dest="${worktrees_dir}/$(echo "$branch" | tr '/' '-')"

if [ ! -e "$dest" ]; then
  echo "ERROR: $dest does not exist." >&2
  exit 1
fi

git -C "$repo_root" worktree remove "$dest"
git -C "$repo_root" branch -d "$branch" 2>/dev/null || \
  echo "Note: local branch '$branch' not deleted (unmerged or already gone) — check with 'git branch -vv'."
