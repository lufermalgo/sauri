"""#1053: explicit regeneration end to end through the real workers on PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.diarization.diarization_engine import DiarizationResult, SpeakerSegment
from app.diarization.worker import _process_diarization
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    MeetingSummary,
    RegenerationOperation,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
    SummaryRequestOutbox,
    Transcript,
    TranscriptWord,
    WordSpeakerAssignment,
)
from app.regeneration import service
from app.transcription.asr_engine import TranscriptionResult, TranscriptionSegment, TranscriptionWord
from app.transcription.worker import _process_transcription
from tests.diarization.test_pipeline_workers import Engines, Factory, consumer, seed, summary_message, transcribe

pytest_plugins = ("tests.diarization.test_pipeline_workers",)

NEW_WORDS = [
    TranscriptionWord("Hello", 0, 500, 0.9),
    TranscriptionWord(" there", 600, 1500, 0.9),
    TranscriptionWord(" good", 3100, 3600, 0.9),
    TranscriptionWord(" morning", 3700, 4800, 0.9),
]
NEW_SEGMENTS = [TranscriptionSegment("Hello there", 0, 2000), TranscriptionSegment("good morning", 3000, 5000)]
TWO_VOICES = [SpeakerSegment("A", 0, 2500), SpeakerSegment("B", 2500, 5200)]


class FakeStore:
    async def inspect(self, _: str) -> str:
        return "available"


@pytest.fixture(autouse=True)
def synthetic_object_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.diarization.worker.create_object_store", lambda: FakeStore())


def two_voice_engines(engines: Engines, diarization: list[SpeakerSegment] | None = None) -> None:
    async def transcribe_two(*_: Any) -> TranscriptionResult:
        async with engines.call("transcription"):
            return TranscriptionResult(segments=NEW_SEGMENTS, words=NEW_WORDS, language="en")

    async def diarize(*_: Any) -> DiarizationResult:
        async with engines.call("diarization"):
            segments = diarization or TWO_VOICES
            return DiarizationResult(segments=segments, speaker_count=len({s.raw_label for s in segments}))

    engines.transcribe = transcribe_two  # type: ignore[method-assign]
    engines.diarize = diarize  # type: ignore[method-assign]


async def pipeline(factory: Factory) -> dict[str, Any]:
    message = await seed(factory)
    diarization_message = await transcribe(factory, dict(message))
    await _process_diarization(dict(diarization_message), factory)
    consume = await consumer(factory)
    await consume(await summary_message(factory, message["meeting_id"]))
    return message


async def regenerate(
    factory: Factory, run: dict[str, Any], stage: str, *, cascade: bool = False
) -> service.Accepted:
    async with factory() as session, session.begin():
        return await service.request_regeneration(
            session, FakeStore(), meeting_id=run["meeting_id"], owner_id=run["owner_id"], stage=stage,  # type: ignore[arg-type]
            template_id=None, cascade=cascade, idempotency_key=None,
        )


async def op(factory: Factory, operation_id: str) -> RegenerationOperation:
    async with factory() as session:
        row = await session.get(RegenerationOperation, operation_id)
        assert row is not None
        return row


async def run_dispatch(factory: Factory, accepted: service.Accepted) -> AsyncMock:
    """Deliver the accepted operation's message to its worker and return the follow-up publications."""
    assert accepted.dispatch is not None
    queue = AsyncMock()
    if accepted.dispatch.topic == "transcribe":
        await _process_transcription(dict(accepted.dispatch.message), factory, queue)
    else:
        await _process_diarization(dict(accepted.dispatch.message), factory)
    return queue


async def stale(factory: Factory, meeting_id: str) -> list[str]:
    async with factory() as session:
        return await service.stale_stages(session, meeting_id)


