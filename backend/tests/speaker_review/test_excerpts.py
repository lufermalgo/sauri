"""RED contract for speaker-specific excerpt derivation and resolution.

The narrow internal seam chosen for this task is
``app.meetings.speaker_excerpt_service.SpeakerExcerptService``. Tests use
synthetic diarization intervals and fake decoder/object-store adapters only;
the service is responsible for keeping storage locators private and binding
references to one recording, revision, and speaker.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.infra.models import SpeakerReview, SpeakerReviewItem
from app.infra.object_store import ObjectStore
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
        self.decode_calls: list[tuple[int, int]] = []
        self.read_calls: list[tuple[int, int]] = []
        self.source_read_calls: list[tuple[str, int]] = []
        self.fail_read = False


def _encoded_test_key(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode("ascii").rstrip("=")


class FakeBoundedStore:
    def __init__(self, media: FakeMedia) -> None:
        self.media = media

    async def get_bounded(
        self, object_key: str, max_bytes: int, deadline_monotonic: float
    ) -> bytes:
        assert deadline_monotonic > 0
        self.media.source_read_calls.append((object_key, max_bytes))
        return b"synthetic-source"


class FakeInput:
    def write(self, _data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class FakeOutput:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class FakeDecoderProcess:
    returncode: int | None = None

    def __init__(self, media: FakeMedia, command: tuple[str, ...]) -> None:
        self.media = media
        self.command = command
        self.pid = 1
        self.exit_code = 0
        self.stdin = FakeInput()
        if command[1] == "probe":
            result = b"10.0"
        else:
            _, mode, start_text, end_text = command
            start_ms, end_ms = int(start_text), int(end_text)
            if mode == "decode":
                result = self.media.decoded.get((start_ms, end_ms)) or b""
            elif self.media.fail_read:
                result = b""
                self.exit_code = 1
            else:
                result = b"synthetic-audio"
        self.stdout = FakeOutput(result)

    async def communicate(self, **kwargs: Any) -> tuple[bytes, bytes]:
        assert kwargs["input"] == b"synthetic-source"
        return self.stdout.data, b""

    async def wait(self) -> int:
        self.returncode = self.exit_code
        return self.exit_code


def _new_service(media: FakeMedia) -> SpeakerExcerptService:
    from app.meetings.speaker_excerpt_service import ManagedDecoderProcess

    async def spawn(*command: str, start_new_session: bool) -> FakeDecoderProcess:
        assert start_new_session
        return FakeDecoderProcess(media, command)

    def decode_command(start_ms: int, end_ms: int) -> tuple[str, ...]:
        media.decode_calls.append((start_ms, end_ms))
        return ("synthetic-decoder", "decode", str(start_ms), str(end_ms))

    def read_command(start_ms: int, end_ms: int) -> tuple[str, ...]:
        media.read_calls.append((start_ms, end_ms))
        return ("synthetic-decoder", "read", str(start_ms), str(end_ms))

    return SpeakerExcerptService(
        object_store=cast(ObjectStore, FakeBoundedStore(media)),
        decoder=ManagedDecoderProcess(
            spawn_process=spawn,
            kill_process_group=lambda *_: None,
            process_group_exists=lambda _pid: False,
        ),
        decode_interval=decode_command,
        read_interval=read_command,
        probe_audio=lambda: ("synthetic-decoder", "probe"),
    )


def _service(media: FakeMedia) -> SpeakerExcerptService:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "test-v1")
        monkeypatch.setenv("SPEAKER_EXCERPT_KEYRING", f"test-v1:{_encoded_test_key(1)}")
        return _new_service(media)


def _candidates() -> list[Candidate]:
    return [
        Candidate(0, 1_000, vad_positive_windows=1, vad_window_count=1),
        Candidate(2_000, 3_500, vad_positive_windows=1, vad_window_count=2),
        Candidate(4_000, 5_500, vad_positive_windows=2, vad_window_count=2),
        Candidate(6_000, 7_500, vad_positive_windows=2, vad_window_count=2),
    ]


async def _derive(
    service: SpeakerExcerptService,
    *,
    candidates: list[Candidate] | None = None,
    audio_duration_ms: int = 10_000,
    object_key: str = "private-bucket/private-recording.wav",
) -> Any:
    return await service.derive(
        recording_id="recording-a",
        revision_id=7,
        speaker_id="speaker-a",
        object_key=object_key,
        audio_duration_ms=audio_duration_ms,
        candidates=_candidates() if candidates is None else candidates,
    )


@pytest.mark.asyncio
async def test_candidate_selection_uses_duration_then_vad_then_earliest_start() -> None:
    """Longest candidates win; equal durations use VAD ratio, then earliest start."""
    media = FakeMedia(
        {
            (0, 1_000): b"short",
            (2_000, 3_500): b"lower-vad",
            (4_000, 5_500): b"tie-earlier",
            (6_000, 7_500): b"tie-later",
        }
    )

    excerpt = await _derive(_service(media))

    assert (excerpt.start_ms, excerpt.end_ms) == (4_000, 5_500)
    assert media.decode_calls == [(4_000, 5_500)]
    assert media.source_read_calls == [("private-bucket/private-recording.wav", 20 * 1024 * 1024)]


@pytest.mark.asyncio
async def test_invalid_candidates_are_rejected_before_excerpt_is_ready() -> None:
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

    excerpt = await _derive(_service(media), candidates=candidates)

    assert (excerpt.start_ms, excerpt.end_ms) == (6_000, 7_500)
    assert media.decode_calls == [(8_000, 10_000), (6_000, 7_500)]


@pytest.mark.asyncio
async def test_revision_is_not_ready_when_no_candidate_passes_validation() -> None:
    """No review excerpt may be created from empty or wholly invalid candidates."""
    media = FakeMedia()
    candidates = [
        Candidate(0, 500),  # decoding fails because the synthetic fixture has no interval data
        Candidate(1_000, 2_000, vad_positive_windows=0),
    ]

    with pytest.raises(ValueError, match="speaker excerpt unavailable"):
        await _derive(_service(media), candidates=candidates)


@pytest.mark.asyncio
async def test_excerpt_reference_is_opaque_and_bound_to_recording_revision_and_speaker() -> None:
    """A public ref must not disclose its locator or resolve across scope boundaries."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    service = _service(media)
    private_key = "private-bucket/private-recording.wav"
    excerpt = await _derive(service, object_key=private_key)

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
    for recording_id, revision_id, speaker_id in (
        ("recording-b", 7, "speaker-a"),
        ("recording-a", 8, "speaker-a"),
        ("recording-a", 7, "speaker-b"),
    ):
        with pytest.raises(LookupError):
            service.resolve(
                excerpt.reference,
                recording_id=recording_id,
                revision_id=revision_id,
                speaker_id=speaker_id,
            )


