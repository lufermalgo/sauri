"""Synthetic HTTP contract tests for the host-native ASR engine."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "native_main.py"
MODULE_SPEC = importlib.util.spec_from_file_location("native_asr_engine", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
native = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(native)


class FakeS3:
    def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
        assert bucket == "synthetic-bucket"
        assert audio_ref == "synthetic/recording.wav"
        Path(path).write_bytes(b"synthetic audio")


@pytest.mark.asyncio
async def test_transcribe_preserves_response_contract_and_cleans_temp_file(
    monkeypatch: pytest.MonkeyPatch,
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

    monkeypatch.setattr(native, "s3_client", FakeS3())
    monkeypatch.setattr(native, "transcribe_audio", transcribe)
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")

    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/transcribe", json={"audio_ref": "synthetic/recording.wav", "language": "es-CO"}
        )

    assert response.status_code == 200
    assert response.json() == {
        "segments": [{"text": "hola", "start_ms": 250, "end_ms": 1500}],
        "language": "es",
    }
    assert observed_path and not Path(observed_path[0]).exists()


@pytest.mark.asyncio
async def test_transcribe_returns_503_until_model_is_initialized() -> None:
    native.transcribe_audio = None
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_ref": "synthetic.wav"})
    assert response.status_code == 503


def test_native_defaults_use_host_minio_and_expected_model() -> None:
    assert native.MINIO_ENDPOINT == "http://localhost:9000"
    assert native.MODEL_ID == "mlx-community/whisper-large-v3-turbo"
    assert native.MODEL_DEVICE == "mlx"
