#!/usr/bin/env bash
# Install the Parakeet transcription engine (FluidAudio CLI, Core ML) from the pinned source, or adopt a copy
# that already exists on this Mac. Nothing unpinned is ever downloaded:
#   - the CLI is built from the commit in scripts/engines/engine-hashes.json (SwiftPM has no remote
#     dependencies; its one binary target is pinned by checksum in Package.swift);
#   - the model files are installed by the portal (Ajustes > Motores y modelos) or adopted below, and the
#     host service verifies every file against the catalog.
# Usage: install-parakeet-engine.sh [--check | --warm | --adopt-from DIR]
#   --check            verify the installed CLI against its provenance and the pinned commit
#   --warm             compile the Core ML models once (needs the model installed)
#   --adopt-from DIR   DIR holds bin/fluidaudiocli and models/parakeet-ultra (the benchmark folder layout):
#                      the binary is accepted only if it is a known build; the model is copied after every
#                      file is hashed against the catalog. DIR is not modified.
# Exit codes: 0 ok, 1 verification failed, 2 usage, 3 the toolchain needed to build is missing (Whisper keeps working).
set -euo pipefail
umask 077
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PARAKEET_HOME="${SAURI_PARAKEET_HOME:-${HOME}/.local/share/sauri/native-engines/parakeet}"
HASHES="${SAURI_ENGINE_HASHES_FILE:-${ROOT_DIR}/scripts/engines/engine-hashes.json}"
ASR_PYTHON="${SAURI_ASR_ENGINE_PYTHON:-${HOME}/.local/share/sauri/native-engines/asr-venv/bin/python}"
HOST_PYTHON="${SAURI_HOST_ENGINE_PYTHON:-${HOME}/.local/share/sauri/native-engines/host-venv/bin/python}"
MODEL_ID="parakeet-tdt-0.6b-v3-ultra-coreml"
BIN="${PARAKEET_HOME}/bin/fluidaudiocli"
PROVENANCE="${PARAKEET_HOME}/provenance.json"

MODE=install
ADOPT_DIR=""
case "${1:-}" in
  "") ;;
  --check) MODE=check ;;
  --warm) MODE=warm ;;
  --adopt-from) [[ $# -eq 2 ]] || { echo "Uso: $0 --adopt-from DIR" >&2; exit 2; }; MODE=adopt; ADOPT_DIR="$2" ;;
  *) echo "Uso: $0 [--check | --warm | --adopt-from DIR]" >&2; exit 2 ;;
esac

pin() {  # pin <field>: a value of the "parakeet" section of engine-hashes.json
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["parakeet"][sys.argv[2]])' "$HASHES" "$1"
}
COMMIT="$(pin source_commit)"
REPO="$(pin source_repo)"
MIN_MACOS="$(pin minimum_macos)"

sha256_of() { shasum -a 256 "$1" | cut -d' ' -f1; }

known_build() {  # known_build <sha256>
  python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1]))["parakeet"]["known_binary_sha256"] else 1)' "$HASHES" "$1"
}

