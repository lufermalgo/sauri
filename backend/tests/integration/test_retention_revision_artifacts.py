"""H1/#903: real PostgreSQL retention, FK ordering and source-bound isolation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Delete, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.database import Base
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    MeetingRecoveryOperation,
    MeetingRecoveryOutbox,
    MeetingSummary,
    ProcessedSummaryEvent,
    RecordingMediaSource,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewIdempotencyReceipt,
    SpeakerReviewItem,
    SpeechTurn,
    SummaryRequestOutbox,
    SummaryTemplate,
    Transcript,
    User,
)
from app.retention.worker import run_retention_deletion
from tests.integration.test_diarization_reservation_concurrency import pg as _pg

pg = _pg
NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
SOURCE_TABLES = {
    "transcripts", "speech_turns", "diarizations", "speakers", "speaker_assignments",
    "speaker_reviews", "speaker_review_items", "speaker_review_idempotency_receipts",
    "summary_request_outbox", "meeting_summaries",
}


async def seed(factory: async_sessionmaker[AsyncSession], expiry: str) -> None:
    async with factory() as session, session.begin():
        for owner in ("owner-a", "owner-b"):
            session.add(User(id=owner, email=f"{owner}@example.test", name="Synthetic owner",
                             password_hash="synthetic", is_sales=True, created_at=NOW))
        await session.flush()
        for tag, owner in (("expired", "owner-a"), ("same-owner", "owner-a"), ("foreign", "owner-b")):
            session.add(Meeting(id=f"{tag}-meeting", created_by=owner, meet_link="https://example.test/synthetic",
                                origin="link", process_state="completed", created_at=NOW))
            session.add(SummaryTemplate(id=f"{tag}-template", owner_user_id=owner, name="Synthetic template",
                                        instructions="Synthetic instructions", version=1,
                                        created_at=NOW, updated_at=NOW))
            await session.flush()
            session.add(Transcript(id=f"{tag}-transcript", meeting_id=f"{tag}-meeting", language="es",
                                   provider="synthetic", supports_turns=True, created_at=NOW,
                                   expires_at=NOW - timedelta(seconds=1) if tag == "expired" and expiry == "transcript"
                                   else NOW + timedelta(days=1)))
            session.add(SessionRecording(
                id=f"{tag}-recording", meeting_id=f"{tag}-meeting", idempotency_key=f"{tag}-upload",
                capture_origin="web_upload", audio_ref=f"synthetic/{tag}/audio.webm",
                video_ref=f"synthetic/{tag}/video.webm", duration_seconds=1, interrupted=False, finished_at=NOW,
                expires_at=NOW - timedelta(seconds=1) if tag == "expired" and expiry == "recording"
                else NOW + timedelta(days=1),
            ))
            session.add(MeetingProcessingClaim(meeting_id=f"{tag}-meeting", generation=3))
            # Recovery metadata is content-free and meeting-owned, not a source derivative.
            session.add(MeetingRecoveryOperation(
                id=f"{tag}-recovery", meeting_id=f"{tag}-meeting", actor_id=owner,
                idempotency_key=f"{tag}-digest", processing_generation=3, status="completed",
                created_at=NOW, updated_at=NOW,
            ))
            await session.flush()
            session.add(MeetingRecoveryOutbox(
                id=f"{tag}-outbox", operation_id=f"{tag}-recovery", topic="diarize", job_identifiers={},
                processing_generation=3, delivery_status="pending", attempts=0, created_at=NOW,
            ))
            session.add(SpeechTurn(id=f"{tag}-turn", transcript_id=f"{tag}-transcript", text="Synthetic source.",
                                   start_ms=0, end_ms=1000, sequence=1))
            for kind in ("audio", "video"):
                session.add(RecordingMediaSource(
                    id=f"{tag}-{kind}", recording_id=f"{tag}-recording", kind=kind,
                    object_ref=f"synthetic/{tag}/{kind}.webm", quality_label="original",
                ))
            await session.flush()
            for revision, state in enumerate(("completed", "failed", "pending"), 1):
                key = f"{tag}-{revision}"
                projection = {"version": 2, "transcript_id": f"{tag}-transcript", "diarization_id": key,
                              "processing_revision": revision, "policy_version": "exclusive-source-v1",
                              "pieces": [{"source_turn_id": f"{tag}-turn", "char_start": 0, "char_end": 17,
                                          "speaker_id": None, "intervals": [{"start_ms": 0, "end_ms": 1000}]}]}
                session.add(Diarization(
                    id=key, meeting_id=f"{tag}-meeting", transcript_id=f"{tag}-transcript",
                    processing_revision=revision, is_legacy=False, diarization_state=state,
                    provider="synthetic", speaker_count=1 if revision == 1 else 0, created_at=NOW, updated_at=NOW,
                    presentation=projection if state == "completed" else None,
                    prepared_result={"provider": "synthetic", "speakers": [], "assignments": [],
                                     "presentation": projection} if state != "completed" else None,
                ))
            await session.flush()
            session.add(Speaker(id=f"{tag}-speaker", diarization_id=f"{tag}-1", raw_label="SPEAKER_00",
                                label="Speaker 1", sequence=1))
            session.add(SpeakerReview(id=f"{tag}-review", meeting_id=f"{tag}-meeting", processing_revision=1,
                                      status="complete", created_at=NOW))
            # Legal legacy review-only generation: it has no diarization FK.
            session.add(SpeakerReview(id=f"{tag}-legacy-review", meeting_id=f"{tag}-meeting", processing_revision=4,
                                      status="pending", created_at=NOW))
            session.add(SummaryRequestOutbox(
                event_id=f"{tag}-event", meeting_id=f"{tag}-meeting", transcript_id=f"{tag}-transcript",
                template_id=f"{tag}-template", template_version=1, instructions_snapshot="Synthetic instructions",
                generation=1, status="succeeded",
            ))
            session.add(ProcessedSummaryEvent(event_id=f"{tag}-event", meeting_id=f"{tag}-meeting", completed_at=NOW))
            session.add(MeetingSummary(
                id=f"{tag}-summary", event_id=f"{tag}-event", meeting_id=f"{tag}-meeting",
                transcript_id=f"{tag}-transcript", template_id=f"{tag}-template", template_version=1,
                generation=1, topic="Synthetic topic", key_points_json='["Synthetic point"]',
                created_at=NOW, updated_at=NOW,
            ))
            await session.flush()
            session.add(SpeakerAssignment(id=f"{tag}-assignment", diarization_id=f"{tag}-1", turn_id=f"{tag}-turn",
                                          speaker_id=f"{tag}-speaker", overlap_ms=1000))
            session.add(SpeakerReviewItem(id=f"{tag}-item", review_id=f"{tag}-review", speaker_key=f"{tag}-speaker",
                                         current_label="Speaker 1", chosen_label="Synthetic name", disposition="named",
                                         attribution_state="uncertain", version=2))
            await session.flush()
            session.add(SpeakerReviewIdempotencyReceipt(
                id=f"{tag}-receipt", review_id=f"{tag}-review", item_id=f"{tag}-item", idempotency_key="synthetic-key",
                request_hash="synthetic-hash", response={"labels_by_speaker_id": {f"{tag}-speaker": "Synthetic name"}},
            ))


async def snapshot(factory: async_sessionmaker[AsyncSession]) -> dict[str, list[dict[str, Any]]]:
    async with factory() as session:
        return {table.name: [dict(row) for row in (await session.execute(
            select(table).order_by(*table.primary_key)
        )).mappings()] for table in Base.metadata.sorted_tables}


def expected_snapshot(before: dict[str, list[dict[str, Any]]], expiry: str) -> dict[str, list[dict[str, Any]]]:
    deleted_tables = SOURCE_TABLES | (
        {"session_recordings", "recording_media_sources"} if expiry == "recording" else set()
    )
    return {name: [row for row in rows if name not in deleted_tables or not str(
        row.get("id", row.get("event_id", ""))
    ).startswith("expired-")] for name, rows in before.items()}


@pytest.mark.parametrize("expiry", ["recording", "transcript"])
async def test_expiry_removes_all_revision_artifacts_and_only_the_origin(
    pg: async_sessionmaker[AsyncSession], expiry: str,
) -> None:
    await seed(pg, expiry)
    before = await snapshot(pg)
    store = AsyncMock()
    async with pg() as session:
        # Loaded source relationships must not produce ORM NULL updates on delete.
        if expiry == "transcript":
            transcript = await session.get(Transcript, "expired-transcript")
            assert transcript is not None
            await session.refresh(transcript, ["turns"])
        await run_retention_deletion(session, store, NOW)
    assert await snapshot(pg) == expected_snapshot(before, expiry)
    if expiry == "recording":
        assert [call.args[0] for call in store.delete.await_args_list] == [
            "synthetic/expired/audio.webm", "synthetic/expired/video.webm"]
    else:
        store.delete.assert_not_awaited()
    async with pg() as session:
        await run_retention_deletion(session, store, NOW)
    assert await snapshot(pg) == expected_snapshot(before, expiry)
    assert store.delete.await_count == (2 if expiry == "recording" else 0)


async def test_expired_recording_cleans_legacy_reviews_without_transcript(pg: async_sessionmaker[AsyncSession]) -> None:
    await seed(pg, "recording")
    async with pg() as session, session.begin():
        await session.execute(delete(Diarization).where(Diarization.transcript_id == "expired-transcript"))
        await session.execute(delete(Transcript).where(Transcript.id == "expired-transcript"))
    before = await snapshot(pg)
    assert any(row["id"] == "expired-legacy-review" for row in before["speaker_reviews"])
    async with pg() as session:
        await run_retention_deletion(session, AsyncMock(), NOW)
    assert await snapshot(pg) == expected_snapshot(before, "recording")


@pytest.mark.parametrize("expiry", ["recording", "transcript"])
async def test_commit_failure_restores_source_and_all_derivatives(
    pg: async_sessionmaker[AsyncSession], expiry: str,
) -> None:
    await seed(pg, expiry)
    before = await snapshot(pg)

    async def reject_commit(self: AsyncSession) -> None:
        await self.flush()
        assert await self.get(Transcript, "expired-transcript") is None
        assert not (await self.scalars(select(Diarization.id).where(
            Diarization.transcript_id == "expired-transcript"
        ))).all()
        raise RuntimeError("synthetic commit failure")

    async with pg() as session:
        with patch.object(AsyncSession, "commit", reject_commit), pytest.raises(
            RuntimeError, match="synthetic commit failure"
        ):
            await run_retention_deletion(session, AsyncMock(), NOW)
        await session.rollback()
    assert await snapshot(pg) == before
    async with pg() as session:
        await run_retention_deletion(session, AsyncMock(), NOW)
    assert await snapshot(pg) == expected_snapshot(before, expiry)


@pytest.mark.parametrize("expiry", ["recording", "transcript"])
async def test_failure_after_child_deletes_rolls_back_and_retry_is_idempotent(
    pg: async_sessionmaker[AsyncSession], expiry: str,
) -> None:
    await seed(pg, expiry)
    before = await snapshot(pg)
    execute = AsyncSession.execute

    async def fail_source_delete(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(statement, Delete) and statement.table.compare(Transcript.__table__):
            # Real child deletion must have happened in this same transaction.
            assert not (await execute(self, select(Diarization.id).where(
                Diarization.transcript_id == "expired-transcript"
            ))).scalars().all()
            raise RuntimeError("synthetic failure before deleting source")
        return await execute(self, statement, *args, **kwargs)

    store = AsyncMock()
    async with pg() as session:
        with patch.object(AsyncSession, "execute", fail_source_delete), pytest.raises(
            RuntimeError, match="synthetic failure before deleting source"
        ):
            await run_retention_deletion(session, store, NOW)
        await session.rollback()
    assert await snapshot(pg) == before
    # Object-store deletions cannot roll back; retrying delete remains idempotent.
    async with pg() as session:
        await run_retention_deletion(session, store, NOW)
    after = await snapshot(pg)
    assert after == expected_snapshot(before, expiry)
    async with pg() as session:
        await run_retention_deletion(session, store, NOW)
    assert await snapshot(pg) == after
