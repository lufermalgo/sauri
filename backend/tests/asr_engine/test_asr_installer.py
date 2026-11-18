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
    return {**os.environ, "SAURI_ASR_VAD": "off", "WHISPER_CLI": str(cli), "NATIVE_PYTHON311": sys.executable,
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


def vad_environment(tmp_path):
    env = environment(tmp_path)
    env["SAURI_ASR_VAD"] = "on"
    Path(env["ASR_MODEL_PATH"]).write_bytes(MODEL)
    vad_cli = tmp_path / "vad-cli"
    vad_cli.write_bytes(b"synthetic VAD executable")
    vad_cli.chmod(0o700)
    source = tmp_path / "vad-source.bin"
    source.write_bytes(b"synthetic VAD model")
    env.update({"SAURI_ASR_VAD_CLI": str(vad_cli), "SAURI_ASR_VAD_MODEL_PATH": str(tmp_path / "vad.bin"),
                "SAURI_ASR_VAD_MODEL_SOURCE": str(source)})
    hashes = Path(env["SAURI_ENGINE_HASHES_FILE"])
    manifest = json.loads(hashes.read_text())
    manifest["asr"]["vad"] = {
        "model_file": "vad.bin", "model_size": source.stat().st_size,
        "model_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "binary_size": vad_cli.stat().st_size, "binary_sha256": hashlib.sha256(vad_cli.read_bytes()).hexdigest(),
        "model_url": "https://huggingface.co/ggml-org/whisper-vad/resolve/synthetic/vad.bin",
    }
    hashes.write_text(json.dumps(manifest))
    return env


def run_asset_provisioning(monkeypatch, env, mode=""):
    """Exercise only the installer's Python asset block; never create venvs or run pip."""
    import urllib.request

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["-", str(ROOT), mode, env["SAURI_ASR_VENV"]])
    monkeypatch.setattr(sys, "path", sys.path.copy())
    def no_network(*args, **kwargs):
        pytest.fail("Installer tests must never download real assets")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    block = INSTALLER.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    exec(compile(block, str(INSTALLER), "exec"), {})


def test_vad_provisioning_copies_verified_source_and_check_is_read_only(monkeypatch, tmp_path):
    env = vad_environment(tmp_path)
    run_asset_provisioning(monkeypatch, env)
    target = Path(env["SAURI_ASR_VAD_MODEL_PATH"])
    assert target.read_bytes() == Path(env["SAURI_ASR_VAD_MODEL_SOURCE"]).read_bytes()
    provenance = tmp_path / "asr-provenance/provenance.json"
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (target, provenance)}
    record = json.loads(provenance.read_text())
    assert record["vad_model_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert record["vad_binary_sha256"] == hashlib.sha256(Path(env["SAURI_ASR_VAD_CLI"]).read_bytes()).hexdigest()
    run_asset_provisioning(monkeypatch, env, "--check")
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before} == before
    assert not (tmp_path / "asr-venv").exists()


@pytest.mark.parametrize("failure", ["source_hash", "installed_hash", "binary_hash", "binary_missing", "check_missing"])
def test_vad_installer_fails_without_replacing_assets_or_provenance(monkeypatch, tmp_path, failure):
    env = vad_environment(tmp_path)
    source = Path(env["SAURI_ASR_VAD_MODEL_SOURCE"])
    target = Path(env["SAURI_ASR_VAD_MODEL_PATH"])
    cli = Path(env["SAURI_ASR_VAD_CLI"])
    mode = ""
    if failure == "source_hash":
        source.write_bytes(b"x" * source.stat().st_size)
    elif failure == "installed_hash":
        target.write_bytes(b"x" * source.stat().st_size)
    elif failure == "binary_hash":
        cli.write_bytes(b"x" * cli.stat().st_size)
    elif failure == "binary_missing":
        cli.unlink()
    else:
        mode = "--check"
    before = target.read_bytes() if target.exists() else None
    with pytest.raises(SystemExit) as exc:
        run_asset_provisioning(monkeypatch, env, mode)
    assert exc.value.code == 1
    assert (target.read_bytes() if target.exists() else None) == before
    assert not list(tmp_path.glob(".asr-model-*"))
    assert not (tmp_path / "asr-provenance").exists()
    assert not (tmp_path / "asr-venv").exists()


def test_installer_upgrades_legacy_record_only_after_vad_verification(monkeypatch, tmp_path):
    env = vad_environment(tmp_path)
    manifest = json.loads(Path(env["SAURI_ENGINE_HASHES_FILE"]).read_text())["asr"]
    record = {
        "engine": "whisper.cpp", "binary_sha256": hashlib.sha256(Path(env["WHISPER_CLI"]).read_bytes()).hexdigest(),
        "model_sha256": manifest["model_sha256"],
    }
    provenance = tmp_path / "asr-provenance/provenance.json"
    provenance.parent.mkdir()
    provenance.write_text(json.dumps(record))
    run_asset_provisioning(monkeypatch, env)
    updated = json.loads(provenance.read_text())
    assert all(updated[key] == value for key, value in record.items())
    assert updated["vad_model_sha256"] == manifest["vad"]["model_sha256"]
    before = provenance.read_bytes()
    env["SAURI_ASR_VAD"] = "off"
    run_asset_provisioning(monkeypatch, env)
    assert provenance.read_bytes() == before
