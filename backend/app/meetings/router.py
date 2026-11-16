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

import logging
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.audit import record_access
from app.auth.dependencies import get_current_user
from app.auth.schemas import AuthenticatedUser
from app.diarization.word_attribution import WordAttribution, WordTime, group_words_into_turns
from app.infra.database import create_engine, create_session_factory
from app.infra.http_errors import (
    CONFLICT,
    FORBIDDEN,
    INVALID_REQUEST,
    NOT_FOUND,
    SafeErrorRoute,
    api_error,
    set_page_headers,
)
from app.infra.models import (
    Diarization,
    Meeting,
    MeetingSummary,
    SessionRecording,
    Speaker,
    SpeakerReview,
    SpeakerReviewItem,
    SpeechTurn,
    Transcript,
    TranscriptWord,
    WordSpeakerAssignment,
)
from app.infra.object_store import ObjectStore, create_object_store
from app.infra.queue import JobQueue, create_job_queue
from app.meetings import service as meeting_service
from app.meetings.schemas import MeetingCreate, ResourceId, RevisionId
from app.meetings.service import (
    delete_meeting,
    get_meeting,
    recorded_at_fields,
    register_meeting,
    rename_meeting,
    request_join,
)
from app.meetings.signed_urls import playback_url_ttl_seconds, signed_url_ttl_seconds
from app.meetings.speaker_review_service import SpeakerReviewService
from app.regeneration import service as regeneration_service

router = APIRouter(prefix="/api/v1/meetings", tags=["meetings"], route_class=SafeErrorRoute)
logger = logging.getLogger(__name__)

# The portal loads the whole library in one call, so the default page is large; the
# maximum bounds the work a single request can ask of the database.
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 500
MAX_LIST_OFFSET = 1_000_000


def _get_queue() -> JobQueue:
    """Job queue factory (simplified DI)."""
    return create_job_queue()


def _get_object_store() -> ObjectStore:
    """Object store factory (simplified DI)."""
    return create_object_store()


async def _get_authorized_meeting(
    session: AsyncSession,
    meeting_id: ResourceId,
    user: AuthenticatedUser,
    resource: str,
) -> Meeting:
    """Require an authorized sales user who owns the requested meeting."""
    if not user.is_sales:
        await record_access(session, user.id, resource, "denied")
        raise api_error(status.HTTP_403_FORBIDDEN, FORBIDDEN)

    meeting = await session.get(Meeting, meeting_id)
    if meeting is None or meeting.created_by != user.id:
        await record_access(session, user.id, resource, "denied")
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return meeting


class DispositionInput(BaseModel):
    """Caller-controlled disposition fields; completion is server-derived."""

    model_config = ConfigDict(extra="forbid")

    disposition: Literal["named", "corrected", "confirmed"]
    label: str | None = Field(default=None, max_length=64)
    expected_version: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_label(self) -> DispositionInput:
        if self.disposition in {"named", "corrected"} and not (self.label or "").strip():
            raise ValueError("A label is required for named or corrected dispositions")
        return self


