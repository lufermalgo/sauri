#!/usr/bin/env bash
# Creates an isolated git worktree + branch for a spec/issue, so concurrent
# APX/Codex sessions never share a working directory (see AGENTS.md: Code changes and Git protection).
#
# Usage: _tools/new-worktree.sh <branch-name>
#   e.g.: _tools/new-worktree.sh feature/issue-12-silero-vad
#         _tools/new-worktree.sh bugfix/issue-34-paste-timing
#
# Creates the worktree inside the registered project root, so APX can inspect
# the worktree while its tools remain confined to this project:
#   .worktrees/<branch-name-with-slashes-replaced-by-dashes>
# branched fresh from origin/main, and prints the path to cd into.

set -euo pipefail

branch="${1:?Usage: _tools/new-worktree.sh <branch-name> (e.g. feature/issue-12-desc)}"

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

# .apc and .agents/skills are local project configuration (not present in every
# remote branch). Seed each isolated checkout so APX/Codex sees the same agent
# instructions and linked Spectra skills; preserve any branch-provided version.
if [ -d "$repo_root/.apc" ] && [ ! -e "$dest/.apc" ]; then
  mkdir -p "$dest/.apc"
  cp -a "$repo_root/.apc/." "$dest/.apc/"
fi
if [ -d "$repo_root/.agents/skills" ] && [ ! -e "$dest/.agents/skills" ]; then
  mkdir -p "$dest/.agents/skills"
  cp -a "$repo_root/.agents/skills/." "$dest/.agents/skills/"
fi
if [ -f "$repo_root/.agents/skills-manager.json" ] && [ ! -e "$dest/.agents/skills-manager.json" ]; then
  mkdir -p "$dest/.agents"
  cp -p "$repo_root/.agents/skills-manager.json" "$dest/.agents/skills-manager.json"
fi

echo ""
echo "Worktree ready:"
echo "  cd $dest"
