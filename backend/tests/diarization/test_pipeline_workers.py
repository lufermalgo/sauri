"""Real PostgreSQL worker boundaries for U3.3/U5.2 (#923, #925).

Synthetic engines exercise persistence, fencing and the actual global slot;
no native engine, private audio or shared database is used.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.diarization.diarization_engine import DiarizationResult, SpeakerSegment
from app.diarization.repository import DiarizationRepository
from app.diarization.worker import _process_diarization
from app.infra.database import Base
from app.infra.engine_slot import EngineSlotTimeout, engine_slot
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    MeetingSummary,
    SessionRecording,
    Speaker,
    SpeechTurn,
    StateHistory,
    SummaryRequestOutbox,
    SummaryTemplate,
    Transcript,
    TranscriptWord,
    User,
    WordSpeakerAssignment,
)
from app.summaries.passages import CanonicalSummary, validate_citations
from app.summaries.service import accept_request
from app.summaries.worker import start_worker
from app.transcription.asr_engine import TranscriptionResult, TranscriptionSegment, TranscriptionWord
from app.transcription.worker import _process_transcription

Factory = async_sessionmaker[AsyncSession]
WORDS = [
    TranscriptionWord("First", 0, 200, 0.9),
    TranscriptionWord(" overlap", 1000, 1200, 0.7, True),
    TranscriptionWord(" distant", 5000, 5200),
]
SEGMENTS = [SpeakerSegment("A", 0, 1200), SpeakerSegment("B", 1000, 1200)]


@pytest.fixture
async def pg_factory() -> AsyncIterator[Factory]:
    raw = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("SAURI_QA_POSTGRES_URL required for real worker integration")
    url = make_url(raw)
    assert url.drivername == "postgresql+asyncpg" and "sauri_qa" in (url.database or "")
    schema = f"sauri_qa_workers_{uuid4().hex}"
    admin = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


class Engines:
    """Only external inference is synthetic; worker SQL and advisory locks are real."""

    def __init__(self, words: list[TranscriptionWord]) -> None:
        self.words = words
        self.active = 0
        self.peak = 0
        self.calls: list[str] = []
        self.slot_timeout_s = 30.0

    @asynccontextmanager
    async def call(self, kind: str) -> AsyncIterator[None]:
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls.append(kind)
        try:
            await asyncio.sleep(0.05)
            yield
        finally:
            self.active -= 1

    async def transcribe(self, *_: Any) -> TranscriptionResult:
        async with self.call("transcription"):
            return TranscriptionResult(
                segments=[TranscriptionSegment("First overlap distant", 0, 5200)],
                words=self.words,
                language="en",
            )

    async def diarize(self, *_: Any) -> DiarizationResult:
        async with self.call("diarization"):
            return DiarizationResult(segments=SEGMENTS, speaker_count=2)

    async def generate(self, passages: Any, _: str) -> CanonicalSummary:
        async with self.call("summary"):
            return validate_citations(
                {
                    "topic": "Synthetic topic",
                    "key_points": [{"text": "Synthetic point", "sources": [{"passage_id": passages[0].passage_id}]}],
                },
                passages,
            )

    def capabilities(self) -> SimpleNamespace:
        return SimpleNamespace(is_local=True, supports_turns=True, provider_name="synthetic")


@pytest.fixture
async def engines(monkeypatch: pytest.MonkeyPatch) -> Engines:
    engines = Engines(WORDS)
    monkeypatch.setattr("app.transcription.worker.create_asr_engine", lambda: engines)
    monkeypatch.setattr("app.diarization.worker.create_diarization_engine", lambda: engines)
    monkeypatch.setattr("app.summaries.worker.create_summarization_engine", lambda: engines)

    @asynccontextmanager
    async def fast_slot(engine: AsyncEngine, *, kind: str, timeout_s: float) -> AsyncIterator[None]:
        async with engine_slot(engine, kind=kind, poll_s=0.01, timeout_s=engines.slot_timeout_s):
            yield

    for module in ("transcription", "diarization", "summaries"):
        monkeypatch.setattr(f"app.{module}.worker.engine_slot", fast_slot)
    return engines


async def seed(factory: Factory) -> dict[str, Any]:
    owner, meeting, recording, template, job = (str(uuid4()) for _ in range(5))
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(
            User(
                id=owner,
                email=f"{owner}@example.test",
                name="Synthetic",
                password_hash="unused",
                is_sales=True,
                created_at=now,
            )
        )
        session.add(
            Meeting(id=meeting, origin="upload", process_state="transcribing", created_by=owner, created_at=now)
        )
        await session.flush()
        session.add(
            SummaryTemplate(
                id=template,
                owner_user_id=owner,
                name="Custom default",
                instructions="Custom brief",
                version=3,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            SessionRecording(
                id=recording,
                meeting_id=meeting,
                idempotency_key=recording,
                capture_origin="web_upload",
                audio_ref="synthetic.webm",
                duration_seconds=6,
                interrupted=False,
                finished_at=now,
            )
        )
        session.add(MeetingProcessingClaim(meeting_id=meeting, generation=1))
        await session.flush()
        user = await session.get(User, owner)
        assert user is not None
        user.default_summary_template_id = template
    return dict(
        meeting_id=meeting, owner_id=owner, recording_id=recording, audio_ref="synthetic.webm", generation=1, job_id=job
    )


async def transcribe(factory: Factory, message: dict[str, Any]) -> dict[str, Any]:
    queue = AsyncMock()
    await _process_transcription(message, factory, queue)
    queue.publish.assert_awaited_once()
    topic, diarization_message = queue.publish.await_args.args
    assert topic == "diarize"
    return dict(diarization_message)


async def summary_message(factory: Factory, meeting_id: str) -> dict[str, Any]:
    async with factory() as session:
        request = await session.scalar(
            select(SummaryRequestOutbox).where(SummaryRequestOutbox.meeting_id == meeting_id)
        )
        assert request is not None
        return {
            key: getattr(request, key)
            for key in (
                "event_id",
                "meeting_id",
                "transcript_id",
                "generation",
                "template_id",
                "template_version",
                "instructions_snapshot",
            )
        }


async def consumer(factory: Factory) -> Any:
    queue = AsyncMock()
    await start_worker(queue, factory)
    return {call.args[0]: call.args[1] for call in queue.subscribe.await_args_list}["summarize"]


async def test_words_assignments_and_summary_are_revision_idempotent(pg_factory: Factory, engines: Engines) -> None:
    message = await seed(pg_factory)
    diarization_message = await transcribe(pg_factory, message)
    await _process_diarization(diarization_message, pg_factory)
    await _process_diarization(diarization_message, pg_factory)
    async with pg_factory() as session:
        words = list(await session.scalars(select(TranscriptWord).order_by(TranscriptWord.sequence)))
        assert [(w.sequence, w.text, w.start_ms, w.end_ms, w.probability, w.timing_repaired) for w in words] == [
            (i, w.text, w.start_ms, w.end_ms, w.probability, w.timing_repaired) for i, w in enumerate(WORDS, 1)
        ]
        revision = (await session.scalars(select(Diarization))).one()
        assert revision.processing_revision == 1 and revision.diarization_state == "completed"
        assignments = list(
            await session.scalars(select(WordSpeakerAssignment).join(TranscriptWord).order_by(TranscriptWord.sequence))
        )
        assert len(assignments) == len(words)
        assert {a.diarization_id for a in assignments} == {revision.id}
        assert [a.state for a in assignments] == ["assigned", "ambiguous", "unassigned"]
        speaker = await session.get(Speaker, assignments[0].speaker_id)
        assert speaker is not None and speaker.raw_label == "A" and speaker.diarization_id == revision.id
        assert assignments[0].candidates_json is None
        assert assignments[1].speaker_id is None
        speakers = {speaker.raw_label: speaker.id for speaker in await session.scalars(select(Speaker))}
        assert assignments[1].candidates_json == [
            {"speaker_id": speakers["A"], "fraction": 1.0},
            {"speaker_id": speakers["B"], "fraction": 1.0},
        ]
        assert assignments[2].speaker_id is None and assignments[2].candidates_json is None
        request = (await session.scalars(select(SummaryRequestOutbox))).one()
        owner = await session.get(User, message["owner_id"])
        assert owner is not None and request.template_id == owner.default_summary_template_id
        assert (request.template_version, request.instructions_snapshot) == (3, "Custom brief")
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None and meeting.process_state == "completed"
    assert engines.calls == ["transcription", "diarization"]


async def test_two_meetings_serialize_all_three_workers(pg_factory: Factory, engines: Engines) -> None:
    messages = [await seed(pg_factory), await seed(pg_factory)]
    consume = await consumer(pg_factory)

    async def pipeline(message: dict[str, Any]) -> None:
        diarization_message = await transcribe(pg_factory, message)
        await _process_diarization(diarization_message, pg_factory)
        await consume(await summary_message(pg_factory, message["meeting_id"]))

    await asyncio.gather(*(pipeline(message) for message in messages))
    assert engines.peak == 1
    assert sorted(engines.calls) == [
        "diarization",
        "diarization",
        "summary",
        "summary",
        "transcription",
        "transcription",
    ]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MeetingSummary)) == 2


async def test_legacy_transcript_without_words(pg_factory: Factory, engines: Engines) -> None:
    engines.words = []
    message = await seed(pg_factory)
    await _process_diarization(await transcribe(pg_factory, message), pg_factory)
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WordSpeakerAssignment)) == 0
        assert await session.scalar(select(func.count()).select_from(SpeechTurn)) == 1
        revision = (await session.scalars(select(Diarization))).one()
        assert revision.diarization_state == "completed" and revision.speaker_count == 2
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 1


async def test_summary_failure_is_visible_without_redelivery(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    message = await seed(pg_factory)
    diarization_message = await transcribe(pg_factory, message)
    with monkeypatch.context() as patch:
        patch.setattr("app.diarization.worker.accept_request", AsyncMock(side_effect=RuntimeError("private sentinel")))
        await _process_diarization(diarization_message, pg_factory)
    assert "Automatic summary request failed" in caplog.text and "private sentinel" not in caplog.text
    async with pg_factory() as session:
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None and meeting.process_state == "completed"
        request = (await session.scalars(select(SummaryRequestOutbox))).one()
        assert request.status == "failed" and request.failure_cause == "request_failed"
        assert (await session.scalars(select(Diarization))).one().diarization_state == "completed"
    await asyncio.gather(*(_process_diarization(diarization_message, pg_factory) for _ in range(2)))
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 1
    assert engines.calls == ["transcription", "diarization"]


@pytest.mark.parametrize("kind", ["transcription", "diarization", "summary"])
async def test_slot_timeout_retries_without_failing_meeting(
    pg_factory: Factory,
    engines: Engines,
    kind: str,
) -> None:
    message = await seed(pg_factory)
    if kind != "transcription":
        message = await transcribe(pg_factory, message)
    if kind == "summary":
        await _process_diarization(message, pg_factory)
        message = await summary_message(pg_factory, message["meeting_id"])
        handler = await consumer(pg_factory)
    else:
        process = _process_transcription if kind == "transcription" else _process_diarization

        async def handler(message: dict[str, Any]) -> None:
            await process(message, pg_factory)

    engines.slot_timeout_s = 0.1
    calls_before = len(engines.calls)
    async with engine_slot(pg_factory.kw["bind"], kind="test-holder"):
        with pytest.raises(EngineSlotTimeout):
            await handler(message)
    assert len(engines.calls) == calls_before
    async with pg_factory() as session:
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None and meeting.process_state == (
            "transcribing" if kind == "transcription" else "completed"
        )
        assert meeting.failure_cause is None
        if kind != "summary":
            claim = await session.get(MeetingProcessingClaim, message["meeting_id"])
            assert claim is not None and claim.claim_id is None and claim.claim_kind is None
        if kind == "diarization":
            assert (await session.scalars(select(Diarization))).one().diarization_state == "pending"
    await handler(message)
    assert len(engines.calls) == calls_before + 1
    async with pg_factory() as session:
        if kind == "summary":
            assert (await session.scalars(select(SummaryRequestOutbox))).one().status == "succeeded"
        elif kind == "diarization":
            assert (await session.scalars(select(Diarization))).one().diarization_state == "completed"
        else:
            assert await session.scalar(select(func.count()).select_from(TranscriptWord)) == len(WORDS)


@pytest.mark.parametrize("kind", ["transcription", "diarization"])
async def test_timeout_restores_recovery_claim_without_extending_lease(
    pg_factory: Factory,
    engines: Engines,
    kind: str,
) -> None:
    message = await seed(pg_factory)
    if kind == "diarization":
        message = await transcribe(pg_factory, message)
    engines.slot_timeout_s = 0.1
    operation = str(uuid4())
    expires = datetime.now(UTC) + timedelta(minutes=10)
    now = datetime.now(UTC)
    async with pg_factory() as session, session.begin():
        claim = await session.get(MeetingProcessingClaim, message["meeting_id"])
        assert claim is not None
        claim.claim_id, claim.claim_kind, claim.claim_expires_at = operation, "recovery", expires
        session.add(
            MeetingRecoveryOperation(
                id=operation,
                meeting_id=message["meeting_id"],
                actor_id=message["owner_id"],
                idempotency_key=operation,
                processing_generation=message["generation"],
                status="dispatch_pending",
                preservation_snapshot_digest=None,
                preservation_counts={},
                created_at=now,
                updated_at=now,
            )
        )
    message["operation_id"] = operation
    process = _process_transcription if kind == "transcription" else _process_diarization
    async with engine_slot(pg_factory.kw["bind"], kind="test-holder"):
        with pytest.raises(EngineSlotTimeout):
            await process(message, pg_factory)
    async with pg_factory() as session:
        claim = await session.get(MeetingProcessingClaim, message["meeting_id"])
        assert claim is not None
        assert (claim.claim_id, claim.claim_kind, claim.claim_expires_at) == (operation, "recovery", expires)
    await process(message, pg_factory)
    async with pg_factory() as session:
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None and meeting.process_state == "completed"


async def test_summary_identity_survives_template_change_and_new_revision(
    pg_factory: Factory,
    engines: Engines,
) -> None:
    message = await seed(pg_factory)
    await _process_diarization(await transcribe(pg_factory, message), pg_factory)
    async with pg_factory() as session, session.begin():
        first = (await session.scalars(select(SummaryRequestOutbox))).one()
        template = await session.get(SummaryTemplate, first.template_id)
        assert template is not None
        template.version, template.instructions = 4, "Updated brief"
    async with pg_factory() as session, session.begin():
        same = await accept_request(session, message["meeting_id"], message["owner_id"], None, processing_revision=1)
        second = await accept_request(session, message["meeting_id"], message["owner_id"], None, processing_revision=2)
        manual = await accept_request(session, message["meeting_id"], message["owner_id"], None)
        assert same.event_id == first.event_id and same.instructions_snapshot == "Custom brief"
        assert second.event_id != first.event_id and second.template_version == 4
        assert (same.generation, second.generation, manual.generation) == (1, 2, 3)


async def test_transcript_words_rollback_with_transcript(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.transcription import worker

    message = await seed(pg_factory)
    transition = worker.record_transition

    async def fail_completion(session: AsyncSession, meeting: Meeting, event: str, **kwargs: Any) -> Any:
        if event == "transcription_completed":
            await session.flush()
            raise RuntimeError("synthetic persistence failure")
        return await transition(session, meeting, event, **kwargs)

    monkeypatch.setattr(worker, "record_transition", fail_completion)
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        await _process_transcription(message, pg_factory)
    async with pg_factory() as session:
        for model in (Transcript, TranscriptWord, SpeechTurn, StateHistory):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_word_assignments_rollback_with_revision(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = await transcribe(pg_factory, await seed(pg_factory))
    complete = DiarizationRepository.complete_revision

    async def fail_completion(self: DiarizationRepository, *args: Any, **kwargs: Any) -> Diarization:
        await complete(self, *args, **kwargs)
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(DiarizationRepository, "complete_revision", fail_completion)
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        await _process_diarization(message, pg_factory)
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WordSpeakerAssignment)) == 0
        assert await session.scalar(select(func.count()).select_from(Speaker)) == 0
        assert (await session.scalars(select(Diarization))).one().diarization_state == "failed"
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 0


async def test_reserved_revision_timeout_and_completion_preserve_previous_revision(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = await seed(pg_factory)
    await _process_diarization(await transcribe(pg_factory, message), pg_factory)
    repo = DiarizationRepository(pg_factory)
    async with pg_factory() as session, session.begin():
        transcript = (await session.scalars(select(Transcript))).one()
        previous_assignments = {
            (a.word_id, a.speaker_id, a.state) for a in await session.scalars(select(WordSpeakerAssignment))
        }
        first = (await session.scalars(select(Diarization))).one()
        attempt = await repo.reserve_next_revision(session, message["meeting_id"], transcript.id)
        assert attempt.processing_revision == 2
    store = AsyncMock()
    store.inspect.return_value = "available"
    monkeypatch.setattr("app.diarization.worker.create_object_store", lambda: store)
    engines.slot_timeout_s = 0.1
    reserved_message = {"meeting_id": message["meeting_id"], "processing_revision": 2}
    async with engine_slot(pg_factory.kw["bind"], kind="test-holder"):
        with pytest.raises(EngineSlotTimeout):
            await _process_diarization(reserved_message, pg_factory)
    await _process_diarization(reserved_message, pg_factory)
    await _process_diarization(reserved_message, pg_factory)
    async with pg_factory() as session:
        assert {
            (a.word_id, a.speaker_id, a.state)
            for a in await session.scalars(
                select(WordSpeakerAssignment).where(
                    WordSpeakerAssignment.diarization_id == first.id,
                )
            )
        } == previous_assignments
        assert await session.scalar(select(func.count()).select_from(WordSpeakerAssignment)) == 2 * len(WORDS)
        requests = list(await session.scalars(select(SummaryRequestOutbox).order_by(SummaryRequestOutbox.generation)))
        assert [request.generation for request in requests] == [1, 2]
    assert engines.calls == ["transcription", "diarization", "diarization"]


@pytest.mark.parametrize("kind", ["transcription", "diarization"])
async def test_slot_timeout_does_not_release_a_newer_processing_generation(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    message = await seed(pg_factory)
    if kind == "diarization":
        message = await transcribe(pg_factory, message)
    engines.slot_timeout_s = 0.5
    started = asyncio.Event()

    @asynccontextmanager
    async def waiting_slot(engine: AsyncEngine, *, kind: str, timeout_s: float) -> AsyncIterator[None]:
        started.set()
        async with engine_slot(engine, kind=kind, poll_s=0.01, timeout_s=engines.slot_timeout_s):
            yield

    monkeypatch.setattr(f"app.{kind}.worker.engine_slot", waiting_slot)
    process = _process_transcription if kind == "transcription" else _process_diarization
    async with engine_slot(pg_factory.kw["bind"], kind="test-holder"):
        task = asyncio.create_task(process(message, pg_factory))
        await asyncio.wait_for(started.wait(), timeout=5)
        async with pg_factory() as session, session.begin():
            claim = await session.get(MeetingProcessingClaim, message["meeting_id"])
            assert claim is not None
            claim.generation += 1
            claim.claim_id, claim.claim_kind = "newer-job", "transcription"
        with pytest.raises(EngineSlotTimeout):
            await task
    async with pg_factory() as session:
        claim = await session.get(MeetingProcessingClaim, message["meeting_id"])
        assert claim is not None
        assert (claim.generation, claim.claim_id, claim.claim_kind) == (
            message["generation"] + 1,
            "newer-job",
            "transcription",
        )
    await process(message, pg_factory)
    assert engines.calls == ([] if kind == "transcription" else ["transcription"])


def test_worker_delivery_budget_is_below_broker_deadline() -> None:
    from app.infra.engine_slot import BROKER_CONSUMER_TIMEOUT_S, ENGINE_CALL_TIMEOUT_S, SLOT_WAIT_TIMEOUT_S

    assert SLOT_WAIT_TIMEOUT_S > 0 and ENGINE_CALL_TIMEOUT_S >= 1025
    assert SLOT_WAIT_TIMEOUT_S + ENGINE_CALL_TIMEOUT_S + 300 < BROKER_CONSUMER_TIMEOUT_S


async def test_publication_failure_rolls_back_generation_and_redelivery_recovers(
    pg_factory: Factory,
    engines: Engines,
) -> None:
    message = await seed(pg_factory)
    queue = AsyncMock()
    queue.publish.side_effect = ConnectionError("synthetic closed channel")
    with pytest.raises(ConnectionError):
        await _process_transcription(message, pg_factory, queue)
    async with pg_factory() as session:
        claim = await session.get(MeetingProcessingClaim, message["meeting_id"])
        assert claim is not None and claim.generation == message["generation"]
        assert claim.claim_id == message["job_id"]
        assert await session.scalar(select(func.count()).select_from(Transcript)) == 1
    queue.publish.side_effect = None
    await _process_transcription(message, pg_factory, queue)
    await _process_transcription(message, pg_factory, queue)
    assert queue.publish.await_count == 2
    assert engines.calls == ["transcription"]
    await _process_diarization(queue.publish.await_args.args[1], pg_factory)
    async with pg_factory() as session:
        assert (await session.scalars(select(Diarization))).one().diarization_state == "completed"


async def test_legacy_transition_precedes_slot_wait(pg_factory: Factory, engines: Engines) -> None:
    message = await seed(pg_factory)
    async with pg_factory() as session, session.begin():
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None
        meeting.process_state = "recording"
    engines.slot_timeout_s = 0.1
    async with engine_slot(pg_factory.kw["bind"], kind="test-holder"):
        with pytest.raises(EngineSlotTimeout):
            await _process_transcription(message, pg_factory)
    async with pg_factory() as session:
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None and meeting.process_state == "transcribing"
        assert (await session.scalars(select(StateHistory.state))).one() == "transcribing"


async def test_exhausted_slot_retries_mark_transcription_failed(pg_factory: Factory, engines: Engines) -> None:
    from app.transcription.worker import start_worker as start_transcription

    message = await seed(pg_factory)
    queue = AsyncMock()
    await start_transcription(queue, pg_factory)
    handlers = {call.args[0]: call.args[1] for call in queue.subscribe.await_args_list}
    engines.slot_timeout_s = 0.1
    async with engine_slot(pg_factory.kw["bind"], kind="test-holder"):
        with pytest.raises(EngineSlotTimeout):
            await handlers["transcribe"](message)
    await handlers["transcribe.failed"](message)
    await handlers["transcribe.failed"](message)
    async with pg_factory() as session:
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None and meeting.process_state == "failed"
        assert meeting.failure_cause == "processing_retries_exhausted"
        assert await session.scalar(select(func.count()).select_from(StateHistory)) == 1
    assert engines.calls == []


async def test_real_broker_redelivery_after_channel_closed_before_next_step(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infra.queue_rabbitmq import RabbitMQJobQueue
    from app.transcription.worker import start_worker as start_transcription

    url = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not url:
        pytest.skip("SAURI_QA_RABBITMQ_URL required; publication recovery also covered without broker")
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-u35-signing-key-at-least-32-bytes")
    monkeypatch.delenv("QUEUE_DLX_EXCHANGE", raising=False)
    message = await seed(pg_factory)
    first, restarted = RabbitMQJobQueue(url), RabbitMQJobQueue(url)
    await first.connect()
    failed_publication = asyncio.Event()

    async def close_before_publish(topic: str, payload: dict[str, Any]) -> None:
        assert topic == "diarize"
        assert first._channel is not None
        await first._channel.close()
        failed_publication.set()
        raise ConnectionError("synthetic closed channel")

    original_publish = first.publish
    monkeypatch.setattr(first, "publish", close_before_publish)
    try:
        await start_transcription(first, pg_factory)
        await original_publish("transcribe", message)
        await asyncio.wait_for(failed_publication.wait(), timeout=20)
        await first.disconnect()
        await restarted.connect()
        received: list[dict[str, Any]] = []
        complete = asyncio.Event()

        async def diarize(payload: dict[str, Any]) -> None:
            await _process_diarization(payload, pg_factory)
            received.append(payload)
            complete.set()

        await restarted.subscribe("diarize", diarize)
        await start_transcription(restarted, pg_factory)
        await asyncio.wait_for(complete.wait(), timeout=30)
        assert len(received) == 1 and received[0]["generation"] == message["generation"] + 1
        assert engines.calls == ["transcription", "diarization"]
        async with pg_factory() as session:
            assert await session.scalar(select(func.count()).select_from(Transcript)) == 1
            assert (await session.scalars(select(Diarization))).one().diarization_state == "completed"
    finally:
        await first.disconnect()
        await restarted.disconnect()


async def test_real_broker_slot_exhaustion_reaches_terminal_state(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infra.queue_rabbitmq import RabbitMQJobQueue
    from app.transcription.worker import start_worker as start_transcription

    url = os.environ.get("SAURI_QA_RABBITMQ_URL")
    if not url:
        pytest.skip("SAURI_QA_RABBITMQ_URL required; terminal handler also covered without broker")
    monkeypatch.setenv("QUEUE_MESSAGE_SIGNING_KEY", "synthetic-u35-signing-key-at-least-32-bytes")
    monkeypatch.setenv("ASR_MAX_RETRIES", "1")
    monkeypatch.delenv("QUEUE_DLX_EXCHANGE", raising=False)
    engines.slot_timeout_s = 0.1
    message = await seed(pg_factory)
    queue = RabbitMQJobQueue(url)
    await queue.connect()
    try:
        await start_transcription(queue, pg_factory)
        async with engine_slot(pg_factory.kw["bind"], kind="test-holder"):
            await queue.publish("transcribe", message)
            async with asyncio.timeout(30):
                while True:
                    async with pg_factory() as session:
                        meeting = await session.get(Meeting, message["meeting_id"])
                        assert meeting is not None
                        if meeting.process_state == "failed":
                            assert meeting.failure_cause == "processing_retries_exhausted"
                            break
                    await asyncio.sleep(0.05)
        assert engines.calls == []
    finally:
        await queue.disconnect()


@pytest.mark.parametrize("has_default", [True, False])
async def test_failed_automatic_request_is_visible_and_retryable_via_existing_api(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
    has_default: bool,
) -> None:
    from fastapi import FastAPI, HTTPException
    from httpx import ASGITransport, AsyncClient

    from app.auth.dependencies import get_current_user
    from app.auth.schemas import AuthenticatedUser
    from app.summaries.outbox import dispatch_pending
    from app.summaries.router import router
    from app.templates.router import get_session

    message = await seed(pg_factory)
    diarization_message = await transcribe(pg_factory, message)
    if not has_default:
        async with pg_factory() as session, session.begin():
            owner = await session.get(User, message["owner_id"])
            assert owner is not None
            owner.default_summary_template_id = None
    with monkeypatch.context() as patch:
        patch.setattr("app.diarization.worker.accept_request", AsyncMock(side_effect=HTTPException(status_code=503)))
        await _process_diarization(diarization_message, pg_factory)
    queue = AsyncMock()
    assert await dispatch_pending(pg_factory, queue) == 0
    queue.publish.assert_not_awaited()

    app = FastAPI()
    app.include_router(router)

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with pg_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        id=message["owner_id"],
        email="synthetic@example.test",
        name="Synthetic",
        is_sales=True,
    )
    path = f"/api/v1/meetings/{message['meeting_id']}/summary-requests"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        latest = await client.get(path + "/latest")
        assert latest.status_code == 200
        failed = latest.json()
        assert failed["status"] == "failed"
        assert failed["failure_cause"] == ("request_failed" if has_default else "no_default_template")
        # A duplicate automatic delivery leaves the durable failure intact.
        await _process_diarization(diarization_message, pg_factory)
        retry = await client.post(path, json={})
        assert retry.status_code == 202
        assert retry.json()["status"] == "pending" and retry.json()["generation"] == 2
        assert retry.json()["event_id"] != failed["event_id"]
    async with pg_factory() as session:
        meeting = await session.get(Meeting, message["meeting_id"])
        assert meeting is not None and meeting.process_state == "completed"
        original = await session.get(SummaryRequestOutbox, failed["event_id"])
        assert original is not None and original.status == "failed"
        from uuid import NAMESPACE_URL, uuid5

        assert original.event_id == str(uuid5(NAMESPACE_URL, f"sauri:auto-summary:{message['meeting_id']}:1"))
        if not has_default:
            assert (original.template_id, original.template_version, original.instructions_snapshot) == (
                None,
                None,
                None,
            )
    assert engines.calls == ["transcription", "diarization"]


async def test_failed_request_migration_roundtrip_and_null_guard(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Connection
    from sqlalchemy.exc import IntegrityError

    path = Path(__file__).resolve().parents[2] / "alembic/versions/019_failed_summary_request.py"
    spec = importlib.util.spec_from_file_location("failed_summary_request", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def apply(connection: Connection, action: str) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, action)()

    engine = pg_factory.kw["bind"]
    async with engine.begin() as connection:
        await connection.run_sync(apply, "downgrade")
        await connection.run_sync(apply, "upgrade")
    message = await seed(pg_factory)
    diarization_message = await transcribe(pg_factory, message)
    async with pg_factory() as session, session.begin():
        owner = await session.get(User, message["owner_id"])
        assert owner is not None
        owner.default_summary_template_id = None
    monkeypatch.setattr(
        "app.diarization.worker.accept_request", AsyncMock(side_effect=RuntimeError("synthetic failure"))
    )
    await _process_diarization(diarization_message, pg_factory)
    with pytest.raises(IntegrityError):
        async with pg_factory() as session, session.begin():
            request = (await session.scalars(select(SummaryRequestOutbox))).one()
            request.status = "pending"
            await session.flush()
    with pytest.raises(RuntimeError, match="requests lack a template snapshot"):
        async with engine.begin() as connection:
            await connection.run_sync(apply, "downgrade")
    async with pg_factory() as session:
        request = (await session.scalars(select(SummaryRequestOutbox))).one()
        assert request.status == "failed" and request.failure_cause == "no_default_template"


@pytest.mark.parametrize("kind", ["transcription", "diarization", "summary"])
async def test_worker_enforces_hard_inference_budget(
    pg_factory: Factory,
    engines: Engines,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    message = await seed(pg_factory)
    if kind != "transcription":
        message = await transcribe(pg_factory, message)
    module = "summaries" if kind == "summary" else kind
    monkeypatch.setattr(f"app.{module}.worker.ENGINE_CALL_TIMEOUT_S", 0.001)
    if kind == "summary":
        await _process_diarization(message, pg_factory)
        consume = await consumer(pg_factory)
        with pytest.raises(TimeoutError):
            await consume(await summary_message(pg_factory, message["meeting_id"]))
    elif kind == "diarization":
        with pytest.raises(TimeoutError):
            await _process_diarization(message, pg_factory)
    else:
        await _process_transcription(message, pg_factory)
    assert engines.active == 0
    async with engine_slot(pg_factory.kw["bind"], kind="test-after-timeout", timeout_s=1):
        pass
    async with pg_factory() as session:
        if kind == "transcription":
            meeting = await session.get(Meeting, message["meeting_id"])
            assert meeting is not None and meeting.process_state == "failed"
            assert meeting.failure_cause == "engine_timeout"
        elif kind == "diarization":
            assert (await session.scalars(select(Diarization))).one().diarization_state == "failed"
        else:
            assert (await session.scalars(select(SummaryRequestOutbox))).one().failure_cause == "llm_unavailable"