class RenameInput(BaseModel):
    """Body of PATCH /{meeting_id} — the note's new title."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=512)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_meeting(
    meeting_data: MeetingCreate,
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
                meeting_data=meeting_data.model_dump(exclude_none=True),
                created_by=user.id,
            )
            return {
                "meeting_id": meeting.id,
                "process_state": meeting.process_state,
                "meet_link": meeting.meet_link,
                "origin": meeting.origin,
            }
    except ValueError as exc:
        raise api_error(422, INVALID_REQUEST) from exc
    finally:
        await engine.dispose()


_EMPTY_LIST_FIELDS: dict[str, Any] = {
    "duration_seconds": None,
    "speaker_count": None,
    "summary_topic": None,
    "thumbnail_url": None,
    "media_kind": None,
}


def _media_kind(video_presence: str, thumbnail_state: str | None) -> str | None:
    """Return video or audio when the recording is known to be one, else None."""
    if thumbnail_state == "audio_only":
        return "audio"
    if thumbnail_state == "ready" or video_presence in {"muxed", "separate"}:
        return "video"
    return "audio" if video_presence == "absent" else None


async def _sign_thumbnail_urls(extras: dict[str, dict[str, Any]]) -> None:
    """Replace each internal `thumbnail_ref` with a short-lived signed `thumbnail_url`.

    Signing is local (no object-store call). The store is only created when a thumbnail exists.
    """
    object_store: ObjectStore | None = None
    for fields in extras.values():
        reference = fields.pop("thumbnail_ref", None)
        if reference is None:
            continue
        try:
            object_store = object_store or _get_object_store()
            fields["thumbnail_url"] = await object_store.temporary_read_url(
                reference, ttl_seconds=signed_url_ttl_seconds()
            )
        except Exception:
            logger.warning("Could not sign a thumbnail link; the row falls back to the generic image")


async def _list_summary_fields(
    session: AsyncSession, meeting_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Batch the per-meeting list extras with three queries, whatever the list size.

    `meeting_ids` must already be the authenticated user's meetings; nothing here
    widens ownership. Missing data stays None.
    """
    if not meeting_ids:
        return {}
    extras: dict[str, dict[str, Any]] = {
        meeting_id: dict(_EMPTY_LIST_FIELDS) for meeting_id in meeting_ids
    }

    recordings = await session.execute(
        select(
            SessionRecording.meeting_id,
            SessionRecording.duration_seconds,
            SessionRecording.video_presence,
            SessionRecording.thumbnail_state,
            SessionRecording.thumbnail_ref,
        ).where(SessionRecording.meeting_id.in_(meeting_ids))
    )
    for meeting_id, duration_seconds, video_presence, thumbnail_state, thumbnail_ref in recordings.all():
        extras[meeting_id]["duration_seconds"] = duration_seconds
        extras[meeting_id]["media_kind"] = _media_kind(video_presence, thumbnail_state)
        if thumbnail_state == "ready":
            extras[meeting_id]["thumbnail_ref"] = thumbnail_ref

    # Latest completed revision per meeting, same rule as `_latest_completed_diarization`.
    diarizations = await session.execute(
        select(Diarization.meeting_id, Diarization.speaker_count)
        .where(
            Diarization.meeting_id.in_(meeting_ids),
            Diarization.diarization_state == "completed",
        )
        .order_by(Diarization.processing_revision.asc())
    )
    for meeting_id, speaker_count in diarizations.all():
        extras[meeting_id]["speaker_count"] = speaker_count  # ascending: the last row wins

    # Highest generation per meeting, same rule as `GET /meetings/{id}/summary`.
    summaries = await session.execute(
        select(MeetingSummary.meeting_id, MeetingSummary.topic)
        .where(MeetingSummary.meeting_id.in_(meeting_ids))
        .order_by(MeetingSummary.generation.asc())
    )
    for meeting_id, topic in summaries.all():
        extras[meeting_id]["summary_topic"] = topic  # ascending: the last row wins

    return extras


async def _owner_meeting_count(session: AsyncSession, owner_id: str, offset: int) -> int:
    """Total for an empty page: zero without a query unless the offset skipped real rows."""
    if offset == 0:
        return 0
    return int(
        await session.scalar(
            select(func.count()).select_from(Meeting).where(Meeting.created_by == owner_id)
        )
        or 0
    )


ListSort = Literal["recorded_desc", "recorded_asc", "processed_desc", "processed_asc"]


def _list_order(sort: ListSort) -> tuple[Any, ...]:
    """Row order of the list; the id breaks ties so pages never repeat or skip a row.

    `recorded` is when the recording was made (rows older than the column use the receipt date);
    `processed` is when Sauri received it. Title order is left to the client, which knows the language.
    """
    column = (
        func.coalesce(Meeting.recorded_at, Meeting.created_at)
        if sort.startswith("recorded")
        else Meeting.created_at
    )
    if sort.endswith("_asc"):
        return (column.asc(), Meeting.id.asc())
    return (column.desc(), Meeting.id.desc())


