"""Production FFprobe/FFmpeg wiring on synthetic in-memory audio, when tools exist."""

from __future__ import annotations

import base64
import io
import shutil
import wave
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest

from app.infra.object_store import ObjectStore
from app.meetings.speaker_excerpt_service import create_speaker_excerpt_service


@dataclass(frozen=True)
class Candidate:
    start_ms: int = 100
    end_ms: int = 500
    vad_positive_windows: int = 1
    vad_window_count: int = 1
    assigned_speaker_id: str = "synthetic-speaker"


class InMemorySource:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls: list[tuple[str, int]] = []

    async def get_bounded(self, key: str, max_bytes: int, deadline_monotonic: float) -> bytes:
        assert deadline_monotonic > 0
        self.calls.append((key, max_bytes))
        if len(self.data) > max_bytes:
            raise ValueError("source too large")
        return self.data


def wav_source(seconds: int) -> bytes:
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * (16_000 * seconds))
    return data.getvalue()


@pytest.mark.asyncio
@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg tools unavailable")
async def test_production_decoder_replays_only_complete_bounded_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "test")
    monkeypatch.setenv("SPEAKER_EXCERPT_KEYRING", "test:" + base64.urlsafe_b64encode(b"k" * 32).decode())
    source = InMemorySource(wav_source(1))
    service = create_speaker_excerpt_service(cast(ObjectStore, source))
    excerpt = await service.derive(
        recording_id="synthetic-meeting",
        revision_id=1,
        speaker_id="synthetic-speaker",
        object_key="synthetic-private-object",
        audio_duration_ms=1000,
        candidates=[Candidate()],
    )
    item = SimpleNamespace(
        speaker_key="synthetic-speaker",
        excerpt_ref=excerpt.reference,
        review=SimpleNamespace(meeting_id="synthetic-meeting", processing_revision=1),
    )
    pcm = await service.play(recording_id="synthetic-meeting", revision_id=1, review_item=item)
    assert len(pcm) == 400 * 16_000 * 2 // 1000
    assert source.calls == [("synthetic-private-object", 20 * 1024 * 1024)] * 2

    # At exactly 30 s the capped probe cannot prove there is no further audio;
    # fail explicitly rather than silently treating a 31 s source as 30 s.
    for duration in (30, 31):
        source.data = wav_source(duration)
        with pytest.raises(ValueError, match="speaker excerpt unavailable"):
            await service.play(recording_id="synthetic-meeting", revision_id=1, review_item=item)
    assert len(source.calls) == 4
