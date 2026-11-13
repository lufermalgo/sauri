"""Transactional persistence of versioned diarization and speaker review results."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.infra.models import (
    Diarization,
    Meeting,
    Speaker,
    SpeakerAssignment,
    SpeakerReview,
    SpeakerReviewItem,
)
from app.infra.queue import JobQueue


class DiarizationRepository:
    """The caller owns commits; publication is deliberately outside transactions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reserve_next_revision(
        self, session: AsyncSession, meeting_id: str, transcript_id: str,
        *, audio_unavailable: bool = False, reuse_terminal: bool = False,
    ) -> Diarization:
        """Serialize revisions on the Meeting row, including when no attempt exists yet.

        The caller must commit before publishing. Repeated reservation of a pending
        attempt returns the same row. Ordinary unversioned capture deliveries use
        reuse_terminal=True: their redelivery never authorizes a new revision.
        Explicit backfill calls use the default, so a completed generation can
        be followed by a new authorized revision.
        """
        meeting = await session.scalar(
            select(Meeting).where(Meeting.id == meeting_id).with_for_update()
        )
        if meeting is None:
            raise ValueError("meeting not found")
        latest = await session.scalar(
            select(Diarization).where(Diarization.meeting_id == meeting_id)
            .order_by(Diarization.processing_revision.desc()).limit(1)
        )
        if latest is not None and latest.transcript_id != transcript_id:
            raise ValueError("transcript does not match existing diarization")
        if latest is not None and latest.diarization_state in {"pending", "in_progress"}:
            if audio_unavailable and latest.diarization_state == "pending":
                latest.diarization_state = "not_reconstructible"
                latest.failure_cause = "audio_unavailable"
                latest.updated_at = datetime.now(UTC)
            return latest
        if latest is not None and (
            reuse_terminal or latest.diarization_state == "not_reconstructible"
        ):
            return latest
        now = datetime.now(UTC)
        attempt = Diarization(
            id=str(uuid.uuid4()), meeting_id=meeting_id, transcript_id=transcript_id,
            processing_revision=latest.processing_revision + 1 if latest else 1,
            is_legacy=False, provider=None, speaker_count=0,
            diarization_state="not_reconstructible" if audio_unavailable else "pending",
            failure_cause="audio_unavailable" if audio_unavailable else None,
            created_at=now, updated_at=now,
        )
        session.add(attempt)
        await session.flush()  # Constraint is a second guard behind the meeting row lock.
        return attempt

    async def publish_pending_revision(
        self, meeting_id: str, processing_revision: int, queue: JobQueue,
    ) -> bool:
        """Publish a committed pending attempt; retrying publication is safe."""
        async with self._session_factory() as session:
            pending = await session.scalar(
                select(Diarization.id).where(
                    Diarization.meeting_id == meeting_id,
                    Diarization.processing_revision == processing_revision,
                    Diarization.diarization_state == "pending",
                )
            )
        if pending is None:
            return False
        await queue.publish("diarize", {
            "meeting_id": meeting_id, "processing_revision": processing_revision,
        })
        return True

    async def claim_revision(
        self, session: AsyncSession, meeting_id: str, processing_revision: int,
    ) -> bool:
        """Exactly one delivery may transition a pending generation to in_progress."""
        result = await session.execute(
            update(Diarization).where(
                Diarization.meeting_id == meeting_id,
                Diarization.processing_revision == processing_revision,
                Diarization.diarization_state == "pending",
            ).values(diarization_state="in_progress", updated_at=datetime.now(UTC))
            .returning(Diarization.id)
        )
        return result.scalar_one_or_none() is not None

    async def fail_revision(
        self, session: AsyncSession, meeting_id: str, processing_revision: int,
    ) -> bool:
        result = await session.execute(
            update(Diarization).where(
                Diarization.meeting_id == meeting_id,
                Diarization.processing_revision == processing_revision,
                Diarization.diarization_state == "in_progress",
            ).values(diarization_state="failed", failure_cause="engine_failure",
                     updated_at=datetime.now(UTC)).returning(Diarization.id)
        )
        return result.scalar_one_or_none() is not None

    async def retry_failed_revision(
        self, session: AsyncSession, meeting_id: str, processing_revision: int,
    ) -> Diarization | None:
        """Explicit retry only: reset a retryable failure without allocating a revision.

        A normal queue redelivery never invokes this method. The caller commits
        before republishing the same meeting/revision pair.
        """
        attempt = await session.scalar(
            select(Diarization).where(
                Diarization.meeting_id == meeting_id,
                Diarization.processing_revision == processing_revision,
            ).with_for_update()
        )
        if attempt is None or attempt.diarization_state not in {"failed", "pending"}:
            return None
        if attempt.diarization_state == "failed":
            if attempt.failure_cause != "engine_failure":
                return None
            attempt.diarization_state = "pending"
            attempt.failure_cause = None
            attempt.updated_at = datetime.now(UTC)
            await session.flush()
        return attempt

    async def complete_revision(
        self, session: AsyncSession, meeting_id: str, processing_revision: int,
        provider: str, speakers: list[Speaker], assignments: list[SpeakerAssignment],
    ) -> Diarization:
        """Commit the generation, its new speaker keys, assignments and review together.

        Failed flushes roll back the enclosing transaction; a previous completed
        generation and its review are never overwritten by this operation.
        """
        attempt = await session.scalar(
            select(Diarization).where(
                Diarization.meeting_id == meeting_id,
                Diarization.processing_revision == processing_revision,
                Diarization.diarization_state == "in_progress",
            ).with_for_update()
        )
        if attempt is None:
            raise ValueError("revision is not claimed")
        attempt.provider = provider
        attempt.speaker_count = len(speakers)
        for speaker in speakers:
            speaker.diarization_id = attempt.id
            session.add(speaker)
        for assignment in assignments:
            assignment.diarization_id = attempt.id
            session.add(assignment)
        review = SpeakerReview(
            id=str(uuid.uuid4()), meeting_id=meeting_id,
            processing_revision=processing_revision,
            status="pending" if speakers else "complete", created_at=datetime.now(UTC),
        )
        session.add(review)
        for speaker in speakers:
            session.add(SpeakerReviewItem(
                id=str(uuid.uuid4()), review_id=review.id, speaker_key=speaker.id,
                current_label=speaker.label, excerpt_ref=None, disposition=None,
                chosen_label=None, attribution_state="uncertain", version=1,
            ))
        attempt.diarization_state = "completed"
        attempt.failure_cause = None
        attempt.updated_at = datetime.now(UTC)
        await session.flush()
        return attempt

    async def create(
        self, session: AsyncSession, diarization: Diarization,
        speakers: list[Speaker], assignments: list[SpeakerAssignment],
    ) -> Diarization:
        """Legacy direct-creation seam retained for existing repository callers."""
        session.add(diarization)
        session.add_all(speakers)
        session.add_all(assignments)
        return diarization

    async def get_by_meeting(self, meeting_id: str) -> Diarization | None:
        """Return only the latest completed generation, with its own children."""
        async with self._session_factory() as session:
            active: Diarization | None = await session.scalar(
                select(Diarization).where(
                    Diarization.meeting_id == meeting_id,
                    Diarization.diarization_state == "completed",
                ).order_by(Diarization.processing_revision.desc()).limit(1).options(
                    selectinload(Diarization.speakers), selectinload(Diarization.assignments),
                )
            )
            return active
