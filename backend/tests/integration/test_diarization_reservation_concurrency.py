"""T9 #648: PostgreSQL row locks, redelivery, atomic publication and isolation.

Run only against a dedicated disposable PostgreSQL database; never SQLite.
"""

import asyncio
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from unittest.mock import call as mock_call

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.diarization.diarization_engine import DiarizationCapabilities, DiarizationResult, SpeakerSegment
from app.diarization.repository import DiarizationRepository
from app.diarization.worker import _process_diarization
from app.infra.database import Base
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingProcessingClaim,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
    Transcript,
)
from app.infra.object_store import ObjectStore


@pytest.fixture
def available_audio() -> Iterator[AsyncMock]:
    """Keep synthetic media local; PostgreSQL transactions remain real."""
    store = AsyncMock(spec=ObjectStore)
    store.inspect.return_value = "available"
    with patch("app.diarization.worker.create_object_store", return_value=store):
        yield store


@pytest.fixture
async def pg():
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url or not url.startswith("postgresql+asyncpg://") or "sauri_qa" not in url:
        pytest.fail("SAURI_QA_POSTGRES_URL must point to an isolated PostgreSQL QA database")
    engine = create_async_engine(url)
    assert engine.dialect.name == "postgresql"
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def seeded(pg):
    meeting_id, transcript_id, turn_id, recording_id = (str(uuid.uuid4()) for _ in range(4))
    now = datetime.now(UTC)
    async with pg() as session, session.begin():
        session.add(Meeting(id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij",
                            origin="link", process_state="completed", created_by="qa-user", created_at=now))
        session.add(Transcript(id=transcript_id, meeting_id=meeting_id, language="es", provider="qa",
                               supports_turns=True, created_at=now))
        session.add(SpeechTurn(id=turn_id, transcript_id=transcript_id, text="Synthetic text",
                               start_ms=0, end_ms=1000, sequence=1))
        session.add(SessionRecording(id=recording_id, meeting_id=meeting_id,
                                     idempotency_key=str(uuid.uuid4()), capture_origin="chrome_extension",
                                     audio_ref="qa/synthetic.webm", duration_seconds=2,
                                     interrupted=False, finished_at=now))
    return meeting_id, transcript_id, turn_id, recording_id


async def reserve(pg, meeting_id, transcript_id):
    repo = DiarizationRepository(pg)
    async with pg() as session, session.begin():
        attempt = await repo.reserve_next_revision(session, meeting_id, transcript_id)
        return attempt.processing_revision


@pytest.mark.asyncio
async def test_two_real_transactions_reserve_only_one_revision(pg, seeded):
    meeting_id, transcript_id, _, _ = seeded
    revisions = await asyncio.wait_for(asyncio.gather(
        reserve(pg, meeting_id, transcript_id), reserve(pg, meeting_id, transcript_id)
    ), timeout=10)
    assert revisions == [1, 1]
    async with pg() as session:
        attempts = (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id))).all()
        assert [(a.processing_revision, a.diarization_state) for a in attempts] == [(1, "pending")]


@pytest.mark.asyncio
async def test_commit_before_publish_and_redelivery_reuses_pending(pg, seeded):
    meeting_id, transcript_id, _, _ = seeded
    assert await reserve(pg, meeting_id, transcript_id) == 1  # crash after commit
    assert await reserve(pg, meeting_id, transcript_id) == 1
    repo = DiarizationRepository(pg)
    queue = AsyncMock()
    queue.publish.side_effect = RuntimeError("broker temporarily unavailable")
    with pytest.raises(RuntimeError, match="broker temporarily unavailable"):
        await repo.publish_pending_revision(meeting_id, 1, queue)
    queue.publish.side_effect = None
    assert await repo.publish_pending_revision(meeting_id, 1, queue)
    assert await repo.publish_pending_revision(meeting_id, 1, queue)
    assert queue.publish.await_count == 3
    for call in queue.publish.await_args_list:
        assert call.args == ("diarize", {"meeting_id": meeting_id, "processing_revision": 1})


