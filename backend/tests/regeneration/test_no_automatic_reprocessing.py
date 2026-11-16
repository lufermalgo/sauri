"""#1053: once a stage's output exists, nothing automatic computes it again.

Real PostgreSQL, real workers, real claims. Only the engines and the broker are synthetic.
Every replay below must acknowledge without engine calls and without writing new work.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.diarization.worker import _process_diarization
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    MeetingSummary,
    RegenerationOperation,
    SessionRecording,
    SummaryRequestOutbox,
    Transcript,
    TranscriptWord,
)
from app.summaries.outbox import dispatch_pending
from app.transcription.worker import _process_transcription
from tests.diarization.test_pipeline_workers import (
    Engines,
    Factory,
    consumer,
    seed,
    summary_message,
    transcribe,
)

pytest_plugins = ("tests.diarization.test_pipeline_workers",)  # shared disposable PG and synthetic engines


async def finished_pipeline(factory: Factory) -> dict[str, Any]:
    """One ordinary run: transcription, speakers and the automatic first summary."""
    message = await seed(factory)
    diarization_message = await transcribe(factory, dict(message))
    await _process_diarization(dict(diarization_message), factory)
    consume = await consumer(factory)
    summarize = await summary_message(factory, message["meeting_id"])
    await consume(dict(summarize))
    return {"transcribe": message, "diarize": diarization_message, "summarize": summarize, "consume": consume}


async def counts(factory: Factory) -> dict[str, int]:
    tables = (Transcript, TranscriptWord, Diarization, SummaryRequestOutbox, MeetingSummary, RegenerationOperation)
    async with factory() as session:
        found = {t.__tablename__: int(await session.scalar(select(func.count()).select_from(t)) or 0) for t in tables}
        claim = await session.scalar(select(MeetingProcessingClaim))
        meeting = await session.scalar(select(Meeting))
        assert claim is not None and meeting is not None
        found["generation"] = claim.generation
        found[f"state:{meeting.process_state}"] = 1
        return found


async def test_replaying_every_message_of_a_finished_pipeline_does_no_work(
    pg_factory: Factory, engines: Engines
) -> None:
    run = await finished_pipeline(pg_factory)
    before, calls = await counts(pg_factory), list(engines.calls)
    assert calls == ["transcription", "diarization", "summary"]
    queue = AsyncMock()

    # Broker redelivery and duplicates of each stage's own message. Each drops with one info line.
    with patch("app.transcription.worker.logger") as transcription_log, \
            patch("app.diarization.worker.logger") as diarization_log, \
            patch("app.summaries.worker.logger") as summary_log:
        await _process_transcription(dict(run["transcribe"]), pg_factory, queue)
        await _process_transcription({**run["transcribe"], "job_id": str(uuid4())}, pg_factory, queue)
        # The legacy-shaped message without any fence.
        bare = {key: run["transcribe"][key] for key in ("meeting_id", "owner_id", "recording_id", "audio_ref")}
        await _process_transcription(bare, pg_factory, queue)
        await _process_diarization(dict(run["diarize"]), pg_factory)
        await _process_diarization({"meeting_id": run["diarize"]["meeting_id"], "processing_revision": 1}, pg_factory)
        await run["consume"](dict(run["summarize"]))
    for log in (transcription_log, diarization_log, summary_log):
        assert any("stage_complete" in str(call.args[0]) for call in log.info.call_args_list)

    queue.publish.assert_not_awaited()
    assert engines.calls == calls
    assert await counts(pg_factory) == before


async def test_restart_recovery_and_the_outbox_publish_nothing_for_settled_work(
    pg_factory: Factory, engines: Engines
) -> None:
    run = await finished_pipeline(pg_factory)
    queue = AsyncMock()
    assert await dispatch_pending(pg_factory, queue) == 0  # restart after everything was delivered
    async with pg_factory() as session, session.begin():
        request = (await session.scalars(select(SummaryRequestOutbox))).one()
        assert request.status == "succeeded"
        request.delivered_at = None  # a crash between broker confirmation and the delivery mark
    assert await dispatch_pending(pg_factory, queue) == 0
    queue.publish.assert_not_awaited()
    await run["consume"](dict(run["summarize"]))
    assert engines.calls == ["transcription", "diarization", "summary"]


async def test_a_second_upload_attempt_never_starts_work(pg_factory: Factory, engines: Engines) -> None:
    from sqlalchemy.exc import IntegrityError, InvalidRequestError

    from app.ingestion.schemas import IngestionData
    from app.ingestion.service import process_ingestion

    run = await finished_pipeline(pg_factory)
    meeting_id, owner_id = run["transcribe"]["meeting_id"], run["transcribe"]["owner_id"]
    async with pg_factory() as session:
        recording = (await session.scalars(select(SessionRecording))).one()
        key = recording.idempotency_key
    data = IngestionData(
        meeting_id=meeting_id, idempotency_key=key, capture_origin="web_upload", duration_seconds=6,
        video_presence="absent",
    )
    before = await counts(pg_factory)
    async with pg_factory() as session, session.begin():
        _, is_new = await process_ingestion(session, data, "other.webm", None, owner_id)
    assert is_new is False  # the route publishes only for a new recording
    other = data.model_copy(update={"idempotency_key": "another-key"})
    with pytest.raises((IntegrityError, InvalidRequestError)):  # one recording per meeting
        async with pg_factory() as session, session.begin():
            await process_ingestion(session, other, "other.webm", None, owner_id)
    assert await counts(pg_factory) == before and engines.calls == ["transcription", "diarization", "summary"]


async def test_request_join_on_a_finished_meeting_publishes_nothing(pg_factory: Factory, engines: Engines) -> None:
    from app.meetings.service import request_join

    run = await finished_pipeline(pg_factory)
    queue = AsyncMock()
    async with pg_factory() as session, session.begin():
        result = await request_join(session, run["transcribe"]["meeting_id"], queue)
    assert result.successful is False
    queue.publish.assert_not_awaited()


async def test_review_save_default_template_change_and_retention_start_nothing(
    pg_factory: Factory, engines: Engines
) -> None:
    from datetime import UTC, datetime

    from app.meetings.service import delete_meeting  # noqa: F401  (documents that deletion is explicit)
    from app.meetings.speaker_review_service import SpeakerReviewService
    from app.retention.worker import run_retention_deletion
    from app.templates.service import set_default_template

    run = await finished_pipeline(pg_factory)
    owner, meeting = run["transcribe"]["owner_id"], run["transcribe"]["meeting_id"]
    before = await counts(pg_factory)
    queue = AsyncMock()

    async with pg_factory() as session, session.begin():
        review = await SpeakerReviewService(session).get_active_review(owner, meeting)
        assert review is not None and review["items"]
        outcome = await SpeakerReviewService(session).record_disposition(
            owner, meeting, str(review["revision_id"]), review["items"][0]["speaker_id"],
            {"disposition": "named", "label": "Ana", "expected_version": 1, "idempotency_key": "k"}, 1,
        )
        assert outcome["outcome"] == "apply"
    async with pg_factory() as session, session.begin():
        await set_default_template(session, owner, run["summarize"]["template_id"])
    async with pg_factory() as session:
        store = AsyncMock()
        await run_retention_deletion(session, store, datetime.now(UTC))  # nothing has expired
        store.delete.assert_not_awaited()
    await dispatch_pending(pg_factory, queue)

    queue.publish.assert_not_awaited()
    assert await counts(pg_factory) == before and engines.calls == ["transcription", "diarization", "summary"]


async def test_an_automatic_summary_is_only_ever_the_first_one(pg_factory: Factory, engines: Engines) -> None:
    from app.summaries.service import accept_request

    run = await finished_pipeline(pg_factory)
    meeting, owner = run["transcribe"]["meeting_id"], run["transcribe"]["owner_id"]
    async with pg_factory() as session, session.begin():
        again = await accept_request(session, meeting, owner, None, processing_revision=2)
    assert again.event_id == run["summarize"]["event_id"]
    async with pg_factory() as session:
        assert await session.scalar(select(func.count()).select_from(SummaryRequestOutbox)) == 1
