"""Meetings service — persistence layer for state transitions and registration.

This module implements:
- `record_transition`: uses the pure function `apply_event` to compute the
  transition and then persists the result (updates the Meeting and creates
  a row in StateHistory).
- `register_meeting`: accepts the three input types (link, calendar, manual),
  validates the Meet link, creates the Meeting in state 'queued' and records
  the initial entry in StateHistory.
- `get_meeting`: returns the current state of a Meeting and, if applicable,
  the failure cause.

Requirements: 1.1, 1.4, 1.5, 1.7, 2.5, 3.6, 4.1, 4.2, 4.4, 4.5
"""

from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import (
    Diarization,
    Meeting,
    RecordingMediaSource,
    SessionRecording,
    StateHistory,
)
from app.infra.object_store import ObjectStore
from app.infra.queue import JobQueue
from app.meetings.schemas import (
    CalendarMeetingInput,
    LinkMeetingInput,
    ManualMeetingInput,
    MeetingInput,
)
from app.meetings.state_machine import TransitionResult, apply_event


@dataclass(frozen=True)
class PlaybackSource:
    """A stored object eligible for an owner-authorized playback manifest."""

    id: str
    object_ref: str
    mime_type: str | None
    quality_label: str
    width: int | None
    height: int | None
    video_offset_ms: int | None


@dataclass(frozen=True)
class PlaybackSourceInventory:
    """Persisted source choices and recording metadata for playback."""

    video_presence: str
    duration_seconds: int
    audio_source: PlaybackSource | RecordingMediaSource | None
    video_sources: list[PlaybackSource | RecordingMediaSource]


async def load_playback_source_inventory(
    session: AsyncSession, recording_id: str
) -> PlaybackSourceInventory | None:
    """Load a recording's source inventory without inferring legacy video."""
    recording = await session.get(SessionRecording, recording_id)
    if recording is None:
        return None

    result = await session.execute(
        select(RecordingMediaSource)
        .where(RecordingMediaSource.recording_id == recording_id)
        .order_by(RecordingMediaSource.id)
    )
    sources = result.scalars().all()
    audio_source: PlaybackSource | RecordingMediaSource | None = next(
        (source for source in sources if source.kind == "audio"), None
    )
    if audio_source is None:
        # Legacy recordings retain a canonical audio_ref. This fallback never
        # treats MIME or a video_ref as evidence that the audio is muxed.
        audio_source = PlaybackSource(
            id=f"legacy-audio-{recording.id}",
            object_ref=recording.audio_ref,
            mime_type=None,
            quality_label="Original",
            width=None,
            height=None,
            video_offset_ms=None,
        )

    return PlaybackSourceInventory(
        video_presence=recording.video_presence,
        duration_seconds=recording.duration_seconds,
        audio_source=audio_source,
        video_sources=[source for source in sources if source.kind == "video"],
    )


async def record_transition(
    session: AsyncSession,
    meeting: Meeting,
    event: str,
) -> TransitionResult:
    """Applies an event via the pure function and persists the transition.

    If the transition is valid:
    1. Updates `meeting.process_state` (and `failure_cause` if applicable).
    2. Creates an entry in `StateHistory` with a timestamp.
    3. Flushes (no commit — the caller controls the transaction).

    If the transition is invalid: doesn't modify anything, returns successful=False.

    Args:
        session: Async SQLAlchemy session (the caller handles commit/rollback).
        meeting: Meeting instance with its current state.
        event: Domain event to apply.

    Returns:
        TransitionResult with the outcome of the operation.
    """
    result = apply_event(meeting.process_state, event)

    if not result.successful:
        return result

    # Update the meeting's state
    meeting.process_state = result.new_state
    if result.failure_cause is not None:
        meeting.failure_cause = result.failure_cause

    # Create an entry in the state history
    history = StateHistory(
        id=str(uuid.uuid4()),
        meeting_id=meeting.id,
        state=result.new_state,
        failure_cause=result.failure_cause,
        occurred_at=datetime.now(UTC),
    )
    session.add(history)

    await session.flush()

    return result


async def register_meeting(
    session: AsyncSession,
    input: dict[str, Any],
    created_by: str,
) -> Meeting:
    """Creates a new Meeting in state 'queued' from a validated input.

    Determines the 'origin' from the shape of the input:
    - Has `calendar_invite_id` -> 'calendar_invite'
    - Only `meet_link` -> 'link' (default for LinkMeetingInput)
    - Only `meet_link` as a manual request -> 'manual'

    Since LinkMeetingInput and ManualMeetingInput have the same shape, an
    extra `type` field with value 'manual' is accepted to distinguish them.
    If not present, 'link' is assumed.

    Validates the meet_link format. Creates the Meeting and the initial
    entry in StateHistory.

    Raises:
        ValueError: If the input is invalid (invalid link, missing fields).

    Requirements: 1.1, 1.7
    """
    # Determine the input type and validate with Pydantic
    model: MeetingInput
    try:
        if "calendar_invite_id" in input:
            model = CalendarMeetingInput(**input)
            origin = "calendar_invite"
        elif input.get("type") == "manual":
            # Exclude the 'type' field for Pydantic validation
            validation_data = {k: v for k, v in input.items() if k != "type"}
            model = ManualMeetingInput(**validation_data)
            origin = "manual"
        else:
            model = LinkMeetingInput(**input)
            origin = "link"
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"Invalid input: {exc}") from exc

    now = datetime.now(UTC)
    meeting_id = str(uuid.uuid4())

    # Create the Meeting in state 'queued'
    meeting = Meeting(
        id=meeting_id,
        meet_link=model.meet_link,
        origin=origin,
        calendar_invite_id=(
            model.calendar_invite_id
            if isinstance(model, CalendarMeetingInput)
            else None
        ),
        scheduled_start_time=(
            model.scheduled_start_time
            if isinstance(model, CalendarMeetingInput)
            else None
        ),
        process_state="queued",
        failure_cause=None,
        created_by=created_by,
        created_at=now,
    )
    session.add(meeting)
    # Flush the Meeting first: StateHistory's FK requires the parent row
    # to exist before insert (enforced by real databases, not by the SQLite
    # test engine, which ignores foreign keys by default).
    await session.flush()

    # Create the initial entry in StateHistory
    history = StateHistory(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        state="queued",
        failure_cause=None,
        occurred_at=now,
    )
    session.add(history)
    await session.flush()

    return meeting


