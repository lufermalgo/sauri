"""Synthetic HTTP contract tests for the host-native diarization engine."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "diar-engine" / "native_main.py"
MODULE_SPEC = importlib.util.spec_from_file_location("native_diar_engine", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
native = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = native
MODULE_SPEC.loader.exec_module(native)


class FakeS3:
    def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
        assert bucket == "synthetic-bucket"
        assert audio_ref == "synthetic/recording.wav"
        Path(path).write_bytes(_minimal_wav_bytes())


class WebMS3:
    """Writes opaque synthetic WebM data for the mocked ffmpeg boundary."""

    def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
        assert bucket == "synthetic-bucket"
        assert audio_ref == "synthetic/recording.webm"
        Path(path).write_bytes(b"synthetic-webm-container")


def _minimal_wav_bytes() -> bytes:
    """Build a tiny valid 16 kHz mono 16-bit PCM WAV (silence) that ffmpeg can read."""
    import struct

    sample_rate = 16000
    num_samples = 160
    byte_rate = sample_rate * 2  # 1 channel, 16-bit
    data = b"\x00\x00" * num_samples
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(data),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        1,  # channels
        sample_rate,
        byte_rate,
        2,  # block align
        16,  # bits per sample
        b"data",
        len(data),
    )
    return header + data


def capability(audio_ref: str, secret: bytes, expires_at: int) -> str:
    message = f"{audio_ref}\n{expires_at}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"


def fake_result() -> dict[str, Any]:
    return {
        "raw_segments": [{"start": 0.5, "end": 2.25, "speaker": "SPEAKER_00"}],
        "merged_segments": [],
    }


@pytest.mark.asyncio
async def test_diarize_preserves_contract_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen_paths: list[str] = []

    def run_pipeline(path: str) -> dict[str, Any]:
        seen_paths.append(path)
        return fake_result()

    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    capability_key_path = tmp_path / "recording_capability_key"
    secret = b"synthetic-capability-secret"
    capability_key_path.write_bytes(secret)
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", capability_key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "s3_client", FakeS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(
        diarize=lambda *, wav_path, accurate, generate_colors: run_pipeline(wav_path)
    ))
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")

    def fake_ffmpeg(command: list[str], **_options: Any) -> None:
        Path(command[-1]).write_bytes(_minimal_wav_bytes())

    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)

    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
            json={"audio_ref": "synthetic/recording.wav"},
            headers={
                "Authorization": "Bearer synthetic-token",
                "X-Sauri-Recording-Capability": capability(
                    "synthetic/recording.wav", secret, int(time.time()) + 60
                ),
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["segments"] == [{"speaker": "SPEAKER_00", "start_ms": 500, "end_ms": 2250}]
    assert data["speaker_count"] == 1
    assert data["contract_version"] == 2
    assert data["engine"] == {"name": "senko", "model": "senko-coreml", "device": "coreml"}
    assert data["diagnostics"]["audio_ms"] == 10
    assert seen_paths and not Path(seen_paths[0]).exists()


@pytest.mark.asyncio
async def test_diarize_converts_webm_to_wav_before_senko(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A downloaded .webm must reach Senko as a 16 kHz mono WAV file."""
    seen_paths: list[str] = []

    def run_pipeline(path: str) -> dict[str, Any]:
        seen_paths.append(path)
        assert Path(path).suffix == ".wav", f"expected WAV input, got {path!r}"
        return fake_result()

    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    secret = b"synthetic-capability-secret"
    key_path = tmp_path / "recording_capability_key"
    key_path.write_bytes(secret)
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "s3_client", WebMS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(
        diarize=lambda *, wav_path, accurate, generate_colors: run_pipeline(wav_path)
    ))
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    ffmpeg_calls: list[list[str]] = []

    def fake_ffmpeg(command: list[str], **options: Any) -> None:
        ffmpeg_calls.append(command)
        assert options == {
            "check": True,
            "capture_output": True,
            "timeout": 300,
        }
        Path(command[-1]).write_bytes(_minimal_wav_bytes())

    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)

    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
            json={"audio_ref": "synthetic/recording.webm"},
            headers={
                "Authorization": "Bearer synthetic-token",
                "X-Sauri-Recording-Capability": capability(
                    "synthetic/recording.webm", secret, int(time.time()) + 60
                ),
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["segments"] == [{"speaker": "SPEAKER_00", "start_ms": 500, "end_ms": 2250}]
    assert data["speaker_count"] == 1
    assert data["contract_version"] == 2
    assert data["engine"] == {"name": "senko", "model": "senko-coreml", "device": "coreml"}
    assert data["diagnostics"]["audio_ms"] == 10
    assert len(ffmpeg_calls) == 1
    command = ffmpeg_calls[0]
    assert command[:6] == ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i"]
    assert command[6].endswith(".webm")
    assert command[7:-1] == ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
    assert command[-1].endswith(".wav")
    assert len(seen_paths) == 1
    assert seen_paths[0].endswith(".wav"), f"Senko received non-WAV: {seen_paths[0]!r}"
    assert not Path(seen_paths[0]).exists(), "converted temp WAV must be cleaned up"


@pytest.mark.asyncio
async def test_diarize_requires_engine_bearer_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/diarize", json={"audio_ref": "recordings/a.wav"})
        invalid = await client.post(
            "/diarize",
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
async def test_diarize_rejects_audio_refs_outside_configured_prefix(
    audio_ref: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
            json={"audio_ref": audio_ref},
            headers={"Authorization": "Bearer synthetic-token"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("expiry_delta", [-1, 360])
async def test_diarize_denies_expired_or_overlong_capability_before_io(
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

    class EmptyAnnotation:
        def itertracks(self, yield_label: bool = False) -> Any:
            assert yield_label
            return iter(())

    def run_pipeline(path: str) -> EmptyAnnotation:
        invocations.append(path)
        return EmptyAnnotation()

    audio_ref = "recordings/owner-a/recording.wav"
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(
        diarize=lambda *, wav_path, accurate, generate_colors: run_pipeline(wav_path)
    ))
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
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
async def test_diarize_denies_capability_for_another_owners_recording_before_io(
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

    class EmptyAnnotation:
        def itertracks(self, yield_label: bool = False) -> Any:
            assert yield_label
            return iter(())

    def run_pipeline(path: str) -> EmptyAnnotation:
        invocations.append(path)
        return EmptyAnnotation()

    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(
        diarize=lambda *, wav_path, accurate, generate_colors: run_pipeline(wav_path)
    ))
    audio_ref = "recordings/owner-b/recording.wav"
    owner_a_capability = capability("recordings/owner-a/recording.wav", secret, int(time.time()) + 60)
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
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
async def test_diarize_denies_missing_recording_capability_before_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    downloads: list[str] = []
    invocations: list[str] = []

    class RecordingS3:
        def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
            downloads.append(audio_ref)
            Path(path).write_bytes(_minimal_wav_bytes())

    class EmptyAnnotation:
        def itertracks(self, yield_label: bool = False) -> Any:
            assert yield_label
            return iter(())

    def run_pipeline(path: str) -> EmptyAnnotation:
        invocations.append(path)
        return EmptyAnnotation()

    def fake_ffmpeg(command: list[str], **_options: Any) -> None:
        Path(command[-1]).write_bytes(_minimal_wav_bytes())

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(
        diarize=lambda *, wav_path, accurate, generate_colors: run_pipeline(wav_path)
    ))
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
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
async def test_diarize_denies_invalid_authorization_before_io(
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
            Path(path).write_bytes(_minimal_wav_bytes())

    class EmptyAnnotation:
        def itertracks(self, yield_label: bool = False) -> Any:
            assert yield_label
            return iter(())

    def run_pipeline(path: str) -> EmptyAnnotation:
        invocations.append(path)
        return EmptyAnnotation()

    def fake_ffmpeg(command: list[str], **_options: Any) -> None:
        Path(command[-1]).write_bytes(_minimal_wav_bytes())

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path, raising=False)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "recordings/")
    monkeypatch.setattr(native, "s3_client", RecordingS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(
        diarize=lambda *, wav_path, accurate, generate_colors: run_pipeline(wav_path)
    ))
    bearer = "synthetic-token" if bearer_kind == "valid" else "wrong-token"
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
            json={"audio_ref": audio_ref},
            headers={
                "Authorization": f"Bearer {bearer}",
                "X-Sauri-Recording-Capability": capability_value,
            },
        )

    assert response.status_code == expected_status
    assert downloads == []
    assert invocations == []


def test_native_defaults_configure_coreml() -> None:
    assert native.MINIO_ENDPOINT == "http://localhost:9000"
    assert native.MODEL_ID == "senko-coreml"
    assert native.MODEL_DEVICE == "coreml"


@pytest.mark.asyncio
async def test_health_reports_ok() -> None:
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_raw_segments_keep_short_turns_and_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    def infer(**kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"wav_path": "synthetic.wav", "accurate": True, "generate_colors": False}
        return {
            "raw_segments": [{"speaker": "brief", "start": 1.1, "end": 1.25},
                             {"speaker": "first", "start": 0.0, "end": 1.0}],
            "merged_segments": [{"speaker": "first", "start": 0.0, "end": 1.25}],
        }
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(diarize=infer))
    segments, dropped = native._run_diarization("synthetic.wav")
    assert dropped == 0
    assert [(s.speaker, s.start_ms, s.end_ms) for s in segments] == [
        ("first", 0, 1000), ("brief", 1100, 1250),
    ]


