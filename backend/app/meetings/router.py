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
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.auth.schemas import AuthenticatedUser
from app.infra.database import create_engine, create_session_factory
from app.infra.models import Diarization, Meeting, SpeechTurn, Transcript
from app.infra.object_store import ObjectStore, create_object_store
from app.infra.queue import JobQueue, create_job_queue
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
                input=meeting_data,
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
            stmt = (
                select(Meeting)
                .where(Meeting.created_by == user.id)
                .order_by(Meeting.created_at.desc())
            )
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
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None or meeting.created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Meeting not found: {meeting_id}",
                )
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
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None or meeting.created_by != user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Meeting not found: {meeting_id}",
                )
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
            result = await get_meeting(session, meeting_id)
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
    queue = _get_queue()
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        await queue.connect()
        async with session_factory() as session, session.begin():
            result = await request_join(session, meeting_id, queue)
            if not result.successful:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot request join: the meeting is in state "
                        f"'{result.new_state}'"
                    ),
                )
            return {
                "meeting_id": meeting_id,
                "process_state": result.new_state,
            }
    finally:
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
            result = await SpeakerReviewService(session).get_active_review(
                user.id, meeting_id
            )
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Speaker review not found: {meeting_id}",
                )
            return result
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
            # Verify the meeting exists
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Meeting not found: {meeting_id}",
                )

            # Get the transcript
            stmt = select(Transcript).where(Transcript.meeting_id == meeting_id)
            result = await session.execute(stmt)
            transcript = result.scalar_one_or_none()

            if transcript is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Transcript not available for meeting: {meeting_id}",
                )

            # Get the turns/segments
            stmt_turns = (
                select(SpeechTurn)
                .where(SpeechTurn.transcript_id == transcript.id)
                .order_by(SpeechTurn.sequence)
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
            meeting = await session.get(Meeting, meeting_id)
            if meeting is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Meeting not found: {meeting_id}",
                )

            stmt = (
                select(Diarization)
                .where(Diarization.meeting_id == meeting_id)
                .options(
                    selectinload(Diarization.speakers),
                    selectinload(Diarization.assignments),
                )
            )
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
                "speakers": [
                    {"id": s.id, "label": s.label, "sequence": s.sequence}
                    for s in ordered_speakers
                ],
                "assignments": [
                    {"turn_id": a.turn_id, "speaker_id": a.speaker_id}
                    for a in diarization.assignments
                ],
            }
    finally:
        await engine.dispose()
