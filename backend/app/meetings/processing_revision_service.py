"""Recording-scoped exact revision admission; the caller owns the transaction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    Meeting,
    ProcessingRevision,
    ProcessingRevisionOutbox,
    RecordingProcessingState,
    SessionRecording,
    SpeakerReview,
    SpeakerReviewItem,
)


async def lock_processing_state(
    session: AsyncSession, meeting_id: str, *, owner_id: str | None = None
) -> RecordingProcessingState | None:
    """Use the same serializing lock for admission and review GET.

    Lock the meeting before creating a missing state row: a first GET and a first
    admission cannot race on an absent row. The state row is then locked as well.
    """
    query = select(Meeting).where(Meeting.id == meeting_id)
    if owner_id is not None:
        query = query.where(Meeting.created_by == owner_id)
    meeting = await session.scalar(query.with_for_update())
    if meeting is None:
        return None
    recording = await session.scalar(select(SessionRecording).where(SessionRecording.meeting_id == meeting_id))
    if recording is None:
        return None
    state = await session.scalar(
        select(RecordingProcessingState).where(RecordingProcessingState.recording_id == recording.id).with_for_update()
    )
    if state is None:
        state = RecordingProcessingState(recording_id=recording.id)
        session.add(state)
        await session.flush()
    return state


async def visible_revision_id(session: AsyncSession, meeting_id: str) -> str | None:
    """Pin both legacy GETs to one visible revision, never to an in-flight row."""
    state = await session.scalar(
        select(RecordingProcessingState)
        .join(SessionRecording, SessionRecording.id == RecordingProcessingState.recording_id)
        .where(SessionRecording.meeting_id == meeting_id)
    )
    if state is None:
        return None
    # An empty ID deliberately matches no stage row: never fall through to a
    # candidate's rows when no active/compatibility revision is visible.
    return state.active_processing_revision_id or state.legacy_compatibility_revision_id or ""


class ProcessingRevisionService:
    """Admit one candidate, replay an exact request, or reject without displacement."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def admit_candidate(
        self, *, owner_id: str, recording_id: str, request_id: str, request_fingerprint: str
    ) -> ProcessingRevision:
        recording = await self._session.scalar(
            select(SessionRecording)
            .join(Meeting, Meeting.id == SessionRecording.meeting_id)
            .where(SessionRecording.id == recording_id, Meeting.created_by == owner_id)
        )
        if recording is None:
            raise ValueError("recording not found")
        state = await lock_processing_state(self._session, recording.meeting_id, owner_id=owner_id)
        if state is None:
            raise ValueError("recording not found")
        previous = await self._session.scalar(
            select(ProcessingRevision).where(
                ProcessingRevision.recording_id == recording_id,
                ProcessingRevision.request_id == request_id,
            )
        )
        if previous is not None:
            if previous.request_fingerprint != request_fingerprint:
                raise ValueError("processing request fingerprint conflict")
            return previous
        if state.in_flight_revision_id is not None:
            raise ValueError("another processing revision is in flight")
        if state.active_processing_revision_id is not None:
            active = await self._session.get(ProcessingRevision, state.active_processing_revision_id)
            if active is None or active.recording_id != recording_id:
                raise ValueError("invalid active revision")
            review = await self._session.scalar(
                select(SpeakerReview).where(
                    SpeakerReview.meeting_id == recording.meeting_id,
                    SpeakerReview.processing_revision == active.revision,
                )
            )
            if review is None or review.status != "complete":
                raise ValueError("active speaker review is pending")
            pending = await self._session.scalar(
                select(SpeakerReviewItem.id)
                .where(
                    SpeakerReviewItem.review_id == review.id,
                    SpeakerReviewItem.disposition.is_(None),
                )
                .limit(1)
            )
            if pending is not None:
                raise ValueError("active speaker review is pending")

        number = await self._session.scalar(
            select(func.coalesce(func.max(ProcessingRevision.revision), 0)).where(
                ProcessingRevision.recording_id == recording_id
            )
        )
        revision = ProcessingRevision(
            id=str(uuid.uuid4()),
            recording_id=recording_id,
            revision=(number or 0) + 1,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            admitted_active_revision_id=state.active_processing_revision_id,
            created_at=datetime.now(UTC),
        )
        self._session.add(revision)
        state.in_flight_revision_id = revision.id
        self._session.add(
            ProcessingRevisionOutbox(
                id=str(uuid.uuid4()),
                recording_id=recording_id,
                processing_revision_id=revision.id,
                event_type="processing_revision_admitted",
                delivery_status="pending",
                created_at=datetime.now(UTC),
            )
        )
        await self._session.flush()
        return revision
