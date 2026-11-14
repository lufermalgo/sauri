"""Read-only installer checks using the provisioned venv and isolated synthetic metadata."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PYTHON = Path(os.environ.get(
    "SAURI_DIAR_ENGINE_PYTHON", "~/.local/share/sauri/native-engines/diar-venv/bin/python",
)).expanduser()


@pytest.mark.skipif(not PYTHON.is_file(), reason="Senko installer venv not provisioned; run install-diar-engine.sh")
def test_check_is_idempotent_and_rejects_tampered_hash(tmp_path: Path) -> None:
    provisioned = subprocess.run(
        [str(PYTHON), "-c", "import importlib.metadata; importlib.metadata.distribution('senko')"],
        capture_output=True, timeout=30,
    )
    if provisioned.returncode:
        pytest.skip("Senko is not installed in the configured diarization venv")
    env = {**os.environ, "SAURI_DIAR_ENGINE_PYTHON": str(PYTHON), "PYTHONDONTWRITEBYTECODE": "1"}
    command = ["bash", str(ROOT / "_tools/install-diar-engine.sh"), "--check"]
    for _ in range(2):
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    manifest = json.loads((ROOT / "_tools/engine-hashes.json").read_text())
    files = manifest["senko"]["files"]
    files[next(iter(files))] = "0" * 64
    altered = tmp_path / "hashes.json"
    altered.write_text(json.dumps(manifest))
    result = subprocess.run(command, env={**env, "SAURI_ENGINE_HASHES_FILE": str(altered)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "SHA-256 mismatch" in result.stderr


@pytest.mark.parametrize("origin_kind", ["vcs", "local", "local_with_vcs", "wrong_commit"])
@pytest.mark.parametrize("tampered", [False, True])
def test_check_verifies_provenance_and_hashes_without_installed_senko(
    tmp_path: Path, origin_kind: str, tampered: bool,
) -> None:
    commit = "1bcb09041bfa170b4a5a4b0af92f66eff76204d5"
    package = tmp_path / "senko"
    package.mkdir()
    model = package / "model.bin"
    model.write_bytes(b"synthetic-model")
    metadata = tmp_path / "senko-0.1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: senko\nVersion: 0.1.0\n")
    origin: dict[str, object] = {"url": "https://github.com/narcotic-sh/senko.git",
                                "vcs_info": {"vcs": "git", "commit_id": commit}}
    if origin_kind.startswith("local"):
        origin["url"] = "file:///synthetic/senko"
    if origin_kind == "local":
        origin.pop("vcs_info")
    if origin_kind == "wrong_commit":
        origin["vcs_info"] = {"vcs": "git", "commit_id": "0" * 40}
    (metadata / "direct_url.json").write_text(json.dumps(origin))
    digest = "0" * 64 if tampered else hashlib.sha256(model.read_bytes()).hexdigest()
    manifest = tmp_path / "hashes.json"
    manifest.write_text(json.dumps({"senko": {"commit": commit, "files": {"senko/model.bin": digest}}}))
    result = subprocess.run(
        ["bash", str(ROOT / "_tools/install-diar-engine.sh"), "--check"],
        env={**os.environ, "PYTHONPATH": str(tmp_path), "SAURI_DIAR_ENGINE_PYTHON": sys.executable,
             "SAURI_ENGINE_HASHES_FILE": str(manifest), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == (0 if origin_kind == "vcs" and not tampered else 1), result.stderr


@pytest.mark.parametrize("script", ["install-diar-engine.sh", "native-engines.sh"])
def test_diarization_never_uses_legacy_asr_python(tmp_path: Path, script: str) -> None:
    marker = tmp_path / "legacy-invoked"
    legacy = tmp_path / "legacy-python"
    legacy.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 0\n")
    legacy.chmod(0o700)
    credentials = tmp_path / ".config/sauri"
    credentials.mkdir(parents=True)
    for name in ("engine_token", "recording_capability_key"):
        (credentials / name).write_text("synthetic-secret")
    env = {key: value for key, value in os.environ.items() if not key.startswith("SAURI_")}
    env.update(HOME=str(tmp_path), SAURI_NATIVE_ENGINE_PYTHON=str(legacy), SAURI_NATIVE_VENV=str(tmp_path))
    arguments = ["--check"] if script == "install-diar-engine.sh" else ["start", "diar"]
    result = subprocess.run(["bash", str(ROOT / "_tools" / script), *arguments],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert not marker.exists()
