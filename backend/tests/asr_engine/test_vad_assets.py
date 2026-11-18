"""Startup verifies VAD assets without executing either inference binary."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest
from test_native_contract import native

assets = importlib.import_module("asr_assets")


@pytest.fixture
def installed(monkeypatch, tmp_path):
    monkeypatch.setenv("SAURI_ASR_VAD", "on")
    monkeypatch.setenv("SAURI_ASR_VENV", str(tmp_path / "asr-venv"))
    model, cli = tmp_path / "asr.bin", tmp_path / "asr-cli"
    vad_model, vad_cli = tmp_path / "vad.bin", tmp_path / "vad-cli"
    for path in (model, cli, vad_model, vad_cli):
        path.write_bytes(b"synthetic " + path.name.encode())
    cli.chmod(0o700)
    vad_cli.chmod(0o700)
    def metadata(path):
        return {"model_file": path.name, "model_size": path.stat().st_size,
                "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = metadata(model)
    manifest["vad"] = {**metadata(vad_model), "binary_size": vad_cli.stat().st_size,
                       "binary_sha256": assets.digest(vad_cli),
                       "model_url": "https://huggingface.co/ggml-org/whisper-vad/resolve/synthetic/vad.bin"}
    hashes = tmp_path / "hashes.json"
    hashes.write_text(json.dumps({"asr": manifest}))
    monkeypatch.setenv("SAURI_ENGINE_HASHES_FILE", str(hashes))
    monkeypatch.setenv("SAURI_ASR_VAD_MODEL_PATH", str(vad_model))
    monkeypatch.setenv("SAURI_ASR_VAD_CLI", str(vad_cli))
    monkeypatch.setattr(native, "ASR_MODEL_PATH", model)
    monkeypatch.setattr(native, "WHISPER_CLI", str(cli))
    record = assets.binary_record(cli, manifest)
    record.update(assets.vad_binary_record(vad_cli, manifest["vad"]))
    provenance = assets.provenance_path()
    provenance.parent.mkdir()
    provenance.write_text(json.dumps(record))
    monkeypatch.setattr(native, "object_store_credentials", lambda: ("synthetic", "synthetic"))
    calls = []
    monkeypatch.setattr(native.boto3, "client", lambda *args, **kwargs: calls.append(True) or object())
    def unexpected(*args, **kwargs):
        pytest.fail("Startup verification must never execute inference")
    monkeypatch.setattr(native, "run_group", unexpected)
    return {"model": vad_model, "binary": vad_cli, "provenance": provenance, "calls": calls,
            "record": record, "hashes": hashes}


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [
    "model_missing", "model_hash", "model_size", "binary_missing", "binary_hash", "binary_not_executable",
    "provenance_missing", "provenance_hash", "provenance_legacy", "manifest",
])
async def test_vad_assets_fail_closed_before_object_store_initialization(installed, tamper):
    if tamper.endswith("missing"):
        installed[tamper.removesuffix("_missing")].unlink()
    elif tamper in {"model_hash", "binary_hash"}:
        path = installed[tamper.split("_")[0]]
        path.write_bytes(b"x" * path.stat().st_size)
    elif tamper == "model_size":
        installed["model"].write_bytes(b"x")
    elif tamper == "binary_not_executable":
        installed["binary"].chmod(0o600)
    elif tamper == "manifest":
        manifest = json.loads(installed["hashes"].read_text())
        manifest["asr"]["vad"]["binary_sha256"] = "invalid"
        installed["hashes"].write_text(json.dumps(manifest))
    else:
        record = installed["record"].copy()
        if tamper == "provenance_hash":
            record["vad_model_sha256"] = "0" * 64
        else:
            record.pop("vad_model_sha256")
            record.pop("vad_binary_sha256")
        installed["provenance"].write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="asset verification failed"):
        async with native.lifespan(native.app):
            pytest.fail("Invalid VAD assets must prevent startup")
    assert installed["calls"] == []


@pytest.mark.asyncio
async def test_vad_verified_startup_does_not_run_inference(installed):
    async with native.lifespan(native.app):
        assert installed["calls"] == [True]
        assert native.s3_client is not None
    assert native.s3_client is None


@pytest.mark.asyncio
async def test_explicit_off_works_with_enriched_provenance_and_without_vad_assets(monkeypatch, installed):
    monkeypatch.setenv("SAURI_ASR_VAD", "off")
    installed["model"].unlink()
    installed["binary"].unlink()
    async with native.lifespan(native.app):
        assert installed["calls"] == [True]


def test_only_explicit_installer_upgrade_accepts_legacy_provenance(installed):
    record = installed["record"]
    legacy = {key: value for key, value in record.items() if not key.startswith("vad_")}
    installed["provenance"].write_text(json.dumps(legacy))
    with pytest.raises(ValueError, match="provenance mismatch"):
        assets.verify_provenance(record, installed["provenance"])
    assets.verify_provenance(record, installed["provenance"], allow_upgrade=True)
    legacy["binary_sha256"] = "0" * 64
    installed["provenance"].write_text(json.dumps(legacy))
    with pytest.raises(ValueError, match="provenance mismatch"):
        assets.verify_provenance(record, installed["provenance"], allow_upgrade=True)


def test_repository_pins_measured_vad_assets():
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "scripts/engines/engine-hashes.json").read_text())["asr"]["vad"]
    assert manifest["model_size"] == 885098
    assert manifest["model_sha256"] == "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987"
    assert "/9ffd54a1e1ee413ddf265af9913beaf518d1639b/" in manifest["model_url"]
    assert manifest["binary_size"] == 452336 and len(manifest["binary_sha256"]) == 64


def test_runtime_vad_build_is_accepted_and_unpinned_builds_are_not(installed, tmp_path):
    manifest = json.loads(installed["hashes"].read_text())["asr"]["vad"]
    runtime_cli = tmp_path / "runtime-vad-cli"
    runtime_cli.write_bytes(b"synthetic runtime build")
    runtime_cli.chmod(0o700)
    with pytest.raises(ValueError, match="VAD binary size or SHA-256 mismatch"):
        assets.vad_binary_record(runtime_cli, manifest)
    manifest["runtime_binary"] = {"size": runtime_cli.stat().st_size, "sha256": assets.digest(runtime_cli)}
    record = assets.vad_binary_record(runtime_cli, manifest)
    assert record["vad_binary_sha256"] == assets.digest(runtime_cli)
    # The Homebrew pin keeps working next to the runtime one.
    assert assets.vad_binary_record(installed["binary"], manifest)["vad_binary_sha256"] == assets.digest(
        installed["binary"]
    )


@pytest.mark.parametrize("where", ["asr", "vad"])
def test_malformed_runtime_pin_is_rejected(installed, where):
    hashes = json.loads(installed["hashes"].read_text())
    section = hashes["asr"] if where == "asr" else hashes["asr"]["vad"]
    section["runtime_binary"] = {"size": 1, "sha256": "invalid"}
    installed["hashes"].write_text(json.dumps(hashes))
    with pytest.raises(ValueError, match="hash manifest"):
        assets.load_manifest()


def test_runtime_pins_match_the_desktop_runtime_manifest():
    root = Path(__file__).resolve().parents[3]
    asr = json.loads((root / "scripts/engines/engine-hashes.json").read_text())["asr"]
    runtime = json.loads((root / "desktop/runtime-manifest.json").read_text())
    whisper = next(artifact for artifact in runtime["artifacts"] if artifact["name"] == "whisper.cpp")
    assert asr["runtime_binary"]["sha256"] == whisper["binaries"]["whisper-cli"]["sha256"]
    assert asr["vad"]["runtime_binary"]["sha256"] == whisper["binaries"]["whisper-vad-speech-segments"]["sha256"]
