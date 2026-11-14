"""Shared, fail-closed asset verification for installation and startup."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


def manifest_path() -> Path:
    return Path(os.environ.get(
        "SAURI_ENGINE_HASHES_FILE", str(Path(__file__).resolve().parents[2] / "scripts/engines/engine-hashes.json"),
    ))


def provenance_path() -> Path:
    venv = Path(os.environ.get("SAURI_ASR_VENV", "~/.local/share/sauri/native-engines/asr-venv")).expanduser()
    return venv.parent / "asr-provenance" / "provenance.json"


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(manifest_path().read_text())["asr"]
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("model_size")) is not int or manifest["model_size"] <= 0
        or not isinstance(manifest.get("model_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest["model_sha256"]) is None
        or not isinstance(manifest.get("model_file"), str)
        or Path(manifest["model_file"]).name != manifest["model_file"]
    ):
        raise ValueError("Invalid ASR hash manifest")
    return manifest


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_model(path: Path, manifest: dict[str, Any]) -> None:
    if path.stat().st_size != manifest["model_size"] or digest(path) != manifest["model_sha256"]:
        raise ValueError("ASR model size or SHA-256 mismatch")


def binary_record(cli: Path, manifest: dict[str, Any]) -> dict[str, str]:
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ValueError("whisper-cli executable unavailable")
    return {"engine": "whisper.cpp", "binary_sha256": digest(cli), "model_sha256": manifest["model_sha256"]}


def verify_provenance(record: dict[str, str], path: Path) -> None:
    if not path.is_file():
        raise ValueError("ASR provenance unavailable")
    if json.loads(path.read_text()) != record:
        raise ValueError("ASR provenance mismatch")


def verify_assets(model: Path, cli: Path) -> None:
    manifest = load_manifest()
    verify_model(model, manifest)
    verify_provenance(binary_record(cli, manifest), provenance_path())