async def test_regenerating_transcription_replaces_content_and_marks_the_rest_stale(
    pg_factory: Factory, engines: Engines
) -> None:
    two_voice_engines(engines)
    run = await pipeline(pg_factory)
    async with pg_factory() as session:
        transcript_id = (await session.scalars(select(Transcript.id))).one()
        old_summary = (await session.scalars(select(MeetingSummary))).one()
    engines.words = []  # not used by the replaced engine
    accepted = await regenerate(pg_factory, run, "transcription")
    assert accepted.operation.details == {"replaces": ["transcription"], "stale": ["speakers", "summary"]}
    async with pg_factory() as session:
        meeting = await session.get(Meeting, run["meeting_id"])
        assert meeting is not None and meeting.process_state == "transcribing"  # not "ready" while it runs

    async def transcribe_changed(*_: Any) -> TranscriptionResult:
        async with engines.call("transcription"):
            return TranscriptionResult(
                segments=[TranscriptionSegment("Hello again there", 0, 2200),
                          TranscriptionSegment("good day", 3000, 5000)],
                words=[TranscriptionWord("Hello", 0, 400), TranscriptionWord(" again", 450, 900),
                       TranscriptionWord(" there", 1000, 1800), TranscriptionWord(" good", 3200, 3800),
                       TranscriptionWord(" day", 3900, 4800)],
                language="en",
            )

    engines.transcribe = transcribe_changed  # type: ignore[method-assign]
    queue = await run_dispatch(pg_factory, accepted)
    queue.publish.assert_not_awaited()  # no cascade: nothing else starts by itself

    assert engines.calls == ["transcription", "diarization", "summary", "transcription"]
    finished = await op(pg_factory, accepted.operation.id)
    assert (finished.status, finished.failure_cause) == ("succeeded", None) and finished.finished_at is not None
    async with pg_factory() as session:
        assert (await session.scalars(select(Transcript.id))).one() == transcript_id  # identity kept
        meeting = await session.get(Meeting, run["meeting_id"])
        assert meeting is not None and meeting.process_state == "completed" and meeting.failure_cause is None
        words = list(await session.scalars(select(TranscriptWord.text).order_by(TranscriptWord.sequence)))
        assert words == ["Hello", " again", " there", " good", " day"]
        turns = list(await session.scalars(select(SpeechTurn).order_by(SpeechTurn.sequence)))
        assert [t.text for t in turns] == ["Hello again there", "good day"]
        # The previous speaker detection stays usable: new turns and words keep their speakers.
        latest = (await session.scalars(select(Diarization))).one()
        speakers = {s.id: s.raw_label for s in await session.scalars(select(Speaker))}
        by_turn = {a.turn_id: speakers[a.speaker_id] for a in await session.scalars(select(SpeakerAssignment))}
        assert [by_turn[t.id] for t in turns] == ["A", "B"]
        word_rows = (await session.scalars(
            select(WordSpeakerAssignment).join(TranscriptWord).order_by(TranscriptWord.sequence))).all()
        assert [speakers[str(w.speaker_id)] for w in word_rows] == ["A", "A", "A", "B", "B"]
        assert latest.diarization_state == "completed"
        # Nothing was recomputed or requested on its own.
        assert await session.scalar(select(func.count()).select_from(Diarization)) == 1
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 1
        assert (await session.scalars(select(MeetingSummary))).one().id == old_summary.id
    assert await stale(pg_factory, run["meeting_id"]) == ["speakers", "summary"]


