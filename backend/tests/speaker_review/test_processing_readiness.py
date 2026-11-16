"""Review readiness and atomic publication using current revisions, without clips.

Replaces contracts for the removed ProcessingPipeline/excerpt finalizer with
its production seams: DiarizationRepository and durable worker generation fencing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.diarization.repository import DiarizationRepository
from app.infra.models import Diarization, MeetingProcessingClaim, Speaker, SpeakerReview, SpeakerReviewItem
from app.infra.processing_claims import ClaimBusy, claim_worker_generation, verify_worker_generation
from app.meetings.speaker_review_service import SpeakerReviewService
from tests.meetings import test_transcript_word_turns as word_tests

migrated_url = word_tests.migrated_url
factory = word_tests.factory
Factory = word_tests.Factory


async def _pending(factory: Factory) -> tuple[str, int, str]:
    meeting, transcript = await word_tests._seed_meeting(factory)
    repo = DiarizationRepository(factory)
    async with factory() as session, session.begin():
        attempt = await repo.reserve_next_revision(session, meeting, transcript)
        return meeting, attempt.processing_revision, attempt.id


async def _complete(repo: DiarizationRepository, factory: Factory, meeting: str, revision: int, attempt: str) -> None:
    async with factory() as session, session.begin():
        await repo.complete_revision(session, meeting, revision, "synthetic", [Speaker(
            id=str(uuid.uuid4()), diarization_id=attempt, raw_label="SPEAKER_00", label="Speaker 1", sequence=1,
        )], [])


async def test_review_is_hidden_until_revision_is_complete(factory: Factory) -> None:
    meeting, revision, attempt = await _pending(factory)
    repo = DiarizationRepository(factory)
    async with factory() as session, session.begin():
        service = SpeakerReviewService(session)
        assert await service.get_active_review(word_tests.OWNER, meeting) is None
        assert await repo.claim_revision(session, meeting, revision)
        assert await service.get_active_review(word_tests.OWNER, meeting) is None
    await _complete(repo, factory, meeting, revision, attempt)
    async with factory() as session:
        review = await SpeakerReviewService(session).get_active_review(word_tests.OWNER, meeting)
        assert review is not None and review["revision_id"] == revision
        assert review["status"] == "pending" and len(review["items"]) == 1
        item = await session.scalar(select(SpeakerReviewItem).where(SpeakerReviewItem.review_id == review["review_id"]))
        assert item is not None and item.excerpt_ref is None


async def test_duplicate_claim_and_completion_do_not_duplicate_review(factory: Factory) -> None:
    meeting, revision, attempt = await _pending(factory)
    repo = DiarizationRepository(factory)
    async with factory() as session, session.begin():
        assert await repo.claim_revision(session, meeting, revision)
        assert not await repo.claim_revision(session, meeting, revision)
    await _complete(repo, factory, meeting, revision, attempt)
    with pytest.raises(ValueError, match="revision is not claimed"):
        await _complete(repo, factory, meeting, revision, attempt)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(SpeakerReview)
                                    .where(SpeakerReview.meeting_id == meeting)) == 1
        assert await session.scalar(select(func.count()).select_from(Speaker)
                                    .where(Speaker.diarization_id == attempt)) == 1


async def test_worker_generation_is_consumed_once_and_stale_delivery_is_fenced(factory: Factory) -> None:
    meeting, _, _ = await _pending(factory)
    async with factory() as session, session.begin():
        claim = MeetingProcessingClaim(meeting_id=meeting, generation=7)
        session.add(claim)
        await session.flush()
        binding = {"meeting_id": meeting, "generation": 7, "job_id": "synthetic-job", "kind": "diarization"}
        assert await claim_worker_generation(session, **binding)
        with pytest.raises(ClaimBusy):  # a second delivery meets the live lease and is deferred, not consumed
            await claim_worker_generation(session, **binding)
        assert await verify_worker_generation(session, **binding)
        claim.generation = 8
        await session.flush()
        assert not await verify_worker_generation(session, **binding)


async def test_expired_worker_claim_cannot_publish_and_is_taken_over_by_the_next_delivery(factory: Factory) -> None:
    meeting, _, _ = await _pending(factory)
    async with factory() as session, session.begin():
        session.add(MeetingProcessingClaim(meeting_id=meeting, generation=7, claim_kind="diarization",
                                          claim_id="synthetic-job",
                                          claim_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await session.flush()
        assert not await verify_worker_generation(session, meeting_id=meeting, generation=7,
                                                  job_id="synthetic-job", kind="diarization")
        holder = await claim_worker_generation(session, meeting_id=meeting, generation=7,
                                               job_id="synthetic-job", kind="diarization")
        assert holder and holder != "synthetic-job"
        assert not await verify_worker_generation(session, meeting_id=meeting, generation=7,
                                                  job_id="synthetic-job", kind="diarization")
        assert await verify_worker_generation(session, meeting_id=meeting, generation=7,
                                              job_id="synthetic-job", kind="diarization", holder=holder)


async def test_failed_publication_rolls_back_outputs_and_can_resume(factory: Factory) -> None:
    meeting, revision, attempt = await _pending(factory)
    repo = DiarizationRepository(factory)
    async with factory() as session, session.begin():
        assert await repo.claim_revision(session, meeting, revision)
    with pytest.raises(RuntimeError, match="synthetic publication failure"):
        async with factory() as session, session.begin():
            await repo.complete_revision(session, meeting, revision, "synthetic", [Speaker(
                id=str(uuid.uuid4()), diarization_id=attempt, raw_label="SPEAKER_00", label="Speaker 1", sequence=1,
            )], [])
            raise RuntimeError("synthetic publication failure")
    async with factory() as session:
        row = await session.get(Diarization, attempt)
        assert row is not None and row.diarization_state == "in_progress"
        assert await SpeakerReviewService(session).get_active_review(word_tests.OWNER, meeting) is None
        assert await session.scalar(select(func.count()).select_from(Speaker)
                                    .where(Speaker.diarization_id == attempt)) == 0
    await _complete(repo, factory, meeting, revision, attempt)
    async with factory() as session:
        assert await SpeakerReviewService(session).get_active_review(word_tests.OWNER, meeting) is not None