write_provenance() {  # write_provenance <origin> <swift version line>
  mkdir -p "$PARAKEET_HOME"
  python3 - "$PROVENANCE" "$COMMIT" "$BIN" "$1" "$2" <<'PY'
import hashlib, json, os, sys, datetime
path, commit, binary, origin, swift = sys.argv[1:]
with open(binary, "rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
record = {
    "engine": "fluidaudio", "source_commit": commit, "binary_sha256": digest, "binary_size": os.path.getsize(binary),
    "origin": origin, "swift": swift, "installed_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
}
tmp = path + ".tmp"
with open(tmp, "w") as out:
    json.dump(record, out, indent=2)
    out.write("\n")
os.replace(tmp, path)
PY
}

verify_installed() {  # 0 = healthy, 2 = not installed, 1 = installed but does not match
  [[ -x "$BIN" && -f "$PROVENANCE" ]] || return 2
  python3 - "$PROVENANCE" "$COMMIT" "$BIN" "$HASHES" <<'PY' || return 1
import hashlib, json, sys
provenance, commit, binary, hashes = sys.argv[1:]
record = json.load(open(provenance))
with open(binary, "rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
known = json.load(open(hashes))["parakeet"]["known_binary_sha256"]
if record.get("source_commit") != commit or record.get("binary_sha256") != digest:
    sys.exit(1)
if record.get("origin") == "adopted" and digest not in known:
    sys.exit(1)
PY
}

model_installed() {
  [[ -x "$ASR_PYTHON" ]] || return 1
  PYTHONPATH="$ROOT_DIR/backend/engine-common" "$ASR_PYTHON" - <<PY
import sys
from sauri_engine_common.local_model_use import select_preferred
sys.exit(0 if select_preferred(process="transcription") is not None else 1)
PY
}

warm() {
  if ! model_installed; then
    echo "El modelo de Parakeet todavía no está instalado: instálalo desde Ajustes > Motores y modelos y vuelve a ejecutar $0 --warm." >&2
    return 0
  fi
  [[ -x "$ASR_PYTHON" ]] || { echo "No se encuentra el Python del motor de transcripción ($ASR_PYTHON); ejecuta make engines-install." >&2; return 1; }
  echo "Preparando Parakeet para el Neural Engine (la primera vez tarda ~1 minuto)..."
  SAURI_PARAKEET_HOME="$PARAKEET_HOME" PYTHONPATH="$ROOT_DIR/backend/engine-common:$ROOT_DIR/backend/asr-engine" \
    "$ASR_PYTHON" -m asr_parakeet --warm
}

if [[ "$MODE" == check ]]; then
  status=0; verify_installed || status=$?
  [[ $status -eq 0 ]] && echo "Parakeet: el motor coincide con el commit fijado ($COMMIT)"
  [[ $status -eq 2 ]] && echo "Parakeet: motor no instalado" >&2
  [[ $status -eq 1 ]] && echo "Parakeet: el motor instalado NO coincide con su registro de procedencia" >&2
  exit $status
fi
if [[ "$MODE" == warm ]]; then warm; exit $?; fi

[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo "Parakeet necesita un Mac con Apple Silicon; esta transcripción seguirá usando Whisper." >&2; exit 3; }
[[ "$(sw_vers -productVersion | cut -d. -f1)" -ge "$MIN_MACOS" ]] || {
  echo "Parakeet necesita macOS $MIN_MACOS o posterior; esta transcripción seguirá usando Whisper." >&2; exit 3; }

status=0; verify_installed || status=$?
if [[ $status -eq 1 ]]; then
  echo "El motor de Parakeet instalado no coincide con su registro; no se reemplaza solo. Revisa $PARAKEET_HOME." >&2; exit 1
fi

if [[ $status -eq 2 ]]; then
  mkdir -p "$PARAKEET_HOME/bin"
  if [[ "$MODE" == adopt ]]; then
    SOURCE_BIN="$ADOPT_DIR/bin/fluidaudiocli"
    [[ -x "$SOURCE_BIN" ]] || { echo "No existe $SOURCE_BIN" >&2; exit 1; }
    known_build "$(sha256_of "$SOURCE_BIN")" || { echo "El binario de $ADOPT_DIR no es una compilación conocida del commit fijado." >&2; exit 1; }
    cp "$SOURCE_BIN" "$BIN.tmp"; chmod 0755 "$BIN.tmp"; mv "$BIN.tmp" "$BIN"
    write_provenance adopted "adopted: Swift 6.4.2 build of $COMMIT"
    echo "Motor de Parakeet adoptado (copiado y verificado por hash)."
  else
    command -v swift >/dev/null 2>&1 && xcode-select -p >/dev/null 2>&1 || {
      echo "Falta la herramienta de Swift (instala Xcode o las Command Line Tools con: xcode-select --install). Sin ella no se puede construir el motor de Parakeet y la transcripción seguirá usando Whisper." >&2
      exit 3; }
    SWIFT_VERSION="$(swift --version 2>&1 | head -1)"
    [[ "$(swift --version 2>&1 | grep -Eo 'Swift version [0-9]+' | grep -Eo '[0-9]+$' | head -1)" -ge 6 ]] || {
      echo "Parakeet necesita Swift 6 o posterior ($SWIFT_VERSION). Actualiza Xcode; mientras tanto la transcripción seguirá usando Whisper." >&2; exit 3; }
    WORK="$(mktemp -d "${TMPDIR:-/tmp}/sauri-fluidaudio.XXXXXX")"
    trap 'rm -rf "$WORK"' EXIT
    git init -q "$WORK/src"
    git -C "$WORK/src" remote add origin "$REPO"
    git -C "$WORK/src" fetch -q --depth 1 origin "$COMMIT"
    git -C "$WORK/src" checkout -q FETCH_HEAD
    [[ "$(git -C "$WORK/src" rev-parse HEAD)" == "$COMMIT" ]] || { echo "El código descargado no es el commit fijado." >&2; exit 1; }
    echo "Construyendo FluidAudio $COMMIT (unos 3 minutos)..."
    (cd "$WORK/src" && swift build -c release --product fluidaudiocli --scratch-path "$WORK/build") >"$WORK/build.log" 2>&1 || {
      tail -20 "$WORK/build.log" >&2; echo "La construcción falló; la transcripción seguirá usando Whisper." >&2; exit 3; }
    cp -L "$WORK/build/release/fluidaudiocli" "$BIN.tmp"; chmod 0755 "$BIN.tmp"; mv "$BIN.tmp" "$BIN"
    write_provenance built "$SWIFT_VERSION"
    echo "Motor de Parakeet construido y registrado."
  fi
fi

if [[ "$MODE" == adopt ]]; then
  [[ -x "$HOST_PYTHON" ]] || { echo "No se encuentra el Python del servicio host ($HOST_PYTHON); ejecuta make engines-install." >&2; exit 1; }
  (cd "$ROOT_DIR/backend/host-engine" && PYTHONPATH="$ROOT_DIR/backend/engine-common" \
    "$HOST_PYTHON" seed_model.py "$MODEL_ID" "$ADOPT_DIR/models/parakeet-ultra")
fi
verify_installed
warm
echo "Parakeet listo. Reinicia los motores nativos (make engines-down && make engines-up) para que lo usen."
