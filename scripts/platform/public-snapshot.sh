#!/usr/bin/env bash
# Builds the first commit of the single public repository from one ref of this repository: the files of that ref, a
# fresh history of one commit, nothing else (no branches, no pull request refs, no issues). It never pushes; the owner
# (or a session with the owner's OK) pushes the result. Plan: docs/operations/single-public-repo.md.
#
# Usage: scripts/platform/public-snapshot.sh <ref> <empty-or-missing-dir>
# SAURI_PUBLIC_DENYLIST=<file> adds private words (one extended regex per line, # comments) that must not appear in
# any file; the list itself lives outside the repository so it does not publish what it hides.
set -euo pipefail

ref="${1:?usage: public-snapshot.sh <ref> <dir>}"
out="${2:?usage: public-snapshot.sh <ref> <dir>}"
repo="$(git rev-parse --show-toplevel)"

if [ -e "$out" ] && [ -n "$(ls -A "$out")" ]; then
  echo "error: $out is not empty" >&2
  exit 2
fi
mkdir -p "$out"
commit="$(git -C "$repo" rev-parse --verify "$ref^{commit}")"
git -C "$repo" archive "$commit" | tar -x -C "$out"

# Credentials that must never be public. Test fixtures use synthetic values that do not match these shapes.
secret='gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}'
secret+='|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
failed=0
if grep -rIlE "$secret" "$out"; then
  echo "error: credential-shaped text above" >&2
  failed=1
fi
if [ -n "${SAURI_PUBLIC_DENYLIST:-}" ]; then
  while IFS= read -r word; do
    case "$word" in ''|'#'*) continue ;; esac
    if grep -rIliE -- "$word" "$out"; then
      echo "error: a private word from the denylist is in the files above" >&2
      failed=1
    fi
  done < "$SAURI_PUBLIC_DENYLIST"
fi
if find "$out" -type f \( -iname '*.wav' -o -iname '*.webm' -o -iname '*.mp4' -o -iname '*.m4a' \) -size +1M | grep .; then
  echo "error: large media above (real recordings never go public)" >&2
  failed=1
fi
[ "$failed" -eq 0 ] || exit 1

git -C "$out" init -q -b main
git -C "$out" add -A
git -C "$out" commit -q -m "Sauri: first public version

Snapshot of ${commit:0:12}; the earlier history stays in the private archive."
echo "ready: $out ($(git -C "$out" ls-files | wc -l | tr -d ' ') files, one commit). Not pushed."
