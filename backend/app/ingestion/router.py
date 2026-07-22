"""Ingestion router — authenticated multipart upload endpoint for SessionRecording.

Receives A/V multipart + JSON metadata (IngestionData), requires authentication,
persists to the ObjectStore, records a RecordingNotice, transitions the
Meeting to "transcribing", and enqueues the transcription job.

Requirements: 2.2, 6.5, 9.1, 9.2
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.auth.dependencies import get_current_user
from app.auth.schemas import AuthenticatedUser
from app.infra.database import create_engine, create_session_factory
from app.infra.object_store import ObjectStore, create_object_store
from app.infra.queue import JobQueue, create_job_queue
from app.ingestion.schemas import IngestionData
from app.ingestion.service import process_ingestion
from app.meetings.service import record_transition

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


def _get_object_store() -> ObjectStore:
    """Creates the object store instance (simplified DI, final wiring in task 17.1)."""
    return create_object_store()


def _get_queue() -> JobQueue:
    """Creates the job queue instance (simplified DI, final wiring in task 17.1)."""
    return create_job_queue()


@router.post("/upload", status_code=status.HTTP_200_OK)
async def upload_recording(
    audio: UploadFile = File(...),
    video: UploadFile | None = File(None),
    data: str = Form(...),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Authenticated multipart upload endpoint for SessionRecording.

    Flow:
    a. Parses `data` JSON into IngestionData.
    b. Validates authentication via dependency (get_current_user).
    c. Stores audio in the ObjectStore -> audio_ref.
    d. Stores video in the ObjectStore (if provided) -> video_ref.
    e. Calls process_ingestion (creates SessionRecording, handles idempotency).
    f. Transitions the Meeting to "transcribing" via record_transition.
    g. Enqueues the transcription job.
    h. Returns 200 with the recording's ID and state.
    """
    # a. Parse the data JSON
    try:
        data_dict = json.loads(data)
        ingestion_data = IngestionData(**data_dict)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid ingestion data: {exc}",
        )

    # b. Authentication already validated by the dependency

    # Get infrastructure
    object_store = _get_object_store()
    queue = _get_queue()

    # c. Store audio in the ObjectStore
    audio_content = await audio.read()
    audio_key = f"recordings/{ingestion_data.meeting_id}/{uuid.uuid4()}/audio"
    audio_ref = await object_store.save(
        key=audio_key,
        content=audio_content,
        content_type=audio.content_type or "audio/webm",
    )

    # d. Store video (optional)
    video_ref: str | None = None
    if video is not None:
        video_content = await video.read()
        video_key = f"recordings/{ingestion_data.meeting_id}/{uuid.uuid4()}/video"
        video_ref = await object_store.save(
            key=video_key,
            content=video_content,
            content_type=video.content_type or "video/webm",
        )

    # e. Process ingestion (create SessionRecording, idempotency, notice)
    engine = create_engine()
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        async with session.begin():
            recording, is_new = await process_ingestion(
                session=session,
                data=ingestion_data,
                audio_ref=audio_ref,
                video_ref=video_ref,
                created_by=user.id,
            )

            # If this is an idempotent retry (duplicate key), return without
            # transitioning or enqueuing again (Req. 2.3, 4.1, 4.2).
            if not is_new:
                await engine.dispose()
                return {
                    "recording_id": recording.id,
                    "state": "idempotent_duplicate",
                }

            # f. Transition Meeting to "transcribing"
            from app.infra.models import Meeting

            meeting = await session.get(Meeting, ingestion_data.meeting_id)
            if meeting is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Meeting not found: {ingestion_data.meeting_id}",
                )

            transition_result = await record_transition(
                session=session,
                meeting=meeting,
                event="recording_uploaded",
            )

    # g. Enqueue the transcription job (only if the recording is new)
    await queue.connect()
    try:
        await queue.publish(
            topic="transcribe",
            message={
                "meeting_id": ingestion_data.meeting_id,
                "audio_ref": audio_ref,
            },
        )
    finally:
        await queue.disconnect()

    # Close the engine
    await engine.dispose()

    # h. Return the result
    return {
        "recording_id": recording.id,
        "state": "transcribing" if transition_result.successful else meeting.process_state,
    }