async def test_cascade_runs_each_stage_in_order_one_turn_at_a_time(pg_factory: Factory, engines: Engines) -> None:
    two_voice_engines(engines)
    run = await pipeline(pg_factory)
    engines.calls.clear()
    accepted = await regenerate(pg_factory, run, "transcription", cascade=True)
    assert accepted.operation.details == {"replaces": ["transcription", "speakers", "summary"], "stale": []}

    queue = await run_dispatch(pg_factory, accepted)
    [(topic, message)] = [call.args for call in queue.publish.await_args_list]
    assert topic == "diarize" and message["processing_revision"] == 2
    parent = await op(pg_factory, accepted.operation.id)
    assert parent.status == "succeeded"
    async with pg_factory() as session:
        speakers_op = (await session.scalars(
            select(RegenerationOperation).where(RegenerationOperation.stage == "speakers"))).one()
    assert speakers_op.parent_operation_id == parent.id and speakers_op.status == "accepted"
    assert engines.calls == ["transcription"]  # the speakers have not started before their message is consumed

    await _process_diarization(dict(message), pg_factory)
    async with pg_factory() as session:
        summary_op = (await session.scalars(
            select(RegenerationOperation).where(RegenerationOperation.stage == "summary"))).one()
        assert summary_op.parent_operation_id == speakers_op.id and summary_op.status == "accepted"
        request = await session.get(SummaryRequestOutbox, summary_op.summary_event_id)
        assert request is not None and request.generation == 2 and request.status == "pending"
    assert engines.calls == ["transcription", "diarization"]

    consume = await consumer(pg_factory)
    assert summary_op.summary_event_id is not None
    await consume(await _event(pg_factory, summary_op.summary_event_id))
    assert engines.calls == ["transcription", "diarization", "summary"] and engines.peak == 1
    async with pg_factory() as session:
        statuses = {o.stage: o.status for o in await session.scalars(select(RegenerationOperation))}
        assert statuses == {"transcription": "succeeded", "speakers": "succeeded", "summary": "succeeded"}
        assert await session.scalar(select(func.count()).select_from(MeetingSummary)) == 2
    assert await stale(pg_factory, run["meeting_id"]) == []  # everything downstream was replaced


async def _event(factory: Factory, event_id: str) -> dict[str, Any]:
    async with factory() as session:
        request = await session.get(SummaryRequestOutbox, event_id)
        assert request is not None
        return {key: getattr(request, key) for key in (
            "event_id", "meeting_id", "transcript_id", "generation", "template_id", "template_version",
            "instructions_snapshot")}


async def test_speakers_regeneration_carries_names_only_where_it_is_safe(
    pg_factory: Factory, engines: Engines
) -> None:
    two_voice_engines(engines)
    run = await pipeline(pg_factory)
    async with pg_factory() as session, session.begin():
        items = {i.current_label: i for i in await session.scalars(select(SpeakerReviewItem))}
        items["Speaker 1"].disposition, items["Speaker 1"].chosen_label = "named", "Ana"
        items["Speaker 2"].disposition = "confirmed"
        review = (await session.scalars(select(SpeakerReview))).one()
        review.status = "complete"

    # Same two voices, different engine labels: each speaker maps one-to-one.
    two_voice_engines(engines, [SpeakerSegment("X", 0, 2500), SpeakerSegment("Y", 2500, 5200)])
    engines.calls.clear()
    accepted = await regenerate(pg_factory, run, "speakers")
    assert accepted.operation.details == {"replaces": ["speakers"], "stale": ["summary"]}
    await run_dispatch(pg_factory, accepted)
    assert engines.calls == ["diarization"]  # no summary was chained
    finished = await op(pg_factory, accepted.operation.id)
    assert finished.status == "succeeded"
    assert finished.details["carried_over"] == 2 and finished.details["needs_review"] is False  # type: ignore[index]
    async with pg_factory() as session:
        review = (await session.scalars(select(SpeakerReview).where(SpeakerReview.processing_revision == 2))).one()
        items = {i.current_label: i for i in await session.scalars(
            select(SpeakerReviewItem).where(SpeakerReviewItem.review_id == review.id))}
        assert (items["Speaker 1"].disposition, items["Speaker 1"].chosen_label) == ("named", "Ana")
        assert items["Speaker 2"].disposition == "confirmed" and items["Speaker 2"].chosen_label == "Speaker 2"
        assert review.status == "complete"
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 1
    assert await stale(pg_factory, run["meeting_id"]) == ["summary"]

    # One merged voice cannot be matched to either person: the review is pending, nothing is guessed.
    two_voice_engines(engines, [SpeakerSegment("Z", 0, 5200)])
    accepted = await regenerate(pg_factory, run, "speakers")
    await run_dispatch(pg_factory, accepted)
    finished = await op(pg_factory, accepted.operation.id)
    assert finished.details["carried_over"] == 0 and finished.details["needs_review"] is True  # type: ignore[index]
    assert finished.details["previous_revision"] == 2  # type: ignore[index]
    async with pg_factory() as session:
        reviews = {r.processing_revision: r.status for r in await session.scalars(select(SpeakerReview))}
        assert reviews == {1: "complete", 2: "complete", 3: "pending"}  # earlier revisions stay readable and untouched
        old = (await session.scalars(select(SpeakerReviewItem).join(SpeakerReview).where(
            SpeakerReview.processing_revision == 1, SpeakerReviewItem.current_label == "Speaker 1"))).one()
        assert old.chosen_label == "Ana"


