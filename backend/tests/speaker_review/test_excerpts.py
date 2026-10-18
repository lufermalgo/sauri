"""RED contract for speaker-specific excerpt derivation and resolution.

The narrow internal seam chosen for this task is
``app.meetings.speaker_excerpt_service.SpeakerExcerptService``. Tests use
synthetic diarization intervals and fake decoder/object-store adapters only;
the service is responsible for keeping storage locators private and binding
references to one recording, revision, and speaker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from app.meetings.speaker_excerpt_service import SpeakerExcerptService

from app.infra.models import SpeakerReview, SpeakerReviewItem


@dataclass(frozen=True)
class Candidate:
    start_ms: int
    end_ms: int
    vad_positive_windows: int = 1
    vad_window_count: int = 1
    assigned_speaker_id: str = "speaker-a"


class FakeMedia:
    """Synthetic adapter: no actual recording or object store is accessed."""

    def __init__(self, decoded: dict[tuple[int, int], bytes] | None = None) -> None:
        self.decoded = decoded or {}
        self.decode_calls: list[tuple[str, int, int]] = []
        self.read_calls: list[tuple[str, int, int]] = []
        self.fail_read = False

    def decode(self, object_key: str, start_ms: int, end_ms: int) -> bytes:
        self.decode_calls.append((object_key, start_ms, end_ms))
        result = self.decoded.get((start_ms, end_ms))
        if result is None:
            raise ValueError("synthetic decode failure")
        return result

    def read(self, object_key: str, start_ms: int, end_ms: int) -> bytes:
        self.read_calls.append((object_key, start_ms, end_ms))
        if self.fail_read:
            raise OSError("synthetic playback failure")
        return b"synthetic-audio"


def _service(media: FakeMedia) -> SpeakerExcerptService:
    return SpeakerExcerptService(decode_interval=media.decode, read_interval=media.read)


def _candidates() -> list[Candidate]:
    return [
        Candidate(0, 1_000, vad_positive_windows=1, vad_window_count=1),
        Candidate(2_000, 3_500, vad_positive_windows=1, vad_window_count=2),
        Candidate(4_000, 5_500, vad_positive_windows=2, vad_window_count=2),
        Candidate(6_000, 7_500, vad_positive_windows=2, vad_window_count=2),
    ]


def _derive(
    service: SpeakerExcerptService,
    *,
    candidates: list[Candidate] | None = None,
    audio_duration_ms: int = 10_000,
    object_key: str = "private-bucket/private-recording.wav",
) -> Any:
    return service.derive(
        recording_id="recording-a",
        revision_id="revision-7",
        speaker_id="speaker-a",
        object_key=object_key,
        audio_duration_ms=audio_duration_ms,
        candidates=_candidates() if candidates is None else candidates,
    )


def test_candidate_selection_uses_duration_then_vad_then_earliest_start() -> None:
    """Longest candidates win; equal durations use VAD ratio, then earliest start."""
    media = FakeMedia(
        {
            (0, 1_000): b"short",
            (2_000, 3_500): b"lower-vad",
            (4_000, 5_500): b"tie-earlier",
            (6_000, 7_500): b"tie-later",
        }
    )

    excerpt = _derive(_service(media))

    assert (excerpt.start_ms, excerpt.end_ms) == (4_000, 5_500)
    assert media.decode_calls == [
        ("private-bucket/private-recording.wav", 4_000, 5_500),
    ]


def test_invalid_candidates_are_rejected_before_excerpt_is_ready() -> None:
    """Bounds, decode, speech activity and speaker assignment are all validated."""
    candidates = [
        Candidate(-1, 1_000),  # starts before the recording
        Candidate(1_000, 11_000),  # ends after the recording
        Candidate(2_000, 3_500, assigned_speaker_id="speaker-b"),
        Candidate(4_000, 5_500, vad_positive_windows=0),
        Candidate(8_000, 10_000),  # longest candidate fails decoding
        Candidate(6_000, 7_500),  # valid fallback after the decode failure
    ]
    media = FakeMedia({(6_000, 7_500): b"valid-speech"})

    excerpt = _derive(_service(media), candidates=candidates)

    assert (excerpt.start_ms, excerpt.end_ms) == (6_000, 7_500)
    assert media.decode_calls == [
        ("private-bucket/private-recording.wav", 8_000, 10_000),
        ("private-bucket/private-recording.wav", 6_000, 7_500),
    ]


def test_revision_is_not_ready_when_no_candidate_passes_validation() -> None:
    """No review excerpt may be created from empty or wholly invalid candidates."""
    media = FakeMedia()
    candidates = [
        Candidate(0, 500),  # decoding fails because the synthetic fixture has no interval data
        Candidate(1_000, 2_000, vad_positive_windows=0),
    ]

    with pytest.raises(ValueError, match="no validated speaker excerpt"):
        _derive(_service(media), candidates=candidates)


def test_excerpt_reference_is_opaque_and_bound_to_recording_revision_and_speaker() -> None:
    """A public ref must not disclose its locator or resolve across scope boundaries."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    service = _service(media)
    private_key = "private-bucket/private-recording.wav"
    excerpt = _derive(service, object_key=private_key)

    assert isinstance(excerpt.reference, str)
    assert excerpt.reference
    assert private_key not in excerpt.reference
    assert all(
        scope_id not in excerpt.reference
        for scope_id in ("recording-a", "revision-7", "speaker-a")
    )
    assert private_key not in repr(excerpt.public_dict())
    assert service.resolve(
        excerpt.reference,
        recording_id="recording-a",
        revision_id="revision-7",
        speaker_id="speaker-a",
    ) == (private_key, excerpt.start_ms, excerpt.end_ms)
    for scope in (
        {"recording_id": "recording-b", "revision_id": "revision-7", "speaker_id": "speaker-a"},
        {"recording_id": "recording-a", "revision_id": "revision-8", "speaker_id": "speaker-a"},
        {"recording_id": "recording-a", "revision_id": "revision-7", "speaker_id": "speaker-b"},
    ):
        with pytest.raises(LookupError):
            service.resolve(excerpt.reference, **scope)


def test_playback_failure_does_not_substitute_or_complete_review_item() -> None:
    """The actual playback call leaves its pending review model unchanged on read failure."""
    from datetime import UTC, datetime

    from app.meetings.speaker_review_state import review_status

    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    media.fail_read = True
    service = _service(media)
    excerpt = _derive(service)
    review = SpeakerReview(
        id="review-a",
        meeting_id="recording-a",
        processing_revision=7,
        status="pending",
        created_at=datetime.now(UTC),
    )
    item = SpeakerReviewItem(
        id="item-a",
        review_id=review.id,
        speaker_key="speaker-a",
        current_label="Speaker 1",
        disposition=None,
        chosen_label=None,
        attribution_state="uncertain",
        version=1,
    )
    review.items.append(item)

    with pytest.raises(OSError, match="synthetic playback failure"):
        service.play(
            excerpt.reference,
            recording_id="recording-a",
            revision_id="revision-7",
            speaker_id="speaker-a",
            review_item=item,
        )

    assert media.read_calls == [
        ("private-bucket/private-recording.wav", 4_000, 5_500),
    ]
    assert item.disposition is None
    assert review.status == "pending"
    assert review_status({item.speaker_key: item.disposition}) == "pending"
