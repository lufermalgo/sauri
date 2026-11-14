#!/usr/bin/env bash
# Verify assets before provisioning the lightweight whisper.cpp HTTP service.
set -euo pipefail
umask 077
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${SAURI_ASR_VENV:-${HOME}/.local/share/sauri/native-engines/asr-venv}"
PYTHON="${SAURI_ASR_ENGINE_PYTHON:-${VENV}/bin/python}"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --check ) ]] || { echo "Usage: $0 [--check]" >&2; exit 2; }
"${NATIVE_PYTHON311:-python3.11}" - "$ROOT_DIR" "${1:-}" "$VENV" <<'PY'
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

root, mode, venv = sys.argv[1:]
sys.path.insert(0, str(Path(root) / "backend/asr-engine"))
from asr_assets import binary_record, load_manifest, verify_model, verify_provenance

provenance = Path(venv).parent / "asr-provenance" / "provenance.json"
try:
    manifest = load_manifest()
    filename = manifest["model_file"]
    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
    model = Path(os.environ.get("ASR_MODEL_PATH", f"~/.local/share/sauri/models/{filename}")).expanduser()
    cli = Path(os.environ.get("WHISPER_CLI", "/opt/homebrew/bin/whisper-cli")).expanduser()
    record = binary_record(cli, manifest)
    if provenance.exists():
        verify_provenance(record, provenance)
    if model.exists():
        verify_model(model, manifest)  # Never repair or overwrite a corrupt installed model.
    elif mode == "--check":
        raise ValueError("ASR model unavailable")
    else:
        model.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".asr-model-", dir=model.parent)
        os.close(fd)
        try:
            source = os.environ.get("SAURI_ASR_MODEL_SOURCE")
            if source:
                shutil.copyfile(Path(source).expanduser(), temporary)
            else:
                with urllib.request.urlopen(url, timeout=300) as response, open(temporary, "wb") as output:
                    shutil.copyfileobj(response, output)
            verify_model(Path(temporary), manifest)
            os.replace(temporary, model)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if mode == "--check":
        verify_provenance(record, provenance)
    else:
        provenance.parent.mkdir(parents=True, exist_ok=True)
        temporary = provenance.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        temporary.replace(provenance)
except (OSError, ValueError, KeyError, TypeError) as exc:
    print(f"ASR verification failed: {exc}", file=sys.stderr)
    sys.exit(1)
print("ASR model size, SHA-256 and whisper-cli checks passed")
PY
[[ "${1:-}" != --check ]] || exit 0
if [[ ! -x "$PYTHON" ]]; then
  [[ "$PYTHON" == "$VENV/bin/python" ]] || { echo "Configured Python is missing" >&2; exit 1; }
  "${NATIVE_PYTHON311:-python3.11}" -m venv "$VENV"
fi
"$PYTHON" -m pip install -r "$ROOT_DIR/scripts/engines/requirements-native-asr.txt"