async def test_failed_regeneration_keeps_every_previous_output(pg_factory: Factory, engines: Engines) -> None:
    two_voice_engines(engines)
    run = await pipeline(pg_factory)

    async def broken(*_: Any) -> Any:
        raise httpx.ConnectError("engine down")

    engines.transcribe = broken  # type: ignore[method-assign]
    accepted = await regenerate(pg_factory, run, "transcription")
    await run_dispatch(pg_factory, accepted)
    failed = await op(pg_factory, accepted.operation.id)
    assert (failed.status, failed.failure_cause) == ("failed", "engine_failed") and failed.finished_at is not None
    async with pg_factory() as session:
        meeting = await session.get(Meeting, run["meeting_id"])
        assert meeting is not None and (meeting.process_state, meeting.failure_cause) == ("completed", None)
        assert await session.scalar(select(func.count()).select_from(TranscriptWord)) == len(NEW_WORDS)
        assert await session.scalar(select(func.count()).select_from(MeetingSummary)) == 1
    assert await stale(pg_factory, run["meeting_id"]) == []  # a failure makes nothing stale

    engines.diarize = broken  # type: ignore[method-assign]
    accepted = await regenerate(pg_factory, run, "speakers")
    with pytest.raises(httpx.ConnectError):  # the broker retries; the retry is fenced below
        await run_dispatch(pg_factory, accepted)
    failed = await op(pg_factory, accepted.operation.id)
    assert (failed.status, failed.failure_cause) == ("failed", "engine_failure")
    async with pg_factory() as session:
        states = {d.processing_revision: d.diarization_state for d in await session.scalars(select(Diarization))}
        assert states == {1: "completed", 2: "failed"}  # the first revision is still the one in use
    calls = len(engines.calls)
    await _process_diarization(dict(accepted.dispatch.message), pg_factory)  # type: ignore[union-attr]
    assert len(engines.calls) == calls  # the redelivery of a failed run does nothing
    assert (await regenerate(pg_factory, run, "summary")).operation.status == "accepted"  # the meeting is free


async def test_workers_ignore_messages_without_a_valid_operation(pg_factory: Factory, engines: Engines) -> None:
    two_voice_engines(engines)
    run = await pipeline(pg_factory)
    first = await regenerate(pg_factory, run, "speakers")
    await run_dispatch(pg_factory, first)  # now succeeded
    transcription = await regenerate(pg_factory, run, "transcription")
    assert transcription.dispatch is not None
    calls = len(engines.calls)
    base = dict(transcription.dispatch.message)
    other_meeting = str(uuid4())
    bogus = [
        {**base, "operation_id": str(uuid4())},                         # unknown operation
        {**base, "operation_id": first.operation.id},                    # finished operation (speakers stage)
        {**base, "generation": base["generation"] - 1},                  # stale generation
        {**base, "generation": base["generation"] + 1},                  # generation from the future
        {**base, "operation_id": None},                                  # claim is owned by an operation
        {**{k: v for k, v in base.items() if k != "operation_id"}},
        {**base, "meeting_id": other_meeting},
    ]
    queue = AsyncMock()
    for message in bogus:
        await _process_transcription(message, pg_factory, queue)
    queue.publish.assert_not_awaited()
    assert len(engines.calls) == calls
    async with pg_factory() as session:
        claim = await session.get(MeetingProcessingClaim, run["meeting_id"])
        assert claim is not None and claim.claim_kind == "recovery" and claim.claim_id == transcription.operation.id
    # A speakers operation cannot drive the transcription worker, nor the other way around.
    speakers_message = {**base, "operation_id": first.operation.id}
    await _process_transcription(speakers_message, pg_factory, queue)
    assert len(engines.calls) == calls
    # The genuine message still works.
    await _process_transcription(base, pg_factory, queue)
    assert len(engines.calls) == calls + 1
    assert (await op(pg_factory, transcription.operation.id)).status == "succeeded"
    await _process_transcription(base, pg_factory, queue)  # its own redelivery
    assert len(engines.calls) == calls + 1


