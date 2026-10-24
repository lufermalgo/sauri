"""Protective tests for the standalone ASR service's failure cleanup."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

_SERVICE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "main.py"
_SERVICE_NAME = "sauri_asr_engine_main_under_test"


def _load_service() -> Any:
    """Load the standalone service without requiring its heavyweight model wheel."""
    if (
        "faster_whisper" not in sys.modules
        and importlib.util.find_spec("faster_whisper") is None
    ):
        faster_whisper_stub = types.ModuleType("faster_whisper")
        faster_whisper_stub.__dict__["WhisperModel"] = type("WhisperModel", (), {})
        sys.modules["faster_whisper"] = faster_whisper_stub

    spec = importlib.util.spec_from_file_location(_SERVICE_NAME, _SERVICE_PATH)
    assert spec is not None and spec.loader is not None
    service = importlib.util.module_from_spec(spec)
    sys.modules[_SERVICE_NAME] = service
    spec.loader.exec_module(service)
    return service


service = _load_service()


def test_failed_s3_download_removes_partial_file_and_chains_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed object-store download cleans its temporary file and preserves cause."""
    downloaded_paths: list[Path] = []

    class FailingS3:
        def download_file(self, bucket: str, key: str, filename: str) -> None:
            assert bucket == service.MINIO_BUCKET
            assert key == "synthetic/recording.wav"
            path = Path(filename)
            path.write_bytes(b"synthetic partial recording")
            downloaded_paths.append(path)
            raise OSError("synthetic object-store failure")

    monkeypatch.setattr(service, "s3_client", FailingS3())

    with pytest.raises(RuntimeError, match="Failed to download") as exc_info:
        service._download_audio_from_s3("synthetic/recording.wav")

    assert isinstance(exc_info.value.__cause__, OSError)
    assert len(downloaded_paths) == 1
    assert not downloaded_paths[0].exists()


def test_transcription_failure_returns_500_and_removes_audio_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A model failure becomes HTTP 500 and still removes the downloaded file."""
    audio_path = tmp_path / "synthetic-recording.wav"
    audio_path.write_bytes(b"synthetic audio")

    class FailingModel:
        def transcribe(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("synthetic model failure")

    monkeypatch.setattr(service, "whisper_model", FailingModel())
    monkeypatch.setattr(service, "_download_audio_from_s3", lambda _ref: str(audio_path))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.transcribe(service.TranscribeRequest(audio_ref="synthetic/ref")))

    assert exc_info.value.status_code == 500
    assert not audio_path.exists()
