#!/usr/bin/env bash
# Install once; verify the pinned source and every model file on every invocation.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${SAURI_DIAR_VENV:-${HOME}/.local/share/sauri/native-engines/diar-venv}"
PYTHON="${SAURI_DIAR_ENGINE_PYTHON:-${VENV}/bin/python}"
HASHES="${SAURI_ENGINE_HASHES_FILE:-${ROOT_DIR}/scripts/engines/engine-hashes.json}"
COMMIT="1bcb09041bfa170b4a5a4b0af92f66eff76204d5"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --check ) ]] || { echo "Usage: $0 [--check]" >&2; exit 2; }
CHECK_ONLY="${1:-}"

verify() {
  [[ -x "$PYTHON" ]] || return 2
  "$PYTHON" - "$HASHES" "$COMMIT" <<'PY'
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

try:
    dist = importlib.metadata.distribution("senko")
except importlib.metadata.PackageNotFoundError:
    sys.exit(2)
try:
    origin = json.loads(dist.read_text("direct_url.json") or "{}")
    commit = origin.get("vcs_info", {}).get("commit_id")
    if origin.get("url", "").startswith("file:") or commit != sys.argv[2]:
        raise ValueError("Senko source commit mismatch")
    manifest = json.loads(Path(sys.argv[1]).read_text())["senko"]
    if manifest["commit"] != sys.argv[2] or not manifest["files"]:
        raise ValueError("Invalid Senko hash manifest")
    for relative, expected in manifest["files"].items():
        path = Path(dist.locate_file(relative))
        with path.open("rb") as model:
            actual = hashlib.file_digest(model, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Model SHA-256 mismatch: {relative}")
except (OSError, ValueError, KeyError) as exc:
    print(f"Senko verification failed: {exc}", file=sys.stderr)
    sys.exit(1)
print("Senko pinned source and model SHA-256 checks passed")
PY
}

if [[ "$CHECK_ONLY" == --check ]]; then
  verify
  exit $?
fi

# A corrupt existing installation must fail closed, not silently reinstall.
status=0
verify || status=$?
if [[ "$status" == 1 ]]; then exit 1; fi
if [[ "$status" == 2 ]]; then
  [[ "$(uname -s)" == Darwin ]] || { echo "Senko native installation requires macOS" >&2; exit 1; }
  if [[ ! -x "$PYTHON" ]]; then
    [[ "$PYTHON" == "$VENV/bin/python" ]] || { echo "Configured Python is missing" >&2; exit 1; }
    "${NATIVE_PYTHON311:-python3.11}" -m venv "$VENV"
  fi
fi
"$PYTHON" -m pip install -r "$ROOT_DIR/backend/diar-engine/requirements-native.txt"
verify
