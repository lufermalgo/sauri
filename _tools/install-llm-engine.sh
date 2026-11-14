#!/usr/bin/env bash
# Pinned, static Metal build; --check never downloads, builds or installs anything.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${SAURI_LLM_INSTALL_DIR:-$HOME/.local/share/sauri/native-engines/llm}"
CHECK=0
case "${1:-}" in --check) CHECK=1 ;; '') ;; *) echo "Usage: $0 [--check]" >&2; exit 2 ;; esac
[[ $# -le 1 ]] || exit 2
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo "Requires Apple silicon macOS" >&2; exit 1;
}
command -v uv >/dev/null
# Use the backend's Python environment, not an ambient system interpreter.
py() { (cd "$ROOT/backend" && uv run --no-sync --extra dev python "$@"); }
read_field() { py -c 'import json,sys; print(json.load(open(sys.argv[1]))["llm"][sys.argv[2]])' "$ROOT/_tools/engine-hashes.json" "$1"; }
COMMIT="$(read_field llama_cpp_commit)"
REPO="$(read_field model_repo)"
REVISION="$(read_field model_revision)"
MODEL="$(read_field model_file)"
HASH="$(read_field model_sha256)"
BINARY="$DEST/bin/llama-server"
MODEL_PATH="$DEST/models/$MODEL"
ENGINE_PYTHON="$DEST/venv/bin/python"
verify_runtime() {
  [[ -x "$ENGINE_PYTHON" ]] && "$ENGINE_PYTHON" -c 'import fastapi, uvicorn, httpx' 2>/dev/null
}
verify_model() { [[ -f "$MODEL_PATH" ]] && [[ "$(shasum -a 256 "$MODEL_PATH" | cut -d' ' -f1)" == "$HASH" ]]; }
verify_binary() {
  [[ -x "$BINARY" ]] || return 1
  local help
  help="$("$BINARY" --help 2>/dev/null)" || return 1
  grep -q -- '--reasoning-budget' <<<"$help" && grep -q -- '--no-context-shift' <<<"$help"
}
verify_provenance() {
  py - "$DEST/provenance.json" "$COMMIT" "$HASH" "$BINARY" <<'PY'
import hashlib, json, sys
try:
    p = json.load(open(sys.argv[1]))
    assert p['llama_cpp_commit'] == sys.argv[2]
    assert p['model_sha256'] == sys.argv[3]
    assert p['binary_sha256'] == hashlib.file_digest(open(sys.argv[4], 'rb'), 'sha256').hexdigest()
    assert p['reasoning_args'] == ['--reasoning-budget', '0']
    assert p['cmake_args'] == ['-DBUILD_SHARED_LIBS=OFF', '-DLLAMA_OPENSSL=OFF', '-DGGML_METAL=ON']
except (OSError, ValueError, KeyError, AssertionError):
    sys.exit(1)
PY
}
if [[ $CHECK -eq 1 ]]; then
  verify_binary && verify_model && verify_provenance && verify_runtime || {
    echo "LLM engine not installed or pinned binary/model/provenance verification failed; no changes made" >&2; exit 1;
  }
  echo "Pinned LLM engine verified (reasoning: --reasoning-budget 0)"
  exit 0
fi
if verify_binary && verify_model && verify_provenance && verify_runtime; then
  echo "Pinned LLM engine already installed"
  exit 0
fi
uv venv --python 3.11 --allow-existing "$DEST/venv"
uv pip install --python "$ENGINE_PYTHON" -r "$ROOT/backend/llm-engine/requirements-native.txt"
command -v cmake >/dev/null
command -v git >/dev/null
mkdir -p "$DEST/bin" "$DEST/models"
BUILD="$(mktemp -d "${TMPDIR:-/tmp}/sauri-llm.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT
git init -q "$BUILD/src"
git -C "$BUILD/src" remote add origin https://github.com/ggml-org/llama.cpp.git
git -C "$BUILD/src" fetch --depth 1 origin "$COMMIT"
git -C "$BUILD/src" checkout --detach FETCH_HEAD
[[ "$(git -C "$BUILD/src" rev-parse HEAD)" == "$COMMIT" ]]
cmake -S "$BUILD/src" -B "$BUILD/build" -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF -DLLAMA_OPENSSL=OFF -DGGML_METAL=ON
cmake --build "$BUILD/build" --config Release --target llama-server -j "$(sysctl -n hw.ncpu)"
install -m 700 "$BUILD/build/bin/llama-server" "$BINARY"
verify_binary || { echo "Compiled binary lacks required reasoning/context flags" >&2; exit 1; }
if ! verify_model; then
  curl --fail --location --retry 3 \
    "https://huggingface.co/$REPO/resolve/$REVISION/$MODEL" -o "$BUILD/model.gguf"
  [[ "$(shasum -a 256 "$BUILD/model.gguf" | cut -d' ' -f1)" == "$HASH" ]] || {
    echo "Model SHA-256 mismatch" >&2; exit 1;
  }
  mv "$BUILD/model.gguf" "$MODEL_PATH"
fi
py - "$DEST/provenance.json" "$ROOT/_tools/engine-hashes.json" "$BINARY" <<'PY'
import hashlib, json, sys
p = json.load(open(sys.argv[2]))['llm']
p.update(binary_sha256=hashlib.file_digest(open(sys.argv[3], 'rb'), 'sha256').hexdigest(),
         reasoning_args=['--reasoning-budget', '0'], reasoning_verified_by='compiled llama-server --help',
         cmake_args=['-DBUILD_SHARED_LIBS=OFF', '-DLLAMA_OPENSSL=OFF', '-DGGML_METAL=ON'])
with open(sys.argv[1], 'w') as f:
    json.dump(p, f, indent=2)
    f.write('\n')
PY
verify_provenance
echo "Installed pinned LLM engine; uses its isolated venv and the existing engine token"
