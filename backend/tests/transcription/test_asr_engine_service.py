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
sys.path.insert(0, str(_SERVICE_PATH.parent))
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


@pytest.mark.parametrize("language", ["auto", "es", "en-US"])
def test_container_returns_words_and_v2_metadata(monkeypatch, tmp_path, language):
    from types import SimpleNamespace

    audio = tmp_path / "synthetic.wav"
    audio.touch()
    word = SimpleNamespace(word=" synthetic", start=0.1, end=0.5, probability=0.9)
    segment = SimpleNamespace(text="synthetic", start=0.1, end=0.5, words=[word])

    class Model:
        model = SimpleNamespace(device="cpu")

        def transcribe(self, path, **kwargs):
            assert kwargs["word_timestamps"] is True
            assert kwargs["language"] == {"auto": None, "es": "es", "en-US": "en"}[language]
            return iter([segment]), SimpleNamespace(language="en", duration=1)

    monkeypatch.setattr(service, "whisper_model", Model())
    monkeypatch.setattr(service, "_download_audio_from_s3", lambda _: str(audio))
    result = asyncio.run(service.transcribe(service.TranscribeRequest(audio_ref="synthetic/ref", language=language)))
    assert result.contract_version == 2 and result.language == "en"
    assert result.words[0].model_dump() == {
        "text": " synthetic", "start_ms": 100, "end_ms": 500, "probability": 0.9, "timing_repaired": False,
    }
    assert result.engine.model_dump() == {"name": "faster-whisper", "model": service.ASR_MODEL, "device": "cpu"}
    assert not audio.exists()


def test_container_repairs_word_timing_with_shared_rule(monkeypatch, tmp_path):
    from types import SimpleNamespace

    audio = tmp_path / "synthetic.wav"
    audio.touch()
    words = [SimpleNamespace(word=" word", start=start, end=end, probability=0.9)
             for start, end in [(0.1, 0.4), (0.9, 0.5), (-0.1, 0.2), (0.9, 1.5)]]

    class Model:
        model = SimpleNamespace(device="cpu")

        def transcribe(self, path, **kwargs):
            return iter([SimpleNamespace(text=" words ", start=0, end=1, words=words)]), SimpleNamespace(
                language="en", duration=1)

    monkeypatch.setattr(service, "whisper_model", Model())
    monkeypatch.setattr(service, "_download_audio_from_s3", lambda _: str(audio))
    result = asyncio.run(service.transcribe(service.TranscribeRequest(audio_ref="synthetic/ref")))
    assert [(w.start_ms, w.end_ms, w.timing_repaired) for w in result.words] == [
        (100, 400, False), (400, 400, True), (400, 400, True), (900, 1000, False),
    ]
    assert all(w.text == " word" for w in result.words)
    assert result.segments[0].text == "words"
    from app.diarization.word_attribution import WordAttribution, WordTime, group_words_into_turns

    timed = [WordTime(i, w.text, w.start_ms, w.end_ms) for i, w in enumerate(result.words)]
    assigned = [WordAttribution(i, "speaker", "assigned", ()) for i in range(len(timed))]
    turns = group_words_into_turns(timed, assigned)
    assert turns[0].text.strip() == "word word word word"
    assert result.diagnostics["inverted_words"] == 2
    assert not audio.exists()
