"""RED contract for speaker-specific excerpt derivation and resolution.

The narrow internal seam chosen for this task is
``app.meetings.speaker_excerpt_service.SpeakerExcerptService``. Tests use
synthetic diarization intervals and fake decoder/object-store adapters only;
the service is responsible for keeping storage locators private and binding
references to one recording, revision, and speaker.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from app.infra.models import SpeakerReview, SpeakerReviewItem
from app.meetings.speaker_excerpt_service import SpeakerExcerptService


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


def _encoded_test_key(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


def _service(media: FakeMedia) -> SpeakerExcerptService:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "test-v1")
        monkeypatch.setenv("SPEAKER_EXCERPT_KEYRING", f"test-v1={_encoded_test_key(1)}")
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
        revision_id=7,
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
        revision_id=7,
        speaker_id="speaker-a",
    ) == (private_key, excerpt.start_ms, excerpt.end_ms)
    for scope in (
        {"recording_id": "recording-b", "revision_id": 7, "speaker_id": "speaker-a"},
        {"recording_id": "recording-a", "revision_id": 8, "speaker_id": "speaker-a"},
        {"recording_id": "recording-a", "revision_id": 7, "speaker_id": "speaker-b"},
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

    service.persist(excerpt, review_item=item)

    with pytest.raises(OSError, match="synthetic playback failure"):
        service.play(
            recording_id="recording-a",
            revision_id=7,
            review_item=item,
        )

    assert media.read_calls == [
        ("private-bucket/private-recording.wav", 4_000, 5_500),
    ]
    assert item.disposition is None
    assert review.status == "pending"
    assert review_status({item.speaker_key: item.disposition}) == "pending"


def test_excerpt_reference_is_persisted_and_playback_uses_only_the_item_reference() -> None:
    """Playback must select the persisted opaque ref on its authorized review item."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
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
        excerpt_ref=None,
        disposition=None,
        chosen_label=None,
        attribution_state="uncertain",
        version=1,
    )
    review.items.append(item)

    assert callable(getattr(service, "persist", None)), "persist must be available for review items"
    service.persist(excerpt, review_item=item)

    assert item.excerpt_ref == excerpt.reference
    assert "private-bucket/private-recording.wav" not in item.excerpt_ref
    assert service.play(
        recording_id="recording-a",
        revision_id=7,
        review_item=item,
    ) == b"synthetic-audio"
    assert media.read_calls == [
        ("private-bucket/private-recording.wav", 4_000, 5_500),
    ]


def test_playback_rejects_a_review_item_from_a_different_recording_or_revision() -> None:
    """An item's persisted reference cannot be replayed under caller-selected scope."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
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
        excerpt_ref=excerpt.reference,
        disposition=None,
        chosen_label=None,
        attribution_state="uncertain",
        version=1,
    )
    review.items.append(item)

    with pytest.raises(LookupError, match="outside the requested scope"):
        service.play(recording_id="recording-b", revision_id=7, review_item=item)

    assert media.read_calls == []


def test_excerpt_keys_are_required_outside_the_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Service startup must reject absent dedicated excerpt-encryption material."""
    monkeypatch.delenv("SPEAKER_EXCERPT_KEYRING", raising=False)
    monkeypatch.delenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", raising=False)

    with pytest.raises(RuntimeError, match="SPEAKER_EXCERPT_KEYRING"):
        SpeakerExcerptService(decode_interval=lambda *_: b"", read_interval=lambda *_: b"")


def test_versioned_excerpt_keyring_can_rotate_while_resolving_existing_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retaining a prior key ID permits old references after the active key rotates."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    monkeypatch.setenv("SPEAKER_EXCERPT_KEYRING", f"key-v1={_encoded_test_key(1)}")
    monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "key-v1")
    before_rotation = SpeakerExcerptService(decode_interval=media.decode, read_interval=media.read)
    excerpt = _derive(before_rotation)

    monkeypatch.setenv(
        "SPEAKER_EXCERPT_KEYRING",
        f"key-v1={_encoded_test_key(1)},key-v2={_encoded_test_key(2)}",
    )
    monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "key-v2")
    after_rotation = SpeakerExcerptService(decode_interval=media.decode, read_interval=media.read)

    assert excerpt.reference.startswith("v1.key-v1.")
    assert after_rotation.resolve(
        excerpt.reference,
        recording_id="recording-a",
        revision_id=7,
        speaker_id="speaker-a",
    ) == ("private-bucket/private-recording.wav", 4_000, 5_500)


def test_application_startup_validates_excerpt_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API refuses to start with missing excerpt-encryption configuration."""
    from app.main import app

    startup = next(
        (
            handler
            for handler in app.router.on_startup
            if getattr(handler, "__name__", "") == "validate_speaker_excerpt_keyring"
        ),
        None,
    )
    assert callable(startup), "application startup must validate excerpt key configuration"

    monkeypatch.delenv("SPEAKER_EXCERPT_KEYRING", raising=False)
    monkeypatch.delenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="SPEAKER_EXCERPT_KEYRING"):
        startup()