@pytest.mark.asyncio
async def test_double_claim_one_winner_and_terminal_noop(pg, seeded):
    meeting_id, transcript_id, _, _ = seeded
    await reserve(pg, meeting_id, transcript_id)
    repo = DiarizationRepository(pg)

    async def claim():
        async with pg() as session, session.begin():
            return await repo.claim_revision(session, meeting_id, 1)

    assert sorted(await asyncio.wait_for(asyncio.gather(claim(), claim()), timeout=10)) == [False, True]
    assert await claim() is False
    async with pg() as session, session.begin():
        await repo.fail_revision(session, meeting_id, 1)
    assert await claim() is False


@pytest.mark.asyncio
async def test_atomic_generation_rollback_and_active_completed_survives_failure(pg, seeded):
    meeting_id, transcript_id, turn_id, _ = seeded
    repo = DiarizationRepository(pg)
    await reserve(pg, meeting_id, transcript_id)
    async with pg() as session, session.begin():
        assert await repo.claim_revision(session, meeting_id, 1)
    speaker = Speaker(
        id=str(uuid.uuid4()), diarization_id="unused", raw_label="SPEAKER_00",
        label="Speaker 1", sequence=1,
    )
    assignment = SpeakerAssignment(id=str(uuid.uuid4()), diarization_id="unused", turn_id=turn_id,
                                   speaker_id=speaker.id, overlap_ms=1000)
    async with pg() as session, session.begin():
        await repo.complete_revision(session, meeting_id, 1, "qa-engine", [speaker], [assignment])
    active = await repo.get_by_meeting(meeting_id)
    assert active is not None and active.processing_revision == 1
    assert await reserve(pg, meeting_id, transcript_id) == 2
    async with pg() as session, session.begin():
        assert await repo.claim_revision(session, meeting_id, 2)
    with pytest.raises(IntegrityError):
        async with pg() as session, session.begin():
            invalid = SpeakerAssignment(id=str(uuid.uuid4()), diarization_id="unused",
                                        turn_id=str(uuid.uuid4()), speaker_id=speaker.id, overlap_ms=1)
            await repo.complete_revision(session, meeting_id, 2, "qa-engine", [], [invalid])
    async with pg() as session, session.begin():
        await repo.fail_revision(session, meeting_id, 2)
    still_active = await repo.get_by_meeting(meeting_id)
    assert still_active is not None and still_active.id == active.id
    async with pg() as session:
        attempts = (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id)
                                          .order_by(Diarization.processing_revision))).all()
        assert [a.diarization_state for a in attempts] == ["completed", "failed"]
        assert len((await session.scalars(select(Speaker))).all()) == 1
        reviews = (await session.scalars(select(SpeakerReview).order_by(SpeakerReview.processing_revision))).all()
        assert len(reviews) == 1 and reviews[0].processing_revision == 1
        items = (await session.scalars(select(SpeakerReviewItem))).all()
        assert [(i.speaker_key, i.current_label, i.disposition) for i in items] == [
            (speaker.id, "Speaker 1", None)
        ]
        assert len((await session.scalars(select(SpeakerAssignment))).all()) == 1


