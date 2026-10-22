"""Synthetic HTTP contract tests for the host-native diarization engine."""

from __future__ import annotations

import importlib.util
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
        Path(path).write_bytes(b"synthetic audio")


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
