#!/usr/bin/env bash
# Creates an isolated git worktree + branch for a spec/issue, so concurrent
# Claude Code sessions never share a working directory (see AGENTS.md §7, §12).
#
# Usage: _tools/new-worktree.sh <branch-name>
#   e.g.: _tools/new-worktree.sh feature/issue-12-silero-vad
#         _tools/new-worktree.sh bugfix/issue-34-paste-timing
#
# Creates the worktree as a sibling directory of the repo:
#   ../sauri-worktrees/<branch-name-with-slashes-replaced-by-dashes>
# branched fresh from origin/main, and prints the path to cd into.

set -euo pipefail

branch="${1:?Usage: _tools/new-worktree.sh <branch-name> (e.g. feature/issue-12-desc)}"

if [ "$branch" = "main" ]; then
  echo "ERROR: refusing to create a worktree for 'main'." >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
repo_name="$(basename "$repo_root")"
worktrees_dir="$(dirname "$repo_root")/${repo_name}-worktrees"
dest="${worktrees_dir}/$(echo "$branch" | tr '/' '-')"

if [ -e "$dest" ]; then
  echo "ERROR: $dest already exists." >&2
  exit 1
fi

mkdir -p "$worktrees_dir"

git -C "$repo_root" fetch origin main

if git -C "$repo_root" show-ref --verify --quiet "refs/heads/$branch"; then
  echo "Branch '$branch' already exists locally — attaching worktree to it (not resetting to origin/main)."
  git -C "$repo_root" worktree add "$dest" "$branch"
else
  git -C "$repo_root" worktree add -b "$branch" "$dest" origin/main
fi

echo ""
echo "Worktree ready:"
echo "  cd $dest"