@pytest.mark.asyncio
async def test_worker_redelivery_does_not_rerun_engine_or_mix_generations(pg, seeded, available_audio):
    meeting_id, transcript_id, _, _ = seeded
    await reserve(pg, meeting_id, transcript_id)
    engine = AsyncMock()
    engine.diarize.return_value = DiarizationResult(
        segments=[SpeakerSegment(raw_label="SPEAKER_00", start_ms=0, end_ms=1000)], speaker_count=1
    )
    engine.capabilities = MagicMock(return_value=DiarizationCapabilities(is_local=True, provider_name="qa-engine"))
    message = {"meeting_id": meeting_id, "processing_revision": 1}
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization(message, pg)
        await _process_diarization(message, pg)
    engine.diarize.assert_awaited_once()
    async with pg() as session:
        generations = (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id))).all()
        assert len(generations) == 1 and generations[0].diarization_state == "completed"
        assert len((await session.scalars(select(SpeakerReview))).all()) == 1

    # A fresh successful revision must have new keys and its own review;
    # matching provider raw labels never transfer a prior speaker identity.
    assert await reserve(pg, meeting_id, transcript_id) == 2
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization({"meeting_id": meeting_id, "processing_revision": 2}, pg)
    assert engine.diarize.await_count == 2
    assert available_audio.inspect.await_args_list == [mock_call("qa/synthetic.webm")] * 2
    async with pg() as session:
        generations = (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id)
                                              .order_by(Diarization.processing_revision))).all()
        reviews = (await session.scalars(select(SpeakerReview).where(SpeakerReview.meeting_id == meeting_id)
                                          .order_by(SpeakerReview.processing_revision))).all()
        speakers = (await session.scalars(select(Speaker).order_by(Speaker.diarization_id))).all()
        assert [g.diarization_state for g in generations] == ["completed", "completed"]
        assert [r.processing_revision for r in reviews] == [1, 2]
        assert len(speakers) == 2 and speakers[0].id != speakers[1].id
        assert {item.speaker_key for item in (await session.scalars(select(SpeakerReviewItem))).all()} == {
            speakers[0].id, speakers[1].id,
        }
        assert (await DiarizationRepository(pg).get_by_meeting(meeting_id)).id == generations[1].id


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_ordinary_unversioned_redelivery_without_processing_claim_is_idempotent(pg, seeded, concurrent):
    meeting_id, _, _, recording_id = seeded
    message = {"meeting_id": meeting_id, "owner_id": "qa-user", "recording_id": recording_id}
    engine = AsyncMock()
    engine.diarize.return_value = DiarizationResult(
        segments=[SpeakerSegment(raw_label="SPEAKER_00", start_ms=0, end_ms=1000)], speaker_count=1,
    )
    engine.capabilities = MagicMock(return_value=DiarizationCapabilities(is_local=True, provider_name="qa-engine"))
    async with pg() as session:
        assert (await session.scalars(select(MeetingProcessingClaim))).all() == []
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        if concurrent:
            entered_engine, release_engine = asyncio.Event(), asyncio.Event()

            async def diarize_while_second_delivery_arrives(*_args):
                entered_engine.set()
                await release_engine.wait()
                return engine.diarize.return_value

            engine.diarize.side_effect = diarize_while_second_delivery_arrives
            first = asyncio.create_task(_process_diarization(message, pg))
            try:
                await asyncio.wait_for(entered_engine.wait(), timeout=10)
                await asyncio.wait_for(_process_diarization(message, pg), timeout=10)
            finally:
                release_engine.set()
                await asyncio.wait_for(first, timeout=10)
        else:
            await _process_diarization(message, pg)
            await _process_diarization(message, pg)
    engine.diarize.assert_awaited_once()
    async with pg() as session:
        generations = (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id))).all()
        reviews = (await session.scalars(select(SpeakerReview).where(SpeakerReview.meeting_id == meeting_id))).all()
        speakers = (await session.scalars(select(Speaker))).all()
        assignments = (await session.scalars(select(SpeakerAssignment))).all()
        assert len(generations) == len(reviews) == len(speakers) == len(assignments) == 1
        assert generations[0].processing_revision == reviews[0].processing_revision == 1
        assert generations[0].diarization_state == "completed"
        assert (await session.scalars(select(SpeakerReviewItem).where(
            SpeakerReviewItem.review_id == reviews[0].id,
        ))).one().speaker_key == speakers[0].id


