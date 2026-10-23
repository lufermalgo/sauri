"""Synthetic HTTP contract tests for the host-native diarization engine."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
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


class FakeTurn:
    start = 0.5
    end = 2.25


class FakeAnnotation:
    def itertracks(self, yield_label: bool = False) -> Any:
        assert yield_label
        yield FakeTurn(), None, "SPEAKER_00"


@pytest.mark.asyncio
async def test_diarize_preserves_contract_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen_paths: list[str] = []

    def run_pipeline(path: str) -> FakeAnnotation:
        seen_paths.append(path)
        return FakeAnnotation()

    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "s3_client", FakeS3())
    monkeypatch.setattr(native, "diarization_pipeline", run_pipeline)
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
            headers={"Authorization": "Bearer synthetic-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "segments": [{"speaker": "SPEAKER_00", "start_ms": 500, "end_ms": 2250}],
        "num_speakers": 1,
    }
    assert seen_paths and not Path(seen_paths[0]).exists()


@pytest.mark.asyncio
async def test_diarize_converts_webm_to_wav_before_pyannote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A downloaded .webm must reach pyannote as a 16 kHz mono WAV file."""
    seen_paths: list[str] = []

    def run_pipeline(path: str) -> FakeAnnotation:
        seen_paths.append(path)
        assert Path(path).suffix == ".wav", f"expected WAV input, got {path!r}"
        return FakeAnnotation()

    token_path = tmp_path / "engine_token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "s3_client", WebMS3())
    monkeypatch.setattr(native, "diarization_pipeline", run_pipeline)
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    ffmpeg_calls: list[list[str]] = []

    def fake_ffmpeg(command: list[str], **options: Any) -> None:
        ffmpeg_calls.append(command)
        assert options == {
            "check": True,
            "capture_output": True,
            "timeout": native.FFMPEG_TIMEOUT_SECONDS,
        }
        Path(command[-1]).write_bytes(_minimal_wav_bytes())

    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)

    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/diarize",
            json={"audio_ref": "synthetic/recording.webm"},
            headers={"Authorization": "Bearer synthetic-token"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "segments": [{"speaker": "SPEAKER_00", "start_ms": 500, "end_ms": 2250}],
        "num_speakers": 1,
    }
    assert len(ffmpeg_calls) == 1
    command = ffmpeg_calls[0]
    assert command[1:3] == ["-y", "-v"]
    assert command[3] == "error"
    assert command[4] == "-i"
    assert command[5].endswith(".webm")
    assert command[6:11] == ["-ar", "16000", "-ac", "1", "-c:a"]
    assert command[11] == "pcm_s16le"
    assert command[-1].endswith(".wav")
    assert len(seen_paths) == 1
    assert seen_paths[0].endswith(".wav"), f"pyannote received non-WAV: {seen_paths[0]!r}"
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


def test_native_defaults_configure_mps_and_private_token_path() -> None:
    assert native.MINIO_ENDPOINT == "http://localhost:9000"
    assert native.MODEL_ID == "pyannote/speaker-diarization-3.1"
    assert native.MODEL_DEVICE == "mps"
    assert Path.home() / ".config" / "sauri" / "hf_token" == native.HF_TOKEN_PATH


@pytest.mark.asyncio
async def test_health_reports_ok() -> None:
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
