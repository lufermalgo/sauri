"""Meetings router — registration, lookup, and join routes.

Exposes:
- POST /api/v1/meetings — register a meeting
- GET /api/v1/meetings — list the authenticated user's meetings
- GET /api/v1/meetings/{meeting_id} — look up a meeting's state
- POST /api/v1/meetings/{meeting_id}/request-join — trigger a manual join
- GET /api/v1/meetings/{meeting_id}/transcript — get the transcript

All routes require JWT authentication.

Requirements: 4.5, 7.1, 7.2, 8.3, 8.4
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.audit import record_access
from app.auth.dependencies import get_current_user
from app.auth.schemas import AuthenticatedUser
from app.infra.database import create_engine, create_session_factory
from app.infra.models import (
    Diarization,
    Meeting,
    RecordingProcessingState,
    SessionRecording,
    SpeechTurn,
    Transcript,
)
from app.infra.object_store import ObjectStore, create_object_store
from app.infra.queue import JobQueue, create_job_queue
from app.meetings import service as meeting_service
from app.meetings.processing_revision_service import visible_revision_id
from app.meetings.service import (
    delete_meeting,
    get_meeting,
    register_meeting,
    rename_meeting,
    request_join,
)
from app.meetings.speaker_review_service import SpeakerReviewService

router = APIRouter(prefix="/api/v1/meetings", tags=["meetings"])


def _get_queue() -> JobQueue:
    """Job queue factory (simplified DI)."""
    return create_job_queue()


def _get_object_store() -> ObjectStore:
    """Object store factory (simplified DI)."""
    return create_object_store()


async def _get_authorized_meeting(
    session: AsyncSession,
    meeting_id: str,
    user: AuthenticatedUser,
    resource: str,
) -> Meeting:
    """Require an authorized sales user who owns the requested meeting."""
    if not user.is_sales:
        await record_access(session, user.id, resource, "denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to authorized sales users",
        )

    meeting = await session.get(Meeting, meeting_id)
    if meeting is None or meeting.created_by != user.id:
        await record_access(session, user.id, resource, "denied")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        )
    return meeting


class RenameInput(BaseModel):
    """Body of PATCH /{meeting_id} — the note's new title."""

    title: str = Field(..., min_length=1, max_length=512)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_meeting(
    meeting_data: Annotated[dict[str, Any], Body(title="Input")],
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Registers a new meeting in state 'queued'.

    Accepts a Meet link, a calendar invite, or a manual request.
    Requirements: 1.1, 1.7, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            meeting = await register_meeting(
                session=session,
                meeting_data=meeting_data,
                created_by=user.id,
            )
            return {
                "meeting_id": meeting.id,
                "process_state": meeting.process_state,
                "meet_link": meeting.meet_link,
                "origin": meeting.origin,
            }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    finally:
        await engine.dispose()


@router.get("/")
async def list_meetings(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """Lists the authenticated user's meetings.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            stmt = select(Meeting).where(Meeting.created_by == user.id).order_by(Meeting.created_at.desc())
            result = await session.execute(stmt)
            meetings = result.scalars().all()
            return [
                {
                    "meeting_id": m.id,
                    "meet_link": m.meet_link,
                    "origin": m.origin,
                    "process_state": m.process_state,
                    "failure_cause": m.failure_cause if m.process_state == "failed" else None,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "title": m.title,
                }
                for m in meetings
            ]
    finally:
        await engine.dispose()


@router.patch("/{meeting_id}")
async def rename_meeting_endpoint(
    meeting_id: str,
    rename_input: RenameInput,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Renames a note (My_Notes -> rename).

    Only the user who created the Meeting can rename it.
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            await _get_authorized_meeting(session, meeting_id, user, f"PATCH /api/v1/meetings/{meeting_id}")
            updated = await rename_meeting(session, meeting_id, rename_input.title)
            assert updated is not None
            return {"meeting_id": updated.id, "title": updated.title}
    finally:
        await engine.dispose()


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting_endpoint(
    meeting_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> None:
    """Deletes a note and everything associated with it (My_Notes -> delete).

    Only the user who created the Meeting can delete it.
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            await _get_authorized_meeting(session, meeting_id, user, f"DELETE /api/v1/meetings/{meeting_id}")
            object_store = _get_object_store()
            await delete_meeting(session, object_store, meeting_id)
    finally:
        await engine.dispose()


@router.get("/{meeting_id}")
async def get_meeting_endpoint(
    meeting_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Looks up the current state of a meeting.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _get_authorized_meeting(session, meeting_id, user, f"GET /api/v1/meetings/{meeting_id}")
            result = await get_meeting(session, meeting_id)
            recording = await session.scalar(
                select(SessionRecording.id).where(SessionRecording.meeting_id == meeting_id)
            )
            if recording is not None:
                result["recording_id"] = recording
            return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    finally:
        await engine.dispose()


@router.post("/{meeting_id}/request-join")
async def request_join_endpoint(
    meeting_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Requests a manual join of the assistant to a queued meeting.

    Requirements: 1.2, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    queue: JobQueue | None = None
    try:
        async with session_factory() as session:
            await _get_authorized_meeting(session, meeting_id, user, f"POST /api/v1/meetings/{meeting_id}/request-join")
        queue = _get_queue()
        await queue.connect()
        async with session_factory() as session, session.begin():
            result = await request_join(session, meeting_id, queue)
            if not result.successful:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(f"Cannot request join: the meeting is in state '{result.new_state}'"),
                )
            return {
                "meeting_id": meeting_id,
                "process_state": result.new_state,
            }
    finally:
        if queue is not None:
            await queue.disconnect()
        await engine.dispose()


@router.get("/{meeting_id}/speaker-review")
async def get_speaker_review(
    meeting_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Reload the authenticated owner's persisted speaker-review state."""
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _get_authorized_meeting(
                session,
                meeting_id,
                user,
                f"GET /api/v1/meetings/{meeting_id}/speaker-review",
            )
            result = await SpeakerReviewService(session).get_active_review(user.id, meeting_id)
            if result is None:
                state = await session.scalar(
                    select(RecordingProcessingState)
                    .join(
                        SessionRecording,
                        SessionRecording.id == RecordingProcessingState.recording_id,
                    )
                    .where(SessionRecording.meeting_id == meeting_id)
                )
                raise HTTPException(
                    status_code=(status.HTTP_409_CONFLICT if state else status.HTTP_404_NOT_FOUND),
                    detail=f"Speaker review not ready: {meeting_id}"
                    if state
                    else f"Speaker review not found: {meeting_id}",
                )
            return result
    finally:
        await engine.dispose()


@router.get("/{meeting_id}/playback")
async def get_playback_manifest(
    meeting_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return short-lived media URLs after verifying meeting ownership."""
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _get_authorized_meeting(
                session,
                meeting_id,
                user,
                f"GET /api/v1/meetings/{meeting_id}/playback",
            )

            recording_result = await session.execute(
                select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
            )
            recording = recording_result.scalar_one_or_none()
            if recording is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Playback not available for meeting: {meeting_id}",
                )

            inventory = await meeting_service.load_playback_source_inventory(session, recording.id)
            if inventory is None or inventory.audio_source is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Playback not available for meeting: {meeting_id}",
                )

            object_store = _get_object_store()
            audio_url = await object_store.temporary_read_url(inventory.audio_source.object_ref, ttl_seconds=3600)
            audio_source = {
                "source_id": inventory.audio_source.id,
                "url": audio_url,
                "mime_type": inventory.audio_source.mime_type,
            }

            muxed_video_source = None
            video_sources: list[dict[str, Any]] = []
            if inventory.video_presence == "muxed":
                muxed_video_source = dict(audio_source)
            elif inventory.video_presence == "separate":
                for source in inventory.video_sources:
                    if source.video_offset_ms is None:
                        continue
                    video_sources.append(
                        {
                            "source_id": source.id,
                            "url": await object_store.temporary_read_url(source.object_ref, ttl_seconds=3600),
                            "mime_type": source.mime_type,
                            "quality_label": source.quality_label,
                            "width": source.width,
                            "height": source.height,
                            "video_offset_ms": source.video_offset_ms,
                        }
                    )

            return {
                "meeting_id": meeting_id,
                "duration_seconds": inventory.duration_seconds,
                "video_presence": inventory.video_presence,
                "audio_source": audio_source,
                "muxed_video_source": muxed_video_source,
                "video_sources": video_sources,
            }
    finally:
        await engine.dispose()


@router.get("/{meeting_id}/transcript")
async def get_transcript(
    meeting_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Gets the full transcript of a meeting.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _get_authorized_meeting(
                session,
                meeting_id,
                user,
                f"GET /api/v1/meetings/{meeting_id}/transcript",
            )

            # Get the transcript
            revision_id = await visible_revision_id(session, meeting_id)
            stmt = select(Transcript).where(Transcript.meeting_id == meeting_id)
            if revision_id is not None:
                stmt = stmt.where(Transcript.processing_revision_id == revision_id)
            result = await session.execute(stmt)
            transcript = result.scalar_one_or_none()

            if transcript is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Transcript not available for meeting: {meeting_id}",
                )

            # Get the turns/segments
            stmt_turns = (
                select(SpeechTurn).where(SpeechTurn.transcript_id == transcript.id).order_by(SpeechTurn.sequence)
            )
            result_turns = await session.execute(stmt_turns)
            turns = result_turns.scalars().all()

            return {
                "transcript_id": transcript.id,
                "meeting_id": transcript.meeting_id,
                "language": transcript.language,
                "provider": transcript.provider,
                "supports_turns": transcript.supports_turns,
                "created_at": transcript.created_at.isoformat() if transcript.created_at else None,
                "segments": [
                    {
                        # Additive gap (chrome-side-panel, Req. 8.1): exposes the
                        # SpeechTurn's id so it can be joined with its SpeakerAssignment.
                        "id": t.id,
                        "text": t.text,
                        "start_ms": t.start_ms,
                        "end_ms": t.end_ms,
                        "sequence": t.sequence,
                    }
                    for t in turns
                ],
            }
    finally:
        await engine.dispose()


@router.get("/{meeting_id}/diarization")
async def get_diarization(
    meeting_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Gets the Diarization (speakers + assignments) of a meeting.

    New endpoint (chrome-side-panel, backend gap).
    Requirements: 6.3, 8.3, 10.1, 10.2, 14.1, 14.2
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _get_authorized_meeting(
                session,
                meeting_id,
                user,
                f"GET /api/v1/meetings/{meeting_id}/diarization",
            )

            revision_id = await visible_revision_id(session, meeting_id)
            stmt = (
                select(Diarization)
                .where(Diarization.meeting_id == meeting_id)
                .options(
                    selectinload(Diarization.speakers),
                    selectinload(Diarization.assignments),
                )
            )
            if revision_id is not None:
                stmt = stmt.where(Diarization.processing_revision_id == revision_id)
            result = await session.execute(stmt)
            diarization = result.scalar_one_or_none()

            if diarization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Diarization not available for meeting: {meeting_id}",
                )

            ordered_speakers = sorted(diarization.speakers, key=lambda s: s.sequence)

            return {
                "diarization_id": diarization.id,
                "meeting_id": diarization.meeting_id,
                "diarization_state": diarization.diarization_state,
                "speaker_count": diarization.speaker_count,
                "speakers": [{"id": s.id, "label": s.label, "sequence": s.sequence} for s in ordered_speakers],
                "assignments": [{"turn_id": a.turn_id, "speaker_id": a.speaker_id} for a in diarization.assignments],
            }
    finally:
        await engine.dispose()