@router.get("/")
async def list_meetings(
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0, le=MAX_LIST_OFFSET)] = 0,
    sort: Annotated[ListSort, Query()] = "recorded_desc",
) -> list[dict[str, Any]]:
    """Lists the authenticated user's meetings, most recently recorded first by default.

    ``sort`` picks the date and direction: ``recorded_desc`` (default), ``recorded_asc``,
    ``processed_desc`` or ``processed_asc``.

    The body stays a bare list. ``X-Total-Count`` carries the owner's total and a
    ``Link: <...>; rel="next"`` header is present while more rows remain.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            # The window count rides on the page query, so listing stays a fixed number of statements.
            stmt = (
                select(Meeting, func.count().over())
                .where(Meeting.created_by == user.id)
                .order_by(*_list_order(sort))
                .limit(limit)
                .offset(offset)
            )
            rows = (await session.execute(stmt)).all()
            meetings = [row[0] for row in rows]
            total = rows[0][1] if rows else await _owner_meeting_count(session, user.id, offset)
            set_page_headers(response, request, total, limit, offset, len(meetings))
            extras = await _list_summary_fields(session, [m.id for m in meetings])
            await _sign_thumbnail_urls(extras)
            return [
                {
                    "meeting_id": m.id,
                    "meet_link": m.meet_link,
                    "origin": m.origin,
                    "process_state": m.process_state,
                    "failure_cause": m.failure_cause if m.process_state == "failed" else None,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "title": m.title,
                    **recorded_at_fields(m),
                    **extras.get(m.id, _EMPTY_LIST_FIELDS),
                }
                for m in meetings
            ]
    finally:
        await engine.dispose()


@router.patch("/{meeting_id}")
async def rename_meeting_endpoint(
    meeting_id: ResourceId,
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
            await _get_authorized_meeting(
                session, meeting_id, user, f"PATCH /api/v1/meetings/{meeting_id}"
            )
            updated = await rename_meeting(session, meeting_id, rename_input.title)
            assert updated is not None
            return {"meeting_id": updated.id, "title": updated.title}
    finally:
        await engine.dispose()


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting_endpoint(
    meeting_id: ResourceId,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> None:
    """Deletes a note and everything associated with it (My_Notes -> delete).

    Only the user who created the Meeting can delete it.
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            await _get_authorized_meeting(
                session, meeting_id, user, f"DELETE /api/v1/meetings/{meeting_id}"
            )
            object_store = _get_object_store()
            await delete_meeting(session, object_store, meeting_id)
    finally:
        await engine.dispose()