@pytest.mark.asyncio
async def test_playback_failure_does_not_substitute_or_complete_review_item() -> None:
    """The actual playback call leaves its pending review model unchanged on read failure."""
    from datetime import UTC, datetime

    from app.meetings.speaker_review_state import review_status

    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    media.fail_read = True
    service = _service(media)
    excerpt = await _derive(service)
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

    with pytest.raises(ValueError, match="speaker excerpt unavailable"):
        await service.play(
            recording_id="recording-a",
            revision_id=7,
            review_item=item,
        )

    assert media.read_calls == [(4_000, 5_500)]
    assert media.source_read_calls == [
        ("private-bucket/private-recording.wav", 20 * 1024 * 1024),
        ("private-bucket/private-recording.wav", 20 * 1024 * 1024),
    ]
    assert item.disposition is None
    assert review.status == "pending"
    assert review_status({item.speaker_key: item.disposition}) == "pending"


@pytest.mark.asyncio
async def test_excerpt_reference_is_persisted_and_playback_uses_only_the_item_reference() -> None:
    """Playback must select the persisted opaque ref on its authorized review item."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    service = _service(media)
    excerpt = await _derive(service)
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
    assert item.excerpt_ref is not None
    assert "private-bucket/private-recording.wav" not in item.excerpt_ref
    assert await service.play(
        recording_id="recording-a",
        revision_id=7,
        review_item=item,
    ) == b"synthetic-audio"
    assert media.read_calls == [(4_000, 5_500)]
    assert media.source_read_calls == [
        ("private-bucket/private-recording.wav", 20 * 1024 * 1024),
        ("private-bucket/private-recording.wav", 20 * 1024 * 1024),
    ]


@pytest.mark.asyncio
async def test_playback_rejects_a_review_item_from_a_different_recording_or_revision() -> None:
    """An item's persisted reference cannot be replayed under caller-selected scope."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    service = _service(media)
    excerpt = await _derive(service)
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
        await service.play(recording_id="recording-b", revision_id=7, review_item=item)

    assert media.read_calls == []


def test_excerpt_keys_are_required_outside_the_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Service startup must reject absent dedicated excerpt-encryption material."""
    monkeypatch.delenv("SPEAKER_EXCERPT_KEYRING", raising=False)
    monkeypatch.delenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", raising=False)

    with pytest.raises(RuntimeError, match="SPEAKER_EXCERPT_KEYRING"):
        _new_service(FakeMedia())


@pytest.mark.asyncio
async def test_versioned_excerpt_keyring_can_rotate_while_resolving_existing_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retaining a prior key ID permits old references after the active key rotates."""
    media = FakeMedia({(4_000, 5_500): b"synthetic-speech"})
    monkeypatch.setenv("SPEAKER_EXCERPT_KEYRING", f"key-v1:{_encoded_test_key(1)}")
    monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "key-v1")
    before_rotation = _new_service(media)
    excerpt = await _derive(before_rotation)

    monkeypatch.setenv(
        "SPEAKER_EXCERPT_KEYRING",
        f"key-v1:{_encoded_test_key(1)},key-v2:{_encoded_test_key(2)}",
    )
    monkeypatch.setenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", "key-v2")
    after_rotation = _new_service(media)

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

    async def start_app() -> None:
        async with app.router.lifespan_context(app):
            pass

    monkeypatch.delenv("SPEAKER_EXCERPT_KEYRING", raising=False)
    monkeypatch.delenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="SPEAKER_EXCERPT_KEYRING"):
        asyncio.run(start_app())