async def test_a_new_generation_fences_the_messages_of_an_older_one(pg_factory: Factory, engines: Engines) -> None:
    two_voice_engines(engines)
    message = await seed(pg_factory)
    diarize = await transcribe(pg_factory, dict(message))
    # Before speakers started, the owner explicitly regenerates them: the old diarize message is superseded.
    run = {"meeting_id": message["meeting_id"], "owner_id": message["owner_id"]}
    accepted = await regenerate(pg_factory, run, "speakers")
    await _process_diarization(dict(diarize), pg_factory)
    assert "diarization" not in engines.calls
    await run_dispatch(pg_factory, accepted)
    assert engines.calls.count("diarization") == 1
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 0


async def test_stale_operations_release_the_meeting(pg_factory: Factory, engines: Engines) -> None:
    two_voice_engines(engines)
    run = await pipeline(pg_factory)
    accepted = await regenerate(pg_factory, run, "transcription")
    assert await service.fail_stale_operations(pg_factory, stale_after=timedelta(hours=1)) == 0
    assert await service.fail_stale_operations(pg_factory, stale_after=timedelta(seconds=-1)) == 1
    failed = await op(pg_factory, accepted.operation.id)
    assert (failed.status, failed.failure_cause) == ("failed", "stale_operation")
    async with pg_factory() as session:
        meeting = await session.get(Meeting, run["meeting_id"])
        assert meeting is not None and meeting.process_state == "completed"
    calls = len(engines.calls)
    await run_dispatch(pg_factory, accepted)  # the late message of the abandoned run is dropped
    assert len(engines.calls) == calls
    assert (await regenerate(pg_factory, run, "speakers")).operation.status == "accepted"


async def test_a_failed_meeting_without_a_transcript_is_retried_by_regeneration(
    pg_factory: Factory, engines: Engines
) -> None:
    two_voice_engines(engines)
    run = await seed(pg_factory)
    async with pg_factory() as session, session.begin():
        meeting = await session.get(Meeting, run["meeting_id"])
        assert meeting is not None
        meeting.process_state, meeting.failure_cause = "failed", "engine_failure"
    accepted = await regenerate(pg_factory, run, "transcription")
    await run_dispatch(pg_factory, accepted)
    async with pg_factory() as session:
        meeting = await session.get(Meeting, run["meeting_id"])
        assert meeting is not None and (meeting.process_state, meeting.failure_cause) == ("completed", None)
        assert await session.scalar(select(func.count()).select_from(Transcript)) == 1
        assert await session.scalar(select(func.count()).select_from(Diarization)) == 0  # nothing chained
    assert (await op(pg_factory, accepted.operation.id)).status == "succeeded"


async def test_the_one_active_rule_is_enforced_by_the_database_too(pg_factory: Factory, engines: Engines) -> None:
    from sqlalchemy.exc import IntegrityError

    two_voice_engines(engines)
    run = await pipeline(pg_factory)
    await regenerate(pg_factory, run, "speakers")
    with pytest.raises(IntegrityError):
        async with pg_factory() as session, session.begin():
            session.add(RegenerationOperation(
                id=str(uuid4()), meeting_id=run["meeting_id"], stage="summary", status="running",
                requested_by=run["owner_id"], requested_at=datetime.now(UTC), cascade=False,
            ))