@pytest.mark.asyncio
async def test_startup_uses_exact_coreml_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    vad = SimpleNamespace(lib=Mock(), processor=object())
    pipeline = SimpleNamespace(vad_processor_pyannote_coreml=vad)
    constructor = Mock(return_value=pipeline)
    monkeypatch.setitem(sys.modules, "senko", SimpleNamespace(Diarizer=constructor))
    monkeypatch.setenv("MINIO_ROOT_USER", "synthetic-access-key")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "synthetic-secret-key")
    monkeypatch.setattr(native.boto3, "client", Mock())
    async with native.lifespan(native.app):
        assert native.diarization_pipeline is pipeline
        constructor.assert_called_once_with(
            device="coreml", vad="pyannote", clustering="cpu", warmup=True, quiet=True,
        )
        vad.lib.vad_set_min_duration_on.assert_called_once_with(vad.processor, 0.0)
        vad.lib.vad_set_min_duration_off.assert_called_once_with(vad.processor, 0.0)
    assert native.diarization_pipeline is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["download", "normalize", "inference"])
async def test_failures_remove_all_temporaries(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from fastapi import HTTPException

    paths: list[Path] = []
    secret = b"synthetic-secret"
    key = tmp_path / "key"
    key.write_bytes(secret)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key)

    class Store:
        def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
            paths.extend([Path(path), Path(path + ".wav")])
            Path(path).write_bytes(b"bad" if failure == "normalize" else _minimal_wav_bytes())
            if failure == "download":
                raise OSError("synthetic download error")

    def infer(**kwargs: Any) -> None:
        assert paths[1].exists()
        raise RuntimeError("synthetic inference error")

    monkeypatch.setattr(native, "s3_client", Store())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(diarize=infer))
    audio_ref = "recordings/synthetic.wav"
    with pytest.raises(HTTPException) as error:
        await native.diarize(
            native.DiarizeRequest(audio_ref=audio_ref),
            None,  # no HTTP request object: the local path never reads it
            recording_capability=capability(audio_ref, secret, int(time.time()) + 60),
            route=None,
        )
    assert error.value.status_code == (422 if failure == "normalize" else 500)
    if failure == "normalize":
        assert error.value.detail == "normalize_failed"
    assert paths and all(not path.exists() for path in paths)


