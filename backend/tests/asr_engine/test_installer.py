"""Fail-closed ASR installer checks with small, isolated synthetic assets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "scripts/engines/install-asr-engine.sh"
MODEL = b"synthetic model"


def environment(tmp_path):
    cli = tmp_path / "whisper-cli"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o700)
    manifest = {"asr": {"model_file": "model.bin", "model_size": len(MODEL),
                        "model_sha256": hashlib.sha256(MODEL).hexdigest()}}
    hashes = tmp_path / "hashes.json"
    hashes.write_text(json.dumps(manifest))
    return {**os.environ, "WHISPER_CLI": str(cli), "NATIVE_PYTHON311": sys.executable,
            "ASR_MODEL_PATH": str(tmp_path / "model.bin"), "SAURI_ASR_VENV": str(tmp_path / "asr-venv"),
            "SAURI_ASR_ENGINE_PYTHON": str(tmp_path / "asr-venv/bin/python"),
            "SAURI_ENGINE_HASHES_FILE": str(hashes)}


@pytest.mark.parametrize("check_only", [True, False])
@pytest.mark.parametrize("size_matches", [True, False])
def test_corrupt_model_fails_closed_without_replacing_it(tmp_path, check_only, size_matches):
    env = environment(tmp_path)
    model = Path(env["ASR_MODEL_PATH"])
    model.write_bytes(b"x" * (len(MODEL) if size_matches else 1))
    before = model.stat()
    result = subprocess.run(["bash", str(INSTALLER), *(["--check"] if check_only else [])],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "size or SHA-256 mismatch" in result.stderr
    assert model.stat().st_size == before.st_size and model.stat().st_mtime_ns == before.st_mtime_ns
    assert not (tmp_path / "asr-venv").exists()
    assert not (tmp_path / "asr-provenance").exists()


def test_altered_manifest_is_rejected(tmp_path):
    env = environment(tmp_path)
    Path(env["ASR_MODEL_PATH"]).write_bytes(MODEL)
    hashes = Path(env["SAURI_ENGINE_HASHES_FILE"])
    manifest = json.loads(hashes.read_text())
    manifest["asr"]["model_sha256"] = "0" * 64
    hashes.write_text(json.dumps(manifest))
    result = subprocess.run(["bash", str(INSTALLER), "--check"], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "SHA-256 mismatch" in result.stderr


def test_check_rejects_missing_provenance_without_writing_it(tmp_path):
    env = environment(tmp_path)
    Path(env["ASR_MODEL_PATH"]).write_bytes(MODEL)
    result = subprocess.run(["bash", str(INSTALLER), "--check"], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "provenance unavailable" in result.stderr
    assert not (tmp_path / "asr-provenance").exists()


def test_preseeded_model_provenance_and_binary_tampering(tmp_path):
    env = environment(tmp_path)
    Path(env["ASR_MODEL_PATH"]).write_bytes(MODEL)
    python = Path(env["SAURI_ASR_ENGINE_PYTHON"])
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\n[ "$1 $2 $3" = "-m pip install" ]\n')
    python.chmod(0o700)
    result = subprocess.run(["bash", str(INSTALLER)], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    provenance = tmp_path / "asr-provenance/provenance.json"
    record = json.loads(provenance.read_text())
    assert record["binary_sha256"] == hashlib.sha256(Path(env["WHISPER_CLI"]).read_bytes()).hexdigest()
    before = provenance.read_bytes()
    result = subprocess.run(["bash", str(INSTALLER), "--check"], env=env, capture_output=True, timeout=30)
    assert result.returncode == 0
    assert provenance.read_bytes() == before
    Path(env["WHISPER_CLI"]).write_text("#!/bin/sh\nexit 1\n")
    result = subprocess.run(["bash", str(INSTALLER), "--check"], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and "provenance mismatch" in result.stderr
    assert provenance.read_bytes() == before
