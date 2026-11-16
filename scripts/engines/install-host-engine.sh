#!/usr/bin/env bash
# Provision the isolated venv of the host administration service (:8005). --check changes nothing.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="${SAURI_HOST_ENGINE_VENV:-$HOME/.local/share/sauri/native-engines/host-venv}"
PYTHON="${SAURI_HOST_ENGINE_PYTHON:-$DEST/bin/python}"
CHECK=0
case "${1:-}" in --check) CHECK=1 ;; '') ;; *) echo "Usage: $0 [--check]" >&2; exit 2 ;; esac
[[ $# -le 1 ]] || exit 2
verify_runtime() {
  [[ -x "$PYTHON" ]] && PYTHONPATH="$ROOT/backend/engine-common" "$PYTHON" -c \
    'import fastapi, uvicorn, httpx, pydantic, sauri_engine_common.secrets, sauri_engine_common.route' 2>/dev/null
}
if [[ $CHECK -eq 1 ]]; then
  verify_runtime || { echo "Host service venv missing or incomplete; no changes made" >&2; exit 1; }
  echo "Host service runtime verified"
  exit 0
fi
if verify_runtime; then
  echo "Host service runtime already installed"
  exit 0
fi
command -v uv >/dev/null
uv venv --python 3.11 --allow-existing "$DEST"
uv pip install --python "$DEST/bin/python" -r "$ROOT/backend/host-engine/requirements-native.txt"
verify_runtime || { echo "Host service runtime verification failed" >&2; exit 1; }
echo "Installed host service runtime in $DEST (no secrets are created or read)"
