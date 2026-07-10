#!/usr/bin/env bash
# Removes a worktree created by _tools/new-worktree.sh once its PR has merged
# (see AGENTS.md §7, §12 — clean up branches/worktrees after merge).
#
# Usage: _tools/remove-worktree.sh <branch-name>
#   e.g.: _tools/remove-worktree.sh feature/issue-12-silero-vad

set -euo pipefail

branch="${1:?Usage: _tools/remove-worktree.sh <branch-name>}"

repo_root="$(git rev-parse --show-toplevel)"
repo_name="$(basename "$repo_root")"
worktrees_dir="$(dirname "$repo_root")/${repo_name}-worktrees"
dest="${worktrees_dir}/$(echo "$branch" | tr '/' '-')"

if [ ! -e "$dest" ]; then
  echo "ERROR: $dest does not exist." >&2
  exit 1
fi

git -C "$repo_root" worktree remove "$dest"
git -C "$repo_root" branch -d "$branch" 2>/dev/null || \
  echo "Note: local branch '$branch' not deleted (unmerged or already gone) — check with 'git branch -vv'."
