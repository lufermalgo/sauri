"""Synthetic HTTP contract tests for the host-native ASR engine."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "native_main.py"
MODULE_SPEC = importlib.util.spec_from_file_location("native_asr_engine", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
native = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = native
MODULE_SPEC.loader.exec_module(native)


class FakeS3:
    def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
        assert bucket == "synthetic-bucket"
        assert audio_ref == "synthetic/recording.wav"
        Path(path).write_bytes(b"synthetic audio")


def capability(audio_ref: str, secret: bytes, expires_at: int) -> str:
    message = f"{audio_ref}\n{expires_at}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


@pytest.mark.asyncio
async def test_transcribe_preserves_response_contract_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed_path: list[str] = []

    def transcribe(path: str, **kwargs: Any) -> dict[str, Any]:
        observed_path.append(path)
        assert kwargs["path_or_hf_repo"] == "mlx-community/whisper-large-v3-turbo"
        assert kwargs["language"] == "es"
        return {
            "language": "es",
            "segments": [
                {"text": " hola ", "start": 0.25, "end": 1.5},
                {"text": " ", "start": 1.5, "end": 2.0},
            ],
        }

    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    capability_key_path = tmp_path / "recording_capability_key"
    secret = b"synthetic-capability-secret"
    capability_key_path.write_bytes(secret)
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", capability_key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "s3_client", FakeS3())
    monkeypatch.setattr(native, "transcribe_audio", transcribe)
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")

    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            json={"audio_ref": "synthetic/recording.wav", "language": "es-CO"},
            headers={
                "Authorization": "Bearer synthetic-token",
                "X-Sauri-Recording-Capability": capability(
                    "synthetic/recording.wav", secret, int(time.time()) + 60
                ),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "segments": [{"text": "hola", "start_ms": 250, "end_ms": 1500}],
        "language": "es",
    }
    assert observed_path and not Path(observed_path[0]).exists()


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
    monkeypatch.setattr(native, "transcribe_audio", None)
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
    monkeypatch.setattr(native, "transcribe_audio", transcribe)
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
    monkeypatch.setattr(native, "transcribe_audio", transcribe)
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
    monkeypatch.setattr(native, "transcribe_audio", transcribe)
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
    monkeypatch.setattr(native, "transcribe_audio", transcribe)
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
    assert native.MODEL_ID == "mlx-community/whisper-large-v3-turbo"
    assert native.MODEL_DEVICE == "mlx"


@pytest.mark.asyncio
async def test_health_reports_ok() -> None:
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
