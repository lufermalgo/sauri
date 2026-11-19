"""Shared, fail-closed asset verification for installation and startup."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from asr_config import vad_enabled


def manifest_path() -> Path:
    return Path(os.environ.get(
        "SAURI_ENGINE_HASHES_FILE", str(Path(__file__).resolve().parents[2] / "scripts/engines/engine-hashes.json"),
    ))


def provenance_path() -> Path:
    venv = Path(os.environ.get("SAURI_ASR_VENV", "~/.local/share/sauri/native-engines/asr-venv")).expanduser()
    return venv.parent / "asr-provenance" / "provenance.json"


def _valid_pin(pin: Any) -> bool:
    """A pinned build: exact size and SHA-256 of one binary file."""
    return (
        isinstance(pin, dict)
        and type(pin.get("size")) is int and pin["size"] > 0
        and isinstance(pin.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is not None
    )


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(manifest_path().read_text())["asr"]
    manifest = _validate_model(manifest)
    # The desktop runtime ships its own whisper.cpp build; its pin is optional but never malformed.
    if "runtime_binary" in manifest and not _valid_pin(manifest["runtime_binary"]):
        raise ValueError("Invalid ASR hash manifest")
    if vad_enabled():
        vad = manifest["vad"]
        _validate_model(vad)
        if (
            type(vad.get("binary_size")) is not int or vad["binary_size"] <= 0
            or not isinstance(vad.get("binary_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", vad["binary_sha256"]) is None
            or not isinstance(vad.get("model_url"), str)
            or not vad["model_url"].startswith("https://huggingface.co/ggml-org/whisper-vad/resolve/")
            or ("runtime_binary" in vad and not _valid_pin(vad["runtime_binary"]))
        ):
            raise ValueError("Invalid VAD hash manifest")
    return manifest


def _validate_model(manifest: Any) -> dict[str, Any]:
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("model_size")) is not int or manifest["model_size"] <= 0
        or not isinstance(manifest.get("model_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest["model_sha256"]) is None
        or not isinstance(manifest.get("model_file"), str)
        or manifest["model_file"] in {"", ".", ".."}
        or Path(manifest["model_file"]).name != manifest["model_file"]
    ):
        raise ValueError("Invalid ASR hash manifest")
    return manifest


def vad_model_path() -> Path:
    return Path(os.environ.get(
        "SAURI_ASR_VAD_MODEL_PATH", "~/.local/share/sauri/models/ggml-silero-v6.2.0.bin",
    )).expanduser()


def vad_cli_path() -> Path:
    return Path(os.environ.get("SAURI_ASR_VAD_CLI", "/opt/homebrew/bin/whisper-vad-speech-segments")).expanduser()


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


def vad_binary_record(cli: Path, manifest: dict[str, Any]) -> dict[str, str]:
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ValueError("VAD executable unavailable")
    # Accepted builds: the Homebrew one and, when pinned, the desktop runtime's own build.
    accepted = {(manifest["binary_size"], manifest["binary_sha256"])}
    if "runtime_binary" in manifest:
        accepted.add((manifest["runtime_binary"]["size"], manifest["runtime_binary"]["sha256"]))
    actual = digest(cli)
    if (cli.stat().st_size, actual) not in accepted:
        raise ValueError("VAD binary size or SHA-256 mismatch")
    return {"vad_binary_sha256": actual, "vad_model_sha256": manifest["model_sha256"]}


def verify_provenance(record: dict[str, str], path: Path, *, allow_upgrade: bool = False) -> None:
    if not path.is_file():
        raise ValueError("ASR provenance unavailable")
    stored = json.loads(path.read_text())
    if not isinstance(stored, dict):
        raise ValueError("Invalid ASR provenance")
    if "vad_binary_sha256" not in record:
        stored = {key: value for key, value in stored.items() if key not in {"vad_binary_sha256", "vad_model_sha256"}}
    expected = record
    if allow_upgrade and "vad_binary_sha256" not in stored and "vad_model_sha256" not in stored:
        expected = {key: value for key, value in record.items() if key not in {"vad_binary_sha256", "vad_model_sha256"}}
    if stored != expected:
        raise ValueError("ASR provenance mismatch")


def verify_runtime(cli: Path) -> dict[str, Any]:
    """Check the whisper.cpp binaries against their recorded provenance and return the manifest.

    Model files are not part of it: each one belongs to the model that uses it and is checked with ``file_problem``,
    so an engine whose active model is Parakeet starts without any Whisper file on disk.
    """
    manifest = load_manifest()
    record = binary_record(cli, manifest)
    if vad_enabled():
        record.update(vad_binary_record(vad_cli_path(), manifest["vad"]))
    verify_provenance(record, provenance_path())
    return manifest


def file_problem(path: Path, metadata: dict[str, Any]) -> str | None:
    """``None`` for the pinned file, else the request code: ``model_not_installed`` or ``model_not_verified``."""
    try:
        verify_model(path, metadata)
    except FileNotFoundError:
        return "model_not_installed"
    except (OSError, ValueError):
        return "model_not_verified"
    return None
