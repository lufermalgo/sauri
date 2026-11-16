"""Synthetic HTTP contract tests for the host-native ASR engine."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import json
import logging
import sys
import threading
import time
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "native_main.py"
sys.path[:0] = [str(MODULE_PATH.parent), str(MODULE_PATH.parent.parent / "engine-common")]
MODULE_SPEC = importlib.util.spec_from_file_location("native_asr_engine", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
native = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = native
MODULE_SPEC.loader.exec_module(native)


class SyntheticBody(BytesIO):
    """Like a real streaming body here: no set_socket_timeout (it breaks on current botocore)."""


class FakeS3:
    def get_object(self, **kwargs):
        assert kwargs["Bucket"] == "synthetic-bucket"
        assert kwargs["Key"] == "synthetic/recording.wav"
        return {"Body": SyntheticBody(b"synthetic audio")}


def capability(audio_ref: str, secret: bytes, expires_at: int) -> str:
    message = f"{audio_ref}\n{expires_at}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("SAURI_ASR_VAD", "off")
    monkeypatch.setenv("SAURI_ASR_SUPPRESS_NST", "off")
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(tmp_path / "absent-vocabulary"))
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token")
    key_path = tmp_path / "capability_key"
    key_path.write_bytes(b"synthetic-secret")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native, "s3_client", FakeS3())
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))
    def normalize(source, dest, **kwargs):
        dest.write_bytes(b"normalized")
        return SimpleNamespace(audio_ms=2000, seconds=0.01)
    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    return {
        "Authorization": "Bearer synthetic-token",
        "X-Sauri-Recording-Capability": capability(
            "synthetic/recording.wav", b"synthetic-secret", int(time.time()) + 60),
    }


def document():
    return {"result": {"language": "en"}, "transcription": [{
        "text": " hello", "offsets": {"from": 250, "to": 1500},
        "tokens": [{"text": " hello", "id": 1, "p": 0.9, "offsets": {"from": 500, "to": 200}}],
    }]}


@pytest.mark.asyncio
async def test_transcribe_preserves_response_contract_and_cleans_temp_file(monkeypatch, tmp_path, configured):
    before = set(tmp_path.iterdir())
    def run(command, **kwargs):
        assert command == [native.WHISPER_CLI, "-m", str(native.ASR_MODEL_PATH),
                           "-f", command[4], "-l", "auto", "-t", "4", "-bs", "5", "-bo", "5",
                           "-fa", "-ojf", "-of", command[-1]]
        assert Path(command[4]).exists()
        assert kwargs["capture_output"] and kwargs["check"]
        Path(command[-1] + ".json").write_text(json.dumps(document()))
    monkeypatch.setattr(native.subprocess, "run", run)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav", "language": "auto"},
                                     headers=configured)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["contract_version"] == 2 and data["language"] == "en"
    assert data["segments"] == [{"text": "hello", "start_ms": 250, "end_ms": 1500}]
    assert data["words"] == [{"text": " hello", "start_ms": 0, "end_ms": 0,
                              "probability": 0.9, "timing_repaired": True}]
    assert data["engine"] == {"name": "whisper.cpp", "model": native.MODEL_ID, "device": "metal"}
    assert data["diagnostics"]["inverted_words"] == 1
    assert data["diagnostics"]["default_prompt"] is False
    assert set(data["diagnostics"]["stage_ms"]) == {"download", "normalize", "inference"}
    assert set(tmp_path.iterdir()) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "status"), [
    ("normalize_failed", 422), ("no_word_timestamps", 500), ("no_speech", 422), ("engine_failed", 500),
    ("keep_awake_failed", 503), ("download_failed", 500),
])
async def test_failures_are_categorized_private_and_clean(monkeypatch, tmp_path, configured, failure, status):
    before = set(tmp_path.iterdir())
    def fail_no_speech(*args, **kwargs):
        raise native.NoSpeechError("private /path/to/audio sensitive text")
    def fail(*args, **kwargs):
        error = {"normalize_failed": native.NormalizeError, "keep_awake_failed": native.KeepAwakeError}.get(
            failure, RuntimeError)
        raise error("private /path/to/audio sensitive text")
    if failure == "normalize_failed":
        monkeypatch.setattr(native, "normalize_to_wav", fail)
    elif failure == "keep_awake_failed":
        monkeypatch.setattr(native, "KeepAwake", fail)
    elif failure == "download_failed":
        monkeypatch.setattr(native.s3_client, "get_object", fail)
    elif failure == "no_speech":
        monkeypatch.setattr(native, "_transcribe_wav", fail_no_speech)
    elif failure == "no_word_timestamps":
        doc = document()
        doc["transcription"][0]["tokens"] = []
        monkeypatch.setattr(native, "_run_whisper", lambda *args: doc)
    else:
        monkeypatch.setattr(native, "_run_whisper", fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav"}, headers=configured)
    assert response.status_code == status
    assert response.json() == {"detail": "engine_failed" if failure == "download_failed" else failure}
    assert set(tmp_path.iterdir()) == before


@pytest.mark.asyncio
async def test_health_responds_while_inference_runs(monkeypatch, configured):
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(5)
        return document()
    monkeypatch.setattr(native, "_run_whisper", slow)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        pending = asyncio.create_task(client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav"},
                                                  headers=configured))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            response = await asyncio.wait_for(client.get("/health"), timeout=0.5)
            assert response.status_code == 200
            assert not pending.done()
        finally:
            release.set()
            result = await pending
        assert result.status_code == 200


@pytest.mark.asyncio
async def test_transcribe_requires_engine_bearer_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/transcribe", json={"audio_ref": "recordings/a.wav"})
        invalid = await client.post(
            "/transcribe",
            json={"audio_ref": "recordings/a.wav"},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert missing.status_code == 401
    assert invalid.status_code == 401


@pytest.mark.parametrize(
    "audio_ref",
    ["other/private.wav", "recordings/../private.wav", "recordings//private.wav", "recordings\\\\private.wav"],
)
@pytest.mark.asyncio
async def test_transcribe_rejects_audio_refs_outside_configured_prefix(
    audio_ref: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            json={"audio_ref": audio_ref},
            headers={"Authorization": "Bearer synthetic-token"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_returns_503_until_model_is_initialized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    key_path = tmp_path / "recording_capability_key"
    key_path.write_bytes(b"synthetic-capability-secret")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "s3_client", None)
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            json={"audio_ref": "synthetic/file.wav"},
            headers={
                "Authorization": "Bearer synthetic-token",
                "X-Sauri-Recording-Capability": capability(
                    "synthetic/file.wav", b"synthetic-capability-secret", int(time.time()) + 60
                ),
            },
        )
    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("expiry_delta", [-1, 301])
async def test_transcribe_denies_expired_or_overlong_capability_before_io(
    expiry_delta: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = b"synthetic-capability-secret"
    key_path = tmp_path / "capability_key"
    key_path.write_bytes(secret)
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    downloads: list[str] = []
    invocations: list[str] = []

    class RecordingS3:
        def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
            downloads.append(audio_ref)

    def transcribe(path: str, **_kwargs: Any) -> dict[str, Any]:
        invocations.append(path)
        return {"language": "es", "segments": []}

    audio_ref = "recordings/owner-a/recording.wav"
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "_run_whisper", transcribe)
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            json={"audio_ref": audio_ref},
            headers={
                "Authorization": "Bearer synthetic-token",
                "X-Sauri-Recording-Capability": capability(
                    audio_ref, secret, int(time.time()) + expiry_delta
                ),
            },
        )

    assert response.status_code == 403
    assert downloads == []
    assert invocations == []


@pytest.mark.asyncio
async def test_transcribe_denies_capability_for_another_owners_recording_before_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = b"synthetic-capability-secret"
    key_path = tmp_path / "capability_key"
    key_path.write_bytes(secret)
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    downloads: list[str] = []
    invocations: list[str] = []

    class RecordingS3:
        def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
            downloads.append(audio_ref)

    def transcribe(path: str, **_kwargs: Any) -> dict[str, Any]:
        invocations.append(path)
        return {"language": "es", "segments": []}

    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "_run_whisper", transcribe)
    audio_ref = "recordings/owner-b/recording.wav"
    owner_a_capability = capability("recordings/owner-a/recording.wav", secret, int(time.time()) + 60)
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            json={"audio_ref": audio_ref},
            headers={
                "Authorization": "Bearer synthetic-token",
                "X-Sauri-Recording-Capability": owner_a_capability,
            },
        )

    assert response.status_code == 403
    assert downloads == []
    assert invocations == []


@pytest.mark.asyncio
async def test_transcribe_denies_missing_recording_capability_before_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    downloads: list[str] = []
    invocations: list[str] = []

    class RecordingS3:
        def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
            downloads.append(audio_ref)

    def transcribe(path: str, **_kwargs: Any) -> dict[str, Any]:
        invocations.append(path)
        return {"language": "es", "segments": []}

    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "_run_whisper", transcribe)
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            json={"audio_ref": "recordings/owner-a/recording.wav"},
            headers={"Authorization": "Bearer synthetic-token"},
        )

    assert response.status_code == 403
    assert downloads == []
    assert invocations == []


@pytest.mark.parametrize(
    ("bearer_kind", "capability_kind", "expected_status"),
    [
        ("valid", "malformed", 403),
        ("valid", "bad_signature", 403),
        ("invalid", "valid", 401),
    ],
)
@pytest.mark.asyncio
async def test_transcribe_denies_invalid_authorization_before_io(
    bearer_kind: str,
    capability_kind: str,
    expected_status: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = b"synthetic-capability-secret"
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    key_path = tmp_path / "recording_capability_key"
    key_path.write_bytes(secret)
    downloads: list[str] = []
    invocations: list[str] = []
    audio_ref = "recordings/owner-a/recording.wav"
    expires_at = int(time.time()) + 60
    capability_value = (
        "malformed"
        if capability_kind == "malformed"
        else f"{expires_at}.{'0' * 64}"
        if capability_kind == "bad_signature"
        else capability(audio_ref, secret, expires_at)
    )

    class RecordingS3:
        def download_file(self, bucket: str, requested_ref: str, path: str) -> None:
            downloads.append(requested_ref)

    def transcribe(path: str, **_kwargs: Any) -> dict[str, Any]:
        invocations.append(path)
        return {"language": "es", "segments": []}

    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path, raising=False)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "_run_whisper", transcribe)
    bearer = "synthetic-token" if bearer_kind == "valid" else "wrong-token"
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            json={"audio_ref": audio_ref},
            headers={
                "Authorization": f"Bearer {bearer}",
                "X-Sauri-Recording-Capability": capability_value,
            },
        )

    assert response.status_code == expected_status
    assert downloads == []
    assert invocations == []


def test_native_defaults_use_host_minio_and_expected_model() -> None:
    assert native.MINIO_ENDPOINT == "http://localhost:9000"
    assert native.MODEL_ID == "ggml-large-v3-turbo-q5_0"
    assert native.MODEL_DEVICE == "metal"


@pytest.mark.asyncio
async def test_health_reports_ok() -> None:
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_corrupt_audio_uses_real_normalization_and_leaves_no_files(monkeypatch, tmp_path, configured):
    from sauri_engine_common.audio import normalize_to_wav

    monkeypatch.setattr(native, "normalize_to_wav", normalize_to_wav)
    before = set(tmp_path.iterdir())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav"}, headers=configured)
    assert response.status_code == 422
    assert response.json() == {"detail": "normalize_failed"}
    assert set(tmp_path.iterdir()) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(("language", "expected"), [("es-CO", "es"), ("es", "es"), ("auto", "auto")])
async def test_language_hint_is_validated_before_cli(monkeypatch, configured, language, expected):
    def run(command, **kwargs):
        assert command[command.index("-l") + 1] == expected
        Path(command[-1] + ".json").write_text(json.dumps(document()))
    monkeypatch.setattr(native.subprocess, "run", run)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav", "language": language},
                                     headers=configured)
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["spa", "ES", "", "auto-X", "es\n", None, 1])
async def test_invalid_language_returns_safe_422(configured, language):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav", "language": language},
                                     headers=configured)
    assert response.status_code == 422 and response.json() == {"detail": "invalid_language"}


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["spa", "es-CO", "ES", ""])
async def test_startup_rejects_invalid_default_language(monkeypatch, language):
    monkeypatch.setenv("SAURI_DEFAULT_LANGUAGE", language)
    with pytest.raises(ValueError, match="SAURI_DEFAULT_LANGUAGE"):
        async with native.lifespan(native.app):
            pytest.fail("Invalid configuration must not start")


@pytest.mark.asyncio
async def test_startup_rejects_invalid_default_prompt_switch(monkeypatch):
    monkeypatch.setenv("SAURI_ASR_DEFAULT_PROMPT", "maybe")
    with pytest.raises(ValueError, match="SAURI_ASR_DEFAULT_PROMPT"):
        async with native.lifespan(native.app):
            pytest.fail("Invalid configuration must not start")


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [None, "model", "binary", "missing_provenance", "provenance"])
async def test_startup_verifies_assets_once(monkeypatch, tmp_path, tamper):
    from asr_assets import binary_record, load_manifest, provenance_path

    monkeypatch.setenv("SAURI_ASR_VAD", "off")

    model, binary = tmp_path / "model.bin", tmp_path / "whisper-cli"
    model.write_bytes(b"synthetic model")
    binary.write_bytes(b"synthetic binary")
    binary.chmod(0o700)
    manifest = {"asr": {"model_file": "model.bin", "model_size": model.stat().st_size,
                        "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest()}}
    hashes = tmp_path / "hashes.json"
    hashes.write_text(json.dumps(manifest))
    monkeypatch.setenv("SAURI_ENGINE_HASHES_FILE", str(hashes))
    monkeypatch.setenv("SAURI_ASR_VENV", str(tmp_path / "asr-venv"))
    monkeypatch.setenv("MINIO_ROOT_USER", "synthetic-access-key")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "synthetic-secret-key")
    monkeypatch.setattr(native, "ASR_MODEL_PATH", model)
    monkeypatch.setattr(native, "WHISPER_CLI", str(binary))
    path = provenance_path()
    path.parent.mkdir()
    path.write_text(json.dumps(binary_record(binary, load_manifest())))
    if tamper == "model":
        model.write_bytes(b"x" * model.stat().st_size)
    elif tamper == "binary":
        binary.write_bytes(b"tampered binary")
    elif tamper == "missing_provenance":
        path.unlink()
    elif tamper == "provenance":
        path.write_text("{}")
    calls = []
    monkeypatch.setattr(native.boto3, "client", lambda *args, **kwargs: calls.append(True) or FakeS3())
    if tamper:
        with pytest.raises(RuntimeError, match="asset verification failed"):
            async with native.lifespan(native.app):
                pytest.fail("Tampered assets must not start")
        assert calls == []
    else:
        async with native.lifespan(native.app):
            assert calls == [True]
            assert native.s3_client is not None
        assert native.s3_client is None


@pytest.mark.asyncio
async def test_server_budget_covers_lock_wait(monkeypatch, configured):
    monkeypatch.setenv("ASR_TIMEOUT_SECONDS", "0.2")
    native._job_lock.acquire()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav"},
                                                         headers=configured), timeout=0.3)
        assert response.status_code == 504
        assert response.json() == {"detail": "engine_failed"}
    finally:
        native._job_lock.release()


@pytest.mark.asyncio
async def test_normalization_and_inference_share_remaining_budget(monkeypatch, configured):
    monkeypatch.setenv("ASR_TIMEOUT_SECONDS", "3600")
    seen = []
    def normalize(source, dest, timeout_s):
        assert timeout_s == 300
        dest.touch()
        return SimpleNamespace(audio_ms=2000, seconds=0.01)
    def run(command, **kwargs):
        seen.append(kwargs["timeout"])
        assert 0 < kwargs["timeout"] < 3570
        Path(command[-1] + ".json").write_text(json.dumps(document()))
    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    monkeypatch.setattr(native.subprocess, "run", run)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav"}, headers=configured)
    assert response.status_code == 200 and len(seen) == 1


@pytest.mark.asyncio
async def test_download_is_inside_http_budget_and_expired_work_cannot_infer(monkeypatch, tmp_path, configured):
    monkeypatch.setenv("ASR_TIMEOUT_SECONDS", "0.2")
    entered, release = threading.Event(), threading.Event()
    before = set(tmp_path.iterdir())
    original = native.s3_client.get_object
    def slow_download(**kwargs):
        entered.set()
        assert release.wait(2)
        return original(**kwargs)
    def no_inference(*args):
        pytest.fail("Expired download must not reach inference")
    monkeypatch.setattr(native.s3_client, "get_object", slow_download)
    monkeypatch.setattr(native, "_run_whisper", no_inference)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav"},
                                               headers=configured))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            response = await asyncio.wait_for(task, timeout=0.3)
            assert response.status_code == 504 and response.json() == {"detail": "engine_failed"}
        finally:
            release.set()
            assert await asyncio.to_thread(native._job_lock.acquire, timeout=2)
            native._job_lock.release()
    assert set(tmp_path.iterdir()) == before


def test_streaming_download_timeout_closes_body_and_removes_partial_file(monkeypatch, tmp_path):
    body = SyntheticBody(b"partial")
    reads = []
    original = body.read
    def read(count):
        reads.append(count)
        if len(reads) == 2:
            raise TimeoutError("private audio path")
        return original(count)
    monkeypatch.setattr(body, "read", read)
    monkeypatch.setattr(native, "s3_client", SimpleNamespace(get_object=lambda **kwargs: {"Body": body}))
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(RuntimeError, match="Audio download failed"):
        native._download_audio("recordings/synthetic.wav", time.monotonic() + 1)
    assert body.closed and len(reads) == 2
    assert list(tmp_path.iterdir()) == []


def test_missing_vocabulary(tmp_path):
    assert native.vocabulary_prompt(tmp_path / "missing") is None


@pytest.mark.parametrize("content", ["", " \n\t\n", "\x00\n"])
def test_empty_vocabulary(tmp_path, content):
    path = tmp_path / "vocabulary.txt"
    path.write_text(content)
    assert native.vocabulary_prompt(path) is None


def test_prompt_keeps_whole_terms_in_order_and_deduplicates(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("Zorvex\n\n  Veltra  Labs \nZorvex\n" + "x" * 300 + "\nNuvexa\n")
    assert native.vocabulary_prompt(path) == "Hola. Estos son los nombres propios: Zorvex, Veltra Labs, Nuvexa."


def test_prompt_budget_counts_utf8_and_keeps_complete_entries(tmp_path):
    path = tmp_path / "vocabulary.txt"
    terms = [f"\u754c\u754c{index}" for index in range(100)]
    path.write_text("\n".join(terms))
    prompt = native.vocabulary_prompt(path)
    assert prompt is not None
    assert len(prompt.encode("utf-8")) <= 224
    included = prompt.split(": ", 1)[1][:-1].split(", ")
    assert included == terms[:len(included)]
    assert len((prompt[:-1] + ", " + terms[len(included)] + ".").encode("utf-8")) > 224


@pytest.mark.parametrize("custom_path", [False, True])
def test_run_whisper_reads_default_or_override_vocabulary(monkeypatch, tmp_path, custom_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SAURI_ASR_VOCABULARY_FILE", raising=False)
    path = tmp_path / ".config/sauri/vocabulary.txt"
    if custom_path:
        path = tmp_path / "custom.txt"
        monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Zorvex\nVeltra\n")
    output = tmp_path / "output"
    def run(command, **kwargs):
        assert command[command.index("--prompt") + 1] == native.vocabulary_prompt(path)
        assert "--carry-initial-prompt" in command
        assert "-ojf" in command and "-fa" in command
        assert kwargs == {"check": True, "capture_output": True, "timeout": 12}
        output.with_suffix(".json").write_text(json.dumps({"transcription": []}))
    monkeypatch.setattr(native.subprocess, "run", run)
    assert native._run_whisper(tmp_path / "audio.wav", output, "es", 12) == {"transcription": []}


DEFAULT_PROMPT = "Buenos d\u00edas. Empecemos."


@pytest.mark.parametrize("content", [None, "", " \n"])
@pytest.mark.parametrize("language", ["es", "es-ES"])
def test_default_prompt_without_terms_for_spanish(monkeypatch, tmp_path, content, language):
    path = tmp_path / "vocabulary.txt"
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(path))
    monkeypatch.delenv("SAURI_ASR_DEFAULT_PROMPT", raising=False)
    if content is not None:
        path.write_text(content)
    output = tmp_path / "output"
    def run(command, **kwargs):
        assert native.DEFAULT_PROMPT == DEFAULT_PROMPT
        assert command[command.index("--prompt") + 1] == DEFAULT_PROMPT
        assert command.count("--carry-initial-prompt") == 1
        assert command.index("--carry-initial-prompt") == command.index("--prompt") + 2
        output.with_suffix(".json").write_text(json.dumps({"transcription": []}))
    monkeypatch.setattr(native.subprocess, "run", run)
    native._run_whisper(tmp_path / "audio.wav", output, language, 12)


@pytest.mark.parametrize(("language", "setting"), [
    ("auto", None), ("en", None), ("fr", None), ("es", "off"),
])
def test_no_prompt_flags_for_other_languages_or_when_disabled(monkeypatch, tmp_path, language, setting):
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(tmp_path / "absent"))
    monkeypatch.delenv("SAURI_ASR_DEFAULT_PROMPT", raising=False)
    if setting:
        monkeypatch.setenv("SAURI_ASR_DEFAULT_PROMPT", setting)
    output = tmp_path / "output"
    def run(command, **kwargs):
        assert "--prompt" not in command and "--carry-initial-prompt" not in command
        output.with_suffix(".json").write_text(json.dumps({"transcription": []}))
    monkeypatch.setattr(native.subprocess, "run", run)
    native._run_whisper(tmp_path / "audio.wav", output, language, 12)


@pytest.mark.parametrize("setting", [None, "off"])
def test_vocabulary_prompt_wins_over_default_and_switch(monkeypatch, tmp_path, setting):
    path = tmp_path / "vocabulary.txt"
    path.write_text("Zorvex\n")
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(path))
    monkeypatch.delenv("SAURI_ASR_DEFAULT_PROMPT", raising=False)
    if setting:
        monkeypatch.setenv("SAURI_ASR_DEFAULT_PROMPT", setting)
    assert native._initial_prompt("es") == (native.vocabulary_prompt(path), False)
    assert native._initial_prompt("en") == (native.vocabulary_prompt(path), False)


def test_diagnostic_tail_is_bounded_and_private():
    safe = "ggml_metal_buffer_init: error: failed to allocate buffer, size =     7.33 MiB"
    stderr = "\n".join([safe] * 20 + [
        "[00:00:00.000 --> 00:00:01.000] private utterance",
        "error: failed to read audio file '/Users/private/audio.wav'",
        "whisper_full: prompt = private glossary",
        "error: arbitrary private content",
        "error: failed to initialize whisper context private suffix",
        "\x1b[31mprivate terminal escape\x1b[0m",
        safe,
    ])
    result = native.diagnostic_tail(stderr.encode() + b"\n\xff")
    assert len(result) <= 600
    assert safe in result
    assert "error: failed to read audio file [redacted]" in result
    for secret in ["private", "/Users", "utterance", "glossary", "\x1b", "\ufffd"]:
        assert secret not in result
    assert native.diagnostic_tail(None) == "[no stderr]"
    assert native.diagnostic_tail("") == "[no stderr]"
    long_tail = native.diagnostic_tail("error: failed to initialize whisper context\n" + (safe + "\n") * 10)
    assert len(long_tail) == 600
    assert "initialize whisper context" not in long_tail


@pytest.mark.asyncio
async def test_failing_cli_logs_safe_tail_and_preserves_http_contract(
    monkeypatch, tmp_path, configured, caplog,
):
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(tmp_path / "absent"))
    # Run a real subprocess, replacing only the CLI executable with a synthetic failure.
    executable = tmp_path / "whisper-fail"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "print('private transcript on stdout')\n"
        "print('private transcript on stderr', file=sys.stderr)\n"
        "print(\"error: failed to read audio file '/Users/private/recording.wav'\", file=sys.stderr)\n"
        "print('ggml_metal_buffer_init: error: failed to allocate buffer, size =     7.33 MiB', file=sys.stderr)\n"
        "sys.exit(17)\n"
    )
    executable.chmod(0o700)
    monkeypatch.setattr(native, "WHISPER_CLI", str(executable))
    before = set(tmp_path.iterdir())
    with caplog.at_level(logging.ERROR, logger=native.logger.name):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
            response = await client.post("/transcribe", json={"audio_ref": "synthetic/recording.wav"},
                                         headers=configured)
    assert response.status_code == 500
    assert response.json() == {"detail": "engine_failed"}
    assert "exit_code=17" in caplog.text
    assert "failed to allocate buffer" in caplog.text
    assert "private" not in caplog.text and "/Users/" not in caplog.text
    assert "private" not in response.text
    assert set(tmp_path.iterdir()) == before
