"""The sweeper resumes or ends processing that nothing is left to resume (#1166)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    RegenerationOperation,
    SessionRecording,
    SpeechTurn,
    StateHistory,
    Transcript,
)
from app.infra.orphan_sweeper import INTERRUPTED_CAUSE, OrphanSweeper
from app.infra.queue import JobQueue

pytestmark = pytest.mark.asyncio


class RecordingQueue(JobQueue):
    def __init__(self, waiting: int | None = 0) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.waiting = waiting

    async def publish(self, topic: str, message: dict[str, Any]) -> None:
        self.published.append((topic, message))

    async def subscribe(self, topic: str, handler: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def pending_count(self, topic: str) -> int | None:
        return self.waiting


async def _seed(
    factory: async_sessionmaker[AsyncSession], *, state: str = "transcribing", generation: int = 2,
    claim_id: str | None = None, claim_kind: str | None = None, expires_at: datetime | None = None,
    entered: timedelta = timedelta(hours=1), with_transcript: bool = False, with_claim: bool = True,
) -> tuple[str, str]:
    meeting_id, owner_id, recording_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state=state, failure_cause=None,
            created_by=owner_id, created_at=now - entered,
        ))
        session.add(SessionRecording(
            id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()), capture_origin="manual_upload",
            audio_ref="recordings/x", video_ref=None, duration_seconds=60, interrupted=False, expires_at=None,
            finished_at=now - entered,
        ))
        session.add(StateHistory(
            id=str(uuid.uuid4()), meeting_id=meeting_id, state=state, failure_cause=None, occurred_at=now - entered,
        ))
        if with_claim:
            session.add(MeetingProcessingClaim(
                meeting_id=meeting_id, generation=generation, claim_id=claim_id, claim_kind=claim_kind,
                claim_expires_at=expires_at,
            ))
        if with_transcript:
            transcript_id = str(uuid.uuid4())
            session.add(Transcript(
                id=transcript_id, meeting_id=meeting_id, language="es", provider="local", supports_turns=True,
                expires_at=None, created_at=now - entered,
            ))
            session.add(SpeechTurn(
                id=str(uuid.uuid4()), transcript_id=transcript_id, text="hola", start_ms=0, end_ms=1, sequence=1,
            ))
    return meeting_id, owner_id


def _lapsed(minutes: float = 30) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


def _sweeper(factory: async_sessionmaker[AsyncSession], queue: JobQueue, **kw: Any) -> OrphanSweeper:
    options: dict[str, Any] = {"orphan_after_s": 300, "max_attempts": 3, "backoff_s": 0.0, "max_age_s": 86400}
    return OrphanSweeper(factory, queue, **{**options, **kw})


async def test_lapsed_transcription_claim_is_republished_for_its_generation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, owner_id = await _seed(
        session_factory, claim_id=str(uuid.uuid4()), claim_kind="transcription", expires_at=_lapsed(),
    )
    queue = RecordingQueue()

    actions = await _sweeper(session_factory, queue).sweep()

    assert actions == [f"republished:transcription:{meeting_id}"]
    [(topic, message)] = queue.published
    assert topic == "transcribe"
    assert message["meeting_id"] == meeting_id and message["owner_id"] == owner_id
    assert message["generation"] == 2 and message["audio_ref"] == "recordings/x" and message["job_id"]


async def test_claim_without_expiry_left_by_an_older_worker_is_republished(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, _ = await _seed(
        session_factory, claim_id=str(uuid.uuid4()), claim_kind="transcription", entered=timedelta(hours=2),
    )
    queue = RecordingQueue()
    assert await _sweeper(session_factory, queue).sweep() == [f"republished:transcription:{meeting_id}"]


async def test_live_lease_and_recently_lapsed_lease_are_left_alone(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(session_factory, claim_id="a", claim_kind="transcription",
                expires_at=datetime.now(UTC) + timedelta(minutes=2))
    await _seed(session_factory, claim_id="b", claim_kind="transcription",
                expires_at=datetime.now(UTC) - timedelta(seconds=60))  # the broker's redelivery is still due
    queue = RecordingQueue()
    assert await _sweeper(session_factory, queue).sweep() == []
    assert queue.published == []


async def test_unclaimed_transcribing_meeting_is_republished_only_when_nothing_waits_in_the_queue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, _ = await _seed(session_factory)

    busy = RecordingQueue(waiting=3)  # a backlog: it is just waiting its turn
    assert await _sweeper(session_factory, busy).sweep() == []
    unknown = RecordingQueue(waiting=None)
    assert await _sweeper(session_factory, unknown).sweep() == []

    empty = RecordingQueue(waiting=0)
    assert await _sweeper(session_factory, empty).sweep() == [f"republished:transcription:{meeting_id}"]


async def test_nothing_that_is_finished_or_owned_elsewhere_is_touched(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    gone = dict(claim_id="a", claim_kind="transcription", expires_at=_lapsed())
    await _seed(session_factory, with_transcript=True, **gone)  # transcript committed: nothing to compute
    await _seed(session_factory, state="completed", **gone)
    await _seed(session_factory, state="failed", **gone)
    await _seed(session_factory, claim_id="op", claim_kind="recovery")  # reserved for an operation's own worker
    with_operation, _ = await _seed(session_factory, **gone)
    async with session_factory() as session, session.begin():
        session.add(RegenerationOperation(
            id=str(uuid.uuid4()), meeting_id=with_operation, stage="transcription", status="running",
            requested_by=str(uuid.uuid4()), cascade=False, requested_at=datetime.now(UTC), details={},
        ))
    queue = RecordingQueue()

    assert await _sweeper(session_factory, queue).sweep() == []
    assert queue.published == []


async def test_one_stage_is_republished_per_sweep_and_each_waits_its_backoff(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first, _ = await _seed(session_factory, claim_id="a", claim_kind="transcription", expires_at=_lapsed())
    second, _ = await _seed(session_factory, claim_id="b", claim_kind="transcription", expires_at=_lapsed())
    queue = RecordingQueue()
    sweeper = _sweeper(session_factory, queue, backoff_s=3600)

    one = await sweeper.sweep()
    two = await sweeper.sweep()
    three = await sweeper.sweep()

    assert len(one) == 1 and len(two) == 1 and one != two
    assert {a.split(":")[2] for a in one + two} == {first, second}
    assert three == []  # both are inside their backoff


async def test_after_the_attempts_run_out_the_meeting_fails_with_a_clear_cause_and_nothing_else_changes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, _ = await _seed(session_factory, claim_id="a", claim_kind="transcription", expires_at=_lapsed())
    queue = RecordingQueue()
    sweeper = _sweeper(session_factory, queue, max_attempts=2)

    assert await sweeper.sweep() == [f"republished:transcription:{meeting_id}"]
    assert await sweeper.sweep() == [f"republished:transcription:{meeting_id}"]
    assert await sweeper.sweep() == [f"failed:transcription:{meeting_id}"]
    assert await sweeper.sweep() == []

    assert len(queue.published) == 2
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None
        assert (meeting.process_state, meeting.failure_cause) == ("failed", INTERRUPTED_CAUSE)
        history = (await session.scalars(
            select(StateHistory).where(StateHistory.meeting_id == meeting_id, StateHistory.state == "failed")
        )).all()
        assert [h.failure_cause for h in history] == [INTERRUPTED_CAUSE]
        assert (await session.execute(select(Transcript))).scalars().all() == []


async def test_a_stage_open_for_too_long_is_given_up_even_on_its_first_look(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, _ = await _seed(
        session_factory, claim_id="a", claim_kind="transcription", expires_at=_lapsed(),
        entered=timedelta(days=2),
    )
    queue = RecordingQueue()
    assert await _sweeper(session_factory, queue).sweep() == [f"failed:transcription:{meeting_id}"]
    assert queue.published == []


async def test_a_worker_taking_over_before_the_give_up_wins(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, _ = await _seed(session_factory, claim_id="a", claim_kind="transcription", expires_at=_lapsed())
    sweeper = _sweeper(session_factory, RecordingQueue(), max_attempts=0)
    async with session_factory() as session:
        orphans = await sweeper._orphans(session)  # found as an orphan...
    async with session_factory() as session, session.begin():  # ...but a worker takes it over right after
        claim = await session.get(MeetingProcessingClaim, meeting_id)
        assert claim is not None
        claim.claim_id = "new-holder"
        claim.claim_expires_at = datetime.now(UTC) + timedelta(minutes=2)

    assert await sweeper._give_up(orphans[0]) is False
    async with session_factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.process_state == "transcribing"


async def test_lapsed_speaker_identification_is_republished_then_marked_failed_keeping_the_transcript(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, _ = await _seed(
        session_factory, state="completed", generation=7, claim_id="a", claim_kind="diarization",
        expires_at=_lapsed(), with_transcript=True,
    )
    queue = RecordingQueue()
    sweeper = _sweeper(session_factory, queue, max_attempts=1)

    assert await sweeper.sweep() == [f"republished:speakers:{meeting_id}"]
    [(topic, message)] = queue.published
    assert topic == "diarize" and message["generation"] == 7 and "audio_ref" not in message

    assert await sweeper.sweep() == [f"failed:speakers:{meeting_id}"]
    async with session_factory() as session:
        attempt = await session.scalar(select(Diarization).where(Diarization.meeting_id == meeting_id))
        assert attempt is not None
        assert (attempt.diarization_state, attempt.failure_cause) == ("failed", INTERRUPTED_CAUSE)
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.process_state == "completed"
        assert await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id)) is not None


async def test_finished_speaker_identification_is_never_republished(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    meeting_id, _ = await _seed(
        session_factory, state="completed", claim_id="a", claim_kind="diarization", expires_at=_lapsed(),
        with_transcript=True,
    )
    async with session_factory() as session, session.begin():
        transcript_id = await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id))
        assert transcript_id is not None
        session.add(Diarization(
            id=str(uuid.uuid4()), meeting_id=meeting_id, transcript_id=transcript_id, processing_revision=1,
            is_legacy=False, provider="x", speaker_count=2, diarization_state="completed",
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        ))
    queue = RecordingQueue()
    assert await _sweeper(session_factory, queue).sweep() == []


async def test_completed_meeting_whose_speakers_were_left_in_progress_without_expiry_is_resumed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Second 2026-11-16 incident: process_state is completed, the diarizations row says in_progress."""
    meeting_id, _ = await _seed(
        session_factory, state="completed", generation=2, claim_id="old", claim_kind="diarization",
        entered=timedelta(minutes=40), with_transcript=True,
    )
    async with session_factory() as session, session.begin():
        transcript_id = await session.scalar(select(Transcript.id).where(Transcript.meeting_id == meeting_id))
        assert transcript_id is not None
        session.add(Diarization(
            id=str(uuid.uuid4()), meeting_id=meeting_id, transcript_id=transcript_id, processing_revision=1,
            is_legacy=False, provider=None, speaker_count=0, diarization_state="in_progress",
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        ))
    queue = RecordingQueue()

    assert await _sweeper(session_factory, queue).sweep() == [f"republished:speakers:{meeting_id}"]
    assert queue.published[0][0] == "diarize"