@pytest.mark.asyncio
async def test_legacy_completed_redelivery_preserves_identities_but_explicit_reprocess_can_advance(
    pg, seeded, available_audio,
):
    meeting_id, transcript_id, turn_id, recording_id = seeded
    now = datetime.now(UTC)
    diarization_id, speaker_id, review_id = (str(uuid.uuid4()) for _ in range(3))
    async with pg() as session, session.begin():
        session.add(Diarization(
            id=diarization_id, meeting_id=meeting_id, transcript_id=transcript_id,
            processing_revision=1, is_legacy=True, provider="legacy-engine",
            speaker_count=1, diarization_state="completed", created_at=now, updated_at=now,
        ))
        session.add(Speaker(
            id=speaker_id, diarization_id=diarization_id, raw_label="SPEAKER_00",
            label="Speaker 1", sequence=1,
        ))
        session.add(SpeakerAssignment(
            id=str(uuid.uuid4()), diarization_id=diarization_id, turn_id=turn_id,
            speaker_id=speaker_id, overlap_ms=None,
        ))
        session.add(SpeakerReview(
            id=review_id, meeting_id=meeting_id, processing_revision=1, status="pending", created_at=now,
        ))
        session.add(SpeakerReviewItem(
            id=str(uuid.uuid4()), review_id=review_id, speaker_key=speaker_id,
            current_label="Speaker 1", excerpt_ref=None, disposition=None,
            chosen_label=None, attribution_state="uncertain", version=1,
        ))
    engine = AsyncMock()
    engine.diarize.return_value = DiarizationResult(segments=[], speaker_count=0)
    engine.capabilities = MagicMock(return_value=DiarizationCapabilities(is_local=True, provider_name="qa-engine"))
    ordinary = {"meeting_id": meeting_id, "owner_id": "qa-user", "recording_id": recording_id}
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization(ordinary, pg)
        await _process_diarization(ordinary, pg)
    engine.diarize.assert_not_awaited()
    async with pg() as session:
        assert [d.id for d in (await session.scalars(select(Diarization))).all()] == [diarization_id]
        assert [s.id for s in (await session.scalars(select(Speaker))).all()] == [speaker_id]
        assert [r.id for r in (await session.scalars(select(SpeakerReview))).all()] == [review_id]

    assert await reserve(pg, meeting_id, transcript_id) == 2  # explicitly authorized reprocess
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization({"meeting_id": meeting_id, "processing_revision": 2}, pg)
    engine.diarize.assert_awaited_once()
    available_audio.inspect.assert_awaited_once_with("qa/synthetic.webm")
    async with pg() as session:
        assert len((await session.scalars(select(Diarization))).all()) == 2
        assert len((await session.scalars(select(SpeakerReview))).all()) == 2
        assert [s.id for s in (await session.scalars(select(Speaker))).all()] == [speaker_id]


@pytest.mark.asyncio
async def test_failed_ordinary_redelivery_requires_explicit_retry_of_same_revision(pg, seeded, available_audio):
    meeting_id, transcript_id, _, recording_id = seeded
    message = {"meeting_id": meeting_id, "owner_id": "qa-user", "recording_id": recording_id}
    engine = AsyncMock()
    engine.diarize.side_effect = RuntimeError("synthetic engine failure")
    engine.capabilities = MagicMock(return_value=DiarizationCapabilities(is_local=True, provider_name="qa-engine"))
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        with pytest.raises(RuntimeError, match="synthetic engine failure"):
            await _process_diarization(message, pg)
        await _process_diarization(message, pg)
    engine.diarize.assert_awaited_once()
    async with pg() as session:
        generations = (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id))).all()
        assert len(generations) == 1 and generations[0].diarization_state == "failed"
        assert generations[0].processing_revision == 1
        assert (await session.scalars(select(SpeakerReview))).all() == []

    repo = DiarizationRepository(pg)
    async with pg() as session, session.begin():
        retried = await repo.retry_failed_revision(session, meeting_id, 1)
        assert retried is not None and retried.processing_revision == 1
    assert await reserve(pg, meeting_id, transcript_id) == 1  # pending stays reusable
    queue = AsyncMock()
    assert await repo.publish_pending_revision(meeting_id, 1, queue)
    engine.diarize.side_effect = None
    engine.diarize.return_value = DiarizationResult(segments=[], speaker_count=0)
    with patch("app.diarization.worker.create_diarization_engine", return_value=engine):
        await _process_diarization(queue.publish.await_args.args[1], pg)
        await _process_diarization(queue.publish.await_args.args[1], pg)
    assert engine.diarize.await_count == 2  # first failure and one retry, not redelivery
    available_audio.inspect.assert_awaited_once_with("qa/synthetic.webm")
    async with pg() as session:
        generations = (await session.scalars(select(Diarization).where(Diarization.meeting_id == meeting_id))).all()
        reviews = (await session.scalars(select(SpeakerReview).where(SpeakerReview.meeting_id == meeting_id))).all()
        assert len(generations) == len(reviews) == 1
        assert generations[0].diarization_state == "completed"
        assert reviews[0].processing_revision == 1
