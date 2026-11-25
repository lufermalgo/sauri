#!/usr/bin/env bash
# Creates an isolated git worktree + branch for a spec/issue, so concurrent
# agent sessions never share a working directory (see CONTRIBUTING.md).
#
# Usage: scripts/dev/new-worktree.sh <branch-name>
#   e.g.: scripts/dev/new-worktree.sh feature/issue-12-silero-vad
#         scripts/dev/new-worktree.sh bugfix/issue-34-paste-timing
#
# Creates the worktree inside the repository root, so tools can inspect it
# while remaining confined to this project:
#   .worktrees/<branch-name-with-slashes-replaced-by-dashes>
# branched fresh from origin/main, and prints the path to cd into.

set -euo pipefail

branch="${1:?Usage: scripts/dev/new-worktree.sh <branch-name> (e.g. feature/issue-12-desc)}"

if [ "$branch" = "main" ]; then
  echo "ERROR: refusing to create a worktree for 'main'." >&2
  exit 1
fi

git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"
repo_root="$(cd "$(dirname "$git_common_dir")" && pwd)"
worktrees_dir="${repo_root}/.worktrees"
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

# The maintainer's private working files (agent rules and settings, specs, internal notes) are ignored by git
# and live only in the main checkout. Link each one into the new worktree so agents find the same files there and
# edits land in the single copy.
private_paths=(.claude .agents .spectra AGENTS.md CLAUDE.md docs/product docs/history docs/operations docs/design
  docs/architecture/overview.md docs/architecture/project-structure.md)
for item in "${private_paths[@]}"; do
  if [ -e "$repo_root/$item" ] && [ ! -e "$dest/$item" ] && [ ! -L "$dest/$item" ]; then
    mkdir -p "$(dirname "$dest/$item")"
    ln -s "$repo_root/$item" "$dest/$item"
  fi
done

echo ""
echo "Worktree ready:"
echo "  cd $dest"