async def get_meeting(
    session: AsyncSession,
    meeting_id: str,
) -> dict[str, Any]:
    """Looks up the current state of a Meeting.

    Returns a dict with:
    - meeting_id
    - process_state: the current state (from meeting.process_state)
    - failure_cause: included ONLY if process_state == "failed", None otherwise

    Raises ValueError if the meeting isn't found.

    Requirements: 4.5
    """
    meeting = await session.get(Meeting, meeting_id)

    if meeting is None:
        raise ValueError(f"Meeting not found: {meeting_id}")

    result: dict[str, Any] = {
        "meeting_id": meeting.id,
        "title": meeting.title,
        "process_state": meeting.process_state,
    }

    if meeting.process_state == "failed":
        result["failure_cause"] = meeting.failure_cause

    return result


async def rename_meeting(
    session: AsyncSession,
    meeting_id: str,
    new_title: str,
) -> Meeting | None:
    """Renames a Meeting (My_Notes -> rename note).

    Returns None if the Meeting doesn't exist; the caller decides how to map
    that to an HTTP response (404).
    """
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        return None

    meeting.title = new_title
    await session.flush()
    return meeting


async def delete_meeting(
    session: AsyncSession,
    object_store: ObjectStore,
    meeting_id: str,
) -> bool:
    """Deletes a Meeting and everything associated with it (My_Notes -> delete note).

    Order is necessary because `diarizations.meeting_id` and
    `diarizations.transcript_id` don't have ondelete=CASCADE (they'd block
    cascading deletion of transcripts/speech_turns if a Diarization were
    left referencing them):
    1. Deletes the Diarization for this meeting if it exists (ORM/DB cascade
       deletes Speaker and SpeakerAssignment automatically via ondelete=CASCADE).
    2. Deletes the audio/video blobs of the SessionRecording from the store.
    3. Deletes the Meeting — DB cascade deletes state_history,
       session_recordings, transcripts (-> speech_turns), and recording_notices.

    Returns False if the Meeting doesn't exist; the caller decides how to map
    that to an HTTP response (404).
    """
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        return False

    # Low-level DELETE (not session.delete()): Diarization.speakers is a
    # bidirectional ORM relationship without cascade configured, so
    # session.delete() would try to set speakers.diarization_id to NULL
    # (a NOT NULL column) before deleting, instead of letting the database's
    # ondelete=CASCADE FK delete speakers/assignments.
    await session.execute(delete(Diarization).where(Diarization.meeting_id == meeting_id))
    await session.flush()

    stmt_recording = select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
    recording = (await session.execute(stmt_recording)).scalar_one_or_none()
    if recording is not None:
        with contextlib.suppress(Exception):
            await object_store.delete(recording.audio_ref)
        if recording.video_ref is not None:
            with contextlib.suppress(Exception):
                await object_store.delete(recording.video_ref)

    await session.delete(meeting)
    await session.flush()
    return True


async def request_join(
    session: AsyncSession,
    meeting_id: str,
    queue: JobQueue,
) -> TransitionResult:
    """Requests manual join of the assistant to a queued Meeting (Req. 1.2).

    1. Loads the Meeting by ID.
    2. Applies the "start_capture" event via record_transition.
    3. If successful, publishes a job to the queue (topic="join", message={meeting_id, meet_link}).
    4. Returns the transition result.
    """
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        return TransitionResult(successful=False, new_state="queued")

    result = await record_transition(session, meeting, "start_capture")

    if result.successful:
        await queue.publish(
            topic="join",
            message={"meeting_id": meeting.id, "meet_link": meeting.meet_link},
        )

    return result


async def schedule_join_by_calendar(
    session: AsyncSession,
    meeting_id: str,
    queue: JobQueue,
) -> TransitionResult:
    """Triggers the join when scheduled_start_time arrives (Req. 1.3).

    Same flow as request_join but designed to be invoked by a scheduler when
    the scheduled time arrives. Applies the "start_capture" event.
    """
    meeting = await session.get(Meeting, meeting_id)
    if meeting is None:
        return TransitionResult(successful=False, new_state="queued")

    result = await record_transition(session, meeting, "start_capture")

    if result.successful:
        await queue.publish(
            topic="join",
            message={"meeting_id": meeting.id, "meet_link": meeting.meet_link},
        )

    return result