@router.get("/{meeting_id}")
async def get_meeting_endpoint(
    meeting_id: ResourceId,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Looks up the current state of a meeting.

    Requirements: 4.5, 9.1
    """
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _get_authorized_meeting(
                session, meeting_id, user, f"GET /api/v1/meetings/{meeting_id}"
            )
            result = await get_meeting(session, meeting_id)
            recording = await session.scalar(
                select(SessionRecording.id).where(SessionRecording.meeting_id == meeting_id)
            )
            if recording is not None:
                result["recording_id"] = recording
            # Optional hints; omitted when empty so existing clients see no change.
            result.update(await regeneration_service.meeting_hints(session, meeting_id))
            return result
    except ValueError as exc:
        raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND) from exc
    finally:
        await engine.dispose()


@router.post("/{meeting_id}/request-join")
async def request_join_endpoint(
    meeting_id: ResourceId,
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
            await _get_authorized_meeting(
                session, meeting_id, user, f"POST /api/v1/meetings/{meeting_id}/request-join"
            )
        queue = _get_queue()
        await queue.connect()
        async with session_factory() as session, session.begin():
            result = await request_join(session, meeting_id, queue)
            if not result.successful:
                raise api_error(status.HTTP_409_CONFLICT, CONFLICT)
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
    meeting_id: ResourceId,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    revision_id: Annotated[RevisionId | None, Query()] = None,
) -> dict[str, Any]:
    """Reload the authenticated owner's persisted speaker-review state.

    Defaults to the latest completed revision; ``revision_id`` reads an earlier one,
    which stays accessible after the speakers are regenerated.
    """
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
            service = SpeakerReviewService(session)
            result = await service.get_active_review(user.id, meeting_id, revision_id)
            if result is None:
                raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
            if revision_id is None:
                revisions = await service.available_revisions(meeting_id)
                if len(revisions) > 1:
                    result = {**result, "available_revisions": revisions}
            return result
    finally:
        await engine.dispose()


@router.put("/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}")
async def put_speaker_disposition(
    meeting_id: ResourceId,
    revision_id: RevisionId,
    speaker_id: ResourceId,
    payload: DispositionInput,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> dict[str, Any]:
    """Persist a decision and return its receipt-backed full review snapshot."""
    engine = create_engine()
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session, session.begin():
            await _get_authorized_meeting(
                session,
                meeting_id,
                user,
                f"PUT /api/v1/meetings/{meeting_id}/speaker-review/revisions/{revision_id}/speakers/{speaker_id}",
            )
            outcome = await SpeakerReviewService(session).record_disposition(
                user.id, meeting_id, str(revision_id), speaker_id,
                payload.model_dump(exclude_none=True), payload.expected_version,
            )
            if outcome["outcome"] == "not_found":
                raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
            if outcome["outcome"].startswith("conflict_"):
                raise api_error(status.HTTP_409_CONFLICT, CONFLICT)
            if outcome["outcome"] == "invalid_request":
                raise api_error(422, INVALID_REQUEST)
            return cast(dict[str, Any], outcome["result"])
    finally:
        await engine.dispose()


@router.get("/{meeting_id}/playback")
async def get_playback_manifest(
    meeting_id: ResourceId,
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
                select(SessionRecording).where(
                    SessionRecording.meeting_id == meeting_id
                )
            )
            recording = recording_result.scalar_one_or_none()
            if recording is None:
                raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)

            inventory = await meeting_service.load_playback_source_inventory(
                session, recording.id
            )
            if inventory is None or inventory.audio_source is None:
                raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)

            object_store = _get_object_store()
            ttl_seconds = playback_url_ttl_seconds()
            audio_url = await object_store.temporary_read_url(
                inventory.audio_source.object_ref, ttl_seconds=ttl_seconds
            )
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
                            "url": await object_store.temporary_read_url(
                                source.object_ref, ttl_seconds=ttl_seconds
                            ),
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


def _latest_completed_diarization(meeting_id: str) -> Select[Diarization]:
    """Select the meeting's latest completed diarization revision (as the repository does)."""
    return (
        select(Diarization)
        .where(
            Diarization.meeting_id == meeting_id,
            Diarization.diarization_state == "completed",
        )
        .order_by(Diarization.processing_revision.desc())
        .limit(1)
    )


async def _attributed_turns(
    session: AsyncSession, meeting_id: str, transcript_id: str
) -> list[dict[str, Any]] | None:
    """Build speaker turns from stored words and the latest completed revision.

    Returns None when the transcript has no words, there is no completed
    revision, or that revision has no word assignments for this transcript.
    """
    diarization = await session.scalar(_latest_completed_diarization(meeting_id))
    if diarization is None:
        return None
    words = (
        await session.scalars(
            select(TranscriptWord)
            .where(TranscriptWord.transcript_id == transcript_id)
            .order_by(TranscriptWord.sequence)
        )
    ).all()
    if not words:
        return None
    assignments = {
        assignment.word_id: assignment
        for assignment in (
            await session.scalars(
                select(WordSpeakerAssignment)
                .join(TranscriptWord, TranscriptWord.id == WordSpeakerAssignment.word_id)
                .where(
                    WordSpeakerAssignment.diarization_id == diarization.id,
                    TranscriptWord.transcript_id == transcript_id,
                )
            )
        ).all()
    }
    if not assignments:
        return None
    speakers = (
        await session.scalars(select(Speaker).where(Speaker.diarization_id == diarization.id))
    ).all()
    raw_label_by_speaker_id = {speaker.id: speaker.raw_label for speaker in speakers}
    speaker_by_raw_label = {speaker.raw_label: speaker for speaker in speakers}
    review_items = (
        await session.scalars(
            select(SpeakerReviewItem)
            .join(SpeakerReview, SpeakerReview.id == SpeakerReviewItem.review_id)
            .where(
                SpeakerReview.meeting_id == meeting_id,
                SpeakerReview.processing_revision == diarization.processing_revision,
            )
        )
    ).all()
    chosen_labels = {item.speaker_key: item.chosen_label for item in review_items}

    word_times: list[WordTime] = []
    attributions: list[WordAttribution] = []
    for word in words:
        word_times.append(WordTime(word.sequence, word.text, word.start_ms, word.end_ms))
        assignment = assignments.get(word.id)
        state = assignment.state if assignment is not None else "unassigned"
        raw_label = (
            raw_label_by_speaker_id.get(assignment.speaker_id)
            if assignment is not None and assignment.speaker_id is not None
            else None
        )
        if state == "assigned" and raw_label is not None:
            attributions.append(WordAttribution(word.sequence, raw_label, "assigned", ()))
        elif state == "ambiguous":
            attributions.append(WordAttribution(word.sequence, None, "ambiguous", ()))
        else:
            attributions.append(WordAttribution(word.sequence, None, "unassigned", ()))

    turns = []
    for turn in group_words_into_turns(word_times, attributions):
        speaker = speaker_by_raw_label.get(turn.raw_label) if turn.raw_label is not None else None
        turns.append(
            {
                "sequence": turn.sequence,
                "speaker_id": speaker.id if speaker is not None else None,
                "speaker_label": (
                    chosen_labels.get(speaker.id) or speaker.label if speaker is not None else None
                ),
                "start_ms": turn.start_ms,
                "end_ms": turn.end_ms,
                "text": turn.text.strip(),
                "word_count": turn.word_count,
                "has_ambiguous": turn.has_ambiguous,
            }
        )
    return turns


@router.get("/{meeting_id}/transcript")
async def get_transcript(
    meeting_id: ResourceId,
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
            stmt = select(Transcript).where(Transcript.meeting_id == meeting_id)
            result = await session.execute(stmt)
            transcript = result.scalar_one_or_none()

            if transcript is None:
                raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)

            # Get the turns/segments
            stmt_turns = (
                select(SpeechTurn)
                .where(SpeechTurn.transcript_id == transcript.id)
                .order_by(SpeechTurn.sequence)
            )
            result_turns = await session.execute(stmt_turns)
            turns = result_turns.scalars().all()
            attributed_turns = await _attributed_turns(session, meeting_id, transcript.id)

            response: dict[str, Any] = {
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
                "presentation": "segments" if attributed_turns is None else "words",
            }
            if attributed_turns is not None:
                response["turns"] = attributed_turns
            return response
    finally:
        await engine.dispose()


@router.get("/{meeting_id}/diarization")
async def get_diarization(
    meeting_id: ResourceId,
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

            diarization = await session.scalar(
                _latest_completed_diarization(meeting_id).options(
                    selectinload(Diarization.speakers),
                    selectinload(Diarization.assignments),
                )
            )

            if diarization is None:
                raise api_error(status.HTTP_404_NOT_FOUND, NOT_FOUND)

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
