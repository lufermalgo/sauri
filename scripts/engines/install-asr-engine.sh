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
from asr_assets import (
    binary_record, load_manifest, vad_binary_record, vad_cli_path, vad_model_path, verify_model, verify_provenance,
)
from asr_config import vad_enabled

provenance = Path(venv).parent / "asr-provenance" / "provenance.json"
try:
    manifest = load_manifest()
    filename = manifest["model_file"]
    url = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{filename}"
    model = Path(os.environ.get("ASR_MODEL_PATH", f"~/.local/share/sauri/models/{filename}")).expanduser()
    cli = Path(os.environ.get("WHISPER_CLI", "/opt/homebrew/bin/whisper-cli")).expanduser()
    record = binary_record(cli, manifest)
    assets = [(model, manifest, url, "SAURI_ASR_MODEL_SOURCE")]
    if vad_enabled():
        vad = manifest["vad"]
        record.update(vad_binary_record(vad_cli_path(), vad))
        assets.append((vad_model_path(), vad, vad["model_url"], "SAURI_ASR_VAD_MODEL_SOURCE"))
    if provenance.exists():
        verify_provenance(record, provenance, allow_upgrade=mode != "--check")
    # Reject any corrupt installed asset before downloading or writing anything.
    for target, metadata, _, _ in assets:
        if target.exists():
            verify_model(target, metadata)
        elif mode == "--check":
            raise ValueError("ASR or VAD model unavailable")
    for target, metadata, asset_url, source_variable in assets:
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".asr-model-", dir=target.parent)
        os.close(fd)
        try:
            source = os.environ.get(source_variable)
            if source:
                shutil.copyfile(Path(source).expanduser(), temporary)
            else:
                with urllib.request.urlopen(asset_url, timeout=300) as response, open(temporary, "wb") as output:
                    shutil.copyfileobj(response, output)
            verify_model(Path(temporary), metadata)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if mode == "--check":
        verify_provenance(record, provenance)
    else:
        provenance.parent.mkdir(parents=True, exist_ok=True)
        if provenance.exists() and not vad_enabled():
            # Disabling VAD must not erase an already verified installation record.
            record = {**json.loads(provenance.read_text()), **record}
        temporary = provenance.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        temporary.replace(provenance)
except (OSError, ValueError, KeyError, TypeError) as exc:
    print(f"ASR verification failed: {exc}", file=sys.stderr)
    sys.exit(1)
print("ASR and enabled VAD asset checks passed")
PY
[[ "${1:-}" != --check ]] || exit 0
if [[ ! -x "$PYTHON" ]]; then
  [[ "$PYTHON" == "$VENV/bin/python" ]] || { echo "Configured Python is missing" >&2; exit 1; }
  "${NATIVE_PYTHON311:-python3.11}" -m venv "$VENV"
fi
"$PYTHON" -m pip install -r "$ROOT_DIR/scripts/engines/requirements-native-asr.txt"