def test_no_voice_is_valid_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    # The pinned Senko implementation returns None when VAD finds no voice.
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(diarize=lambda **kwargs: None))
    assert native._run_diarization("synthetic-silence.wav") == ([], 0)


@pytest.fixture
def synthetic_client(monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    monkeypatch.setitem(native.app.dependency_overrides, native._require_engine_token, lambda: None)
    monkeypatch.setattr(native, "_require_recording_capability", lambda *_args: None)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native, "s3_client", FakeS3())
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(diarize=lambda **kwargs: None))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test")


async def test_rounds_times_and_reports_only_invalid_segments_as_dropped(
    synthetic_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = [
        {"speaker": "brief", "start": 1.005, "end": 1.006},
        {"speaker": "inverted", "start": 2.0, "end": 1.0},
        {"speaker": "collapsed", "start": 3.0001, "end": 3.0002},
    ]
    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(diarize=lambda **kwargs: {"raw_segments": raw}))
    async with synthetic_client as client:
        response = await client.post("/diarize", json={"audio_ref": "synthetic/recording.wav"})
    assert response.status_code == 200
    data = response.json()
    assert data["segments"] == [{"speaker": "brief", "start_ms": 1005, "end_ms": 1006}]
    assert data["diagnostics"]["dropped_segments"] == 2
    assert data["speaker_count"] == 1


async def test_caffeinate_failure_is_categorized(
    synthetic_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    monkeypatch.setattr(sys, "platform", "darwin")
    launch = Mock(side_effect=OSError("synthetic launch failure"))
    download = Mock()
    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(native, "_download_audio", download)
    async with synthetic_client as client:
        response = await client.post("/diarize", json={"audio_ref": "synthetic/recording.wav"})
    assert response.status_code == 503
    assert response.json() == {"detail": "keep_awake_failed"}
    download.assert_not_called()


async def test_health_responds_during_slow_diarization(
    synthetic_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import threading

    started, release = threading.Event(), threading.Event()

    def infer(**kwargs: Any) -> None:
        started.set()
        release.wait(timeout=3)

    monkeypatch.setattr(native, "diarization_pipeline", SimpleNamespace(diarize=infer))
    async with synthetic_client as client:
        pending = asyncio.create_task(client.post("/diarize", json={"audio_ref": "synthetic/recording.wav"}))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            response = await asyncio.wait_for(client.get("/health"), timeout=1)
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            assert not pending.done()
        finally:
            release.set()
            result = await pending
        assert result.status_code == 200
