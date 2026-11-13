"""Synthetic regressions for #880: admission, exact words and original offsets."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_acoustic_asr", Path(__file__).resolve().parents[2] / "asr-engine/native_main.py"
)
assert SPEC and SPEC.loader
native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)


async def execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    segments: list[dict[str, Any]],
    activity: list[tuple[int, int]] | None,
) -> Any:
    path = tmp_path / "source.wav"
    path.write_bytes(b"synthetic")
    monkeypatch.setattr(native, "_require_recording_capability", lambda *_: None)
    monkeypatch.setattr(native, "_download_audio", lambda _: str(path))
    monkeypatch.setattr(native, "ACOUSTIC_VALIDATION_ENABLED", True, raising=False)
    monkeypatch.setattr(native, "_detect_speech", lambda _: (str(path), activity, 10000), raising=False)
    monkeypatch.setattr(native, "transcribe_audio", lambda *_, **__: {"segments": segments})
    result = await native.transcribe(
        native.TranscribeRequest(audio_ref="recordings/test.wav"), recording_capability="synthetic"
    )
    assert not path.exists()
    return result.segments


@pytest.mark.asyncio
async def test_word_boundaries_survive_before_first_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = await execute(
        monkeypatch,
        tmp_path,
        [
            {
                "text": " Hola. Good day. ",
                "start": 2.0,
                "end": 3.0,
                "words": [
                    {"word": " Hola.", "start": 2.0, "end": 2.6},
                    {"word": " Good", "start": 2.6, "end": 2.8},
                    {"word": " day. ", "start": 2.8, "end": 3.0},
                ],
            }
        ],
        [(2000, 3000)],
    )
    assert [(s.text, s.start_ms, s.end_ms) for s in result] == [
        ("Hola.", 2000, 2600),
        (" Good", 2600, 2800),
        (" day.", 2800, 3000),
    ]
    assert "".join(s.text for s in result) == "Hola. Good day."


@pytest.mark.asyncio
@pytest.mark.parametrize("start", [0, 5])
@pytest.mark.parametrize("score", [0.9, 1.0226965801996002e-10])
async def test_verified_non_speech_is_not_published(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, start: int, score: float
) -> None:
    result = await execute(
        monkeypatch,
        tmp_path,
        [
            {
                "text": "texto de prueba",
                "start": start,
                "end": start + 0.8,
                "no_speech_prob": score,
                "avg_logprob": -0.01,
            }
        ],
        [],
    )
    assert result == []


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [None, 0.1])
async def test_brief_weak_or_unavailable_evidence_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    score: float | None,
) -> None:
    result = await execute(
        monkeypatch,
        tmp_path,
        [
            {
                "text": "Hola.",
                "start": 0.0,
                "end": 0.2,
                "no_speech_prob": score,
            }
        ],
        None if score is None else [(0, 200)],
    )
    assert [(s.text, s.start_ms, s.end_ms) for s in result] == [("Hola.", 0, 200)]


@pytest.mark.asyncio
async def test_activity_overrides_negative_decoder_score(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = await execute(
        monkeypatch,
        tmp_path,
        [
            {
                "text": "Hola.",
                "start": 0.0,
                "end": 0.2,
                "no_speech_prob": 0.99,
            }
        ],
        [(0, 200)],
    )
    assert len(result) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "word",
    [
        {"word": "wrong", "start": 2, "end": 3},
        {"word": "Hola.", "start": 3, "end": 2},
        {"word": "Hola.", "start": float("nan"), "end": 3},
        {"word": "Hola.", "start": 1, "end": 3},
    ],
)
async def test_invalid_words_fall_back_to_whole_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, word: dict[str, Any]
) -> None:
    result = await execute(
        monkeypatch,
        tmp_path,
        [
            {
                "text": "Hola.",
                "start": 2,
                "end": 3,
                "words": [word],
            }
        ],
        [(2000, 3000)],
    )
    assert [(s.text, s.start_ms, s.end_ms) for s in result] == [("Hola.", 2000, 3000)]
