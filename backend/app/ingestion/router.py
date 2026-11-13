"""Ingestion router — authenticated multipart upload endpoint for SessionRecording.

Receives A/V multipart + JSON metadata (IngestionData), requires authentication,
persists to the ObjectStore, records a RecordingNotice, transitions the
Meeting to "transcribing", and durably admits an exact-revision outbox event.

Requirements: 2.2, 6.5, 9.1, 9.2
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.auth.schemas import AuthenticatedUser
from app.infra.database import create_engine, create_session_factory
from app.infra.models import Meeting, ProcessingRevision
from app.infra.object_store import ObjectStore, create_object_store
from app.ingestion.schemas import IngestionData
from app.ingestion.service import preflight_ingestion, process_ingestion, resolve_upload_title
from app.meetings.processing_revision_service import ProcessingRevisionService
from app.meetings.service import record_transition
from app.retention.cleanup import (
    drain_pending_object_deletions,
    persist_pending_object_deletions,
)

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])
logger = logging.getLogger(__name__)

_AUDIO_FILE = File(...)
_VIDEO_FILE = File(None)
_INGESTION_DATA_FORM = Form(...)
_AUTHENTICATED_USER = Depends(get_current_user)


def _cleanup_scope_hash(user_id: str, meeting_id: str, idempotency_key: str) -> str:
    scope = json.dumps([user_id, meeting_id, idempotency_key], separators=(",", ":"))
    return hashlib.sha256(scope.encode()).hexdigest()


def _request_fingerprint(data: IngestionData, audio_content: bytes, video_content: bytes | None) -> str:
    """Canonical request metadata and media, independent of staged object refs."""
    metadata = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(metadata.encode("utf-8"))
    digest.update(b"\x00" + hashlib.sha256(audio_content).digest())
    digest.update(b"\x01" if video_content is not None else b"\x00")
    if video_content is not None:
        digest.update(hashlib.sha256(video_content).digest())
    return "sha256:" + digest.hexdigest()


def _get_object_store() -> ObjectStore:
    """Creates the object store instance (simplified DI, final wiring in task 17.1)."""
    return create_object_store()


@router.post("/upload", status_code=status.HTTP_200_OK)
async def upload_recording(
    audio: UploadFile = _AUDIO_FILE,
    video: UploadFile | None = _VIDEO_FILE,
    data: str = _INGESTION_DATA_FORM,
    user: AuthenticatedUser = _AUTHENTICATED_USER,
) -> dict[str, Any]:
    """Authenticated multipart upload endpoint for SessionRecording.

    Flow:
    a. Parses `data` JSON into IngestionData.
    b. Validates authentication via dependency (get_current_user).
    c. Stores audio in the ObjectStore -> audio_ref.
    d. Stores video in the ObjectStore (if provided) -> video_ref.
    e. Calls process_ingestion (creates SessionRecording, handles idempotency).
    f. Transitions the Meeting to "transcribing" via record_transition.
    g. Leaves the exact revision admission event pending for T-15 dispatch.
    h. Returns 200 with the recording's ID and state.
    """
    # a. Parse the data JSON
    try:
        data_dict = json.loads(data)
        ingestion_data = IngestionData(**data_dict)
        ingestion_data.title = resolve_upload_title(ingestion_data.title, audio.filename)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid ingestion data: {exc}",
        ) from exc

    # b. Authentication already validated by the dependency
    has_separate_video = video is not None
    if (
        (ingestion_data.video_presence == "separate") != has_separate_video
        or ingestion_data.video_presence in {"muxed", "absent"}
        and has_separate_video
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Video upload does not match the declared video_presence",
        )

    # Check ownership and exact retries before writing any media object.
    preflight_engine = create_engine()
    preflight_session_factory = create_session_factory(preflight_engine)
    existing_recording = None
    prior_state: str | None = None
    try:
        async with preflight_session_factory() as session:
            existing_recording = await preflight_ingestion(session, ingestion_data, user.id)
            if existing_recording is not None:
                prior_revision = await session.scalar(
                    select(ProcessingRevision.id).where(
                        ProcessingRevision.recording_id == existing_recording.id,
                        ProcessingRevision.request_id == ingestion_data.idempotency_key,
                    )
                )
                if prior_revision is not None:
                    # A preflight retry must not bypass the admission fingerprint
                    # just because it avoids staging a duplicate media object.
                    fingerprint = _request_fingerprint(
                        ingestion_data,
                        await audio.read(),
                        await video.read() if video is not None else None,
                    )
                    try:
                        await ProcessingRevisionService(session).admit_candidate(
                            owner_id=user.id,
                            recording_id=existing_recording.id,
                            request_id=ingestion_data.idempotency_key,
                            request_fingerprint=fingerprint,
                        )
                    except ValueError as error:
                        raise HTTPException(status_code=409, detail="Processing admission conflict") from error
                await drain_pending_object_deletions(
                    session,
                    _get_object_store(),
                    _cleanup_scope_hash(
                        user.id,
                        ingestion_data.meeting_id,
                        ingestion_data.idempotency_key,
                    ),
                    raise_on_error=True,
                )
                meeting = await session.get(Meeting, ingestion_data.meeting_id)
                if meeting is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Meeting not found",
                    )
                prior_state = meeting.process_state
    finally:
        await preflight_engine.dispose()

    if existing_recording is not None:
        return {
            "recording_id": existing_recording.id,
            "state": prior_state,
        }

    # Get infrastructure only after preflight passes.
    object_store = _get_object_store()

    cleanup_scope_hash = _cleanup_scope_hash(user.id, ingestion_data.meeting_id, ingestion_data.idempotency_key)
    staged_refs: list[str | None] = []
    video_ref: str | None = None
    video_content: bytes | None = None
    try:
        # c. Store audio in the ObjectStore
        audio_content = await audio.read()
        audio_key = f"recordings/{ingestion_data.meeting_id}/{uuid.uuid4()}/audio"
        audio_ref = await object_store.save(
            audio_key,
            audio_content,
            audio.content_type or "audio/webm",
        )
        staged_refs.append(audio_ref)

        # d. Store video (optional)
        if video is not None:
            video_content = await video.read()
            video_key = f"recordings/{ingestion_data.meeting_id}/{uuid.uuid4()}/video"
            video_ref = await object_store.save(
                video_key,
                video_content,
                video.content_type or "video/webm",
            )
            staged_refs.append(video_ref)
    except Exception:
        cleanup_engine: Any = None
        try:
            cleanup_engine = create_engine()
            cleanup_session_factory = create_session_factory(cleanup_engine)
            async with cleanup_session_factory() as cleanup_session:
                await persist_pending_object_deletions(cleanup_session, cleanup_scope_hash, staged_refs)
                await drain_pending_object_deletions(cleanup_session, object_store, cleanup_scope_hash)
        except Exception:
            logger.exception("Could not durably clean partially staged ingestion objects")
        finally:
            if cleanup_engine is not None:
                try:
                    await cleanup_engine.dispose()
                except Exception:
                    logger.exception("Could not dispose partial-ingestion cleanup engine")
        raise

    # e. Process ingestion (create SessionRecording, handles idempotency, notice)
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            try:
                recording, is_new = await process_ingestion(
                    session=session,
                    data=ingestion_data,
                    audio_ref=audio_ref,
                    video_ref=video_ref,
                    created_by=user.id,
                    request_fingerprint=_request_fingerprint(ingestion_data, audio_content, video_content),
                )
            except ValueError as error:
                raise HTTPException(status_code=409, detail="Processing admission conflict") from error

            if is_new:
                # f. Transition Meeting to "transcribing"
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
            else:
                meeting = await session.get(Meeting, ingestion_data.meeting_id)
                if meeting is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Meeting not found",
                    )
                prior_state = meeting.process_state
    except Exception:
        try:
            async with session_factory() as cleanup_session:
                await persist_pending_object_deletions(
                    cleanup_session,
                    cleanup_scope_hash,
                    [audio_ref, video_ref],
                )
                await drain_pending_object_deletions(cleanup_session, object_store, cleanup_scope_hash)
        except Exception:
            logger.exception("Could not durably clean failed ingestion objects")
        finally:
            await engine.dispose()
        raise

    # If another request committed the same idempotency key during storage,
    # clean only this attempt's uncommitted refs and return the persisted result.
    if not is_new:
        try:
            async with session_factory() as cleanup_session:
                await persist_pending_object_deletions(
                    cleanup_session,
                    cleanup_scope_hash,
                    [audio_ref, video_ref],
                )
                await drain_pending_object_deletions(
                    cleanup_session,
                    object_store,
                    cleanup_scope_hash,
                    raise_on_error=True,
                )
        finally:
            await engine.dispose()
        return {"recording_id": recording.id, "state": prior_state}

    # T-15 dispatches the committed admission outbox event with its exact
    # processing_revision_id. Never publish an unversioned legacy job here.

    # Close the engine
    await engine.dispose()

    # h. Return the result
    return {
        "recording_id": recording.id,
        "state": "transcribing" if transition_result.successful else meeting.process_state,
    }
