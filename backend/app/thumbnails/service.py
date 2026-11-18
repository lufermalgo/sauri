"""Generate, store and sweep recording thumbnails.

A thumbnail is derived data: failing to make one never fails a meeting. Outcomes
are recorded on the recording (`thumbnail_state`) so each recording is attempted
once; unexpected infrastructure errors leave it pending to be retried later.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, SessionRecording
from app.infra.object_store import ObjectStore
from app.infra.object_store_fs import FilesystemObjectStore
from app.meetings.recorded_at import SOURCE_FILE_METADATA, is_stronger_source, plausible_recorded_at
from app.meetings.service import load_playback_source_inventory
from app.thumbnails.ffmpeg import MediaToolError, extract_best_frame, probe_media

logger = logging.getLogger(__name__)

ThumbnailState = Literal["ready", "audio_only", "unavailable"]

SOURCE_URL_TTL_SECONDS = 900
DEFAULT_SWEEP_INTERVAL_SECONDS = 30
ERROR = "error"


def thumbnail_key(meeting_id: str, recording_id: str) -> str:
    """Object key next to the recording; one fixed key per recording keeps regeneration idempotent."""
    return f"recordings/{meeting_id}/{recording_id}/thumbnail.jpg"


@dataclass(frozen=True)
class _Job:
    meeting_id: str
    recording_id: str
    recorded_duration_seconds: int
    source_ref: str | None
    offset_seconds: float
    fixed_state: ThumbnailState | None
    # Media object to probe for the creation tag when the thumbnail itself needs no probe (audio only).
    creation_ref: str | None = None
    # The meeting may still learn its recording date from the container; see `note_creation_time`.
    wants_creation_time: bool = False


async def _wants_creation_time(session: AsyncSession, recording: SessionRecording) -> bool:
    """Only web uploads: the extension knows its own capture start, which is better than any tag."""
    if recording.capture_origin != "web_upload":
        return False
    meeting = await session.get(Meeting, recording.meeting_id)
    return meeting is not None and is_stronger_source(SOURCE_FILE_METADATA, meeting.recorded_at_source)


async def _load_job(session: AsyncSession, recording_id: str) -> _Job | None:
    recording = await session.get(SessionRecording, recording_id)
    if recording is None:
        return None

    wants = await _wants_creation_time(session, recording)

    def job(
        source_ref: str | None = None,
        offset_seconds: float = 0.0,
        fixed_state: ThumbnailState | None = None,
        creation_ref: str | None = None,
    ) -> _Job:
        return _Job(
            meeting_id=recording.meeting_id,
            recording_id=recording.id,
            recorded_duration_seconds=recording.duration_seconds,
            source_ref=source_ref,
            offset_seconds=offset_seconds,
            fixed_state=fixed_state,
            creation_ref=creation_ref,
            wants_creation_time=wants,
        )

    if recording.video_presence == "absent":
        if not wants:
            return job(fixed_state="audio_only")
        audio_only = await load_playback_source_inventory(session, recording.id)
        audio_ref = audio_only.audio_source.object_ref if audio_only and audio_only.audio_source else None
        return job(fixed_state="audio_only", creation_ref=audio_ref)

    inventory = await load_playback_source_inventory(session, recording.id)
    if inventory is None:
        return job(fixed_state="unavailable")
    if recording.video_presence == "separate":
        for source in inventory.video_sources:
            if source.video_offset_ms is not None:
                return job(source_ref=source.object_ref, offset_seconds=source.video_offset_ms / 1000)
        return job(fixed_state="unavailable")

    # Muxed (and legacy "unknown") recordings carry any video inside the primary media object.
    if inventory.audio_source is None:
        return job(fixed_state="unavailable")
    return job(source_ref=inventory.audio_source.object_ref)


async def _record_result(
    session_factory: async_sessionmaker[AsyncSession],
    object_store: ObjectStore,
    job: _Job,
    state: ThumbnailState,
    jpeg: bytes | None,
) -> None:
    key = thumbnail_key(job.meeting_id, job.recording_id) if jpeg is not None else None
    if key is not None and jpeg is not None:
        await object_store.save(key, jpeg, "image/jpeg")
    async with session_factory() as session, session.begin():
        recording = await session.get(SessionRecording, job.recording_id)
        if recording is not None:
            recording.thumbnail_ref = key
            recording.thumbnail_state = state
            return
    if key is not None:
        # The recording was deleted while its frame was being cut; do not leave the frame behind.
        await object_store.delete(key)


async def note_creation_time(
    session_factory: async_sessionmaker[AsyncSession], meeting_id: str, creation_time: datetime | None
) -> bool:
    """Keep the container's creation date as the meeting's recording date when it is a better source."""
    moment = plausible_recorded_at(creation_time)
    if moment is None:
        return False
    async with session_factory() as session, session.begin():
        meeting = await session.get(Meeting, meeting_id)
        if meeting is None or not is_stronger_source(SOURCE_FILE_METADATA, meeting.recorded_at_source):
            return False
        meeting.recorded_at = moment
        meeting.recorded_at_source = SOURCE_FILE_METADATA
        return True


async def _media_source(object_store: ObjectStore, reference: str) -> str:
    if root := os.environ.get("SAURI_RECORDINGS_DIR"):
        return str(FilesystemObjectStore(Path(root)).local_path(reference))
    return await object_store.temporary_read_url(reference, ttl_seconds=SOURCE_URL_TTL_SECONDS)


async def generate_thumbnail(
    session_factory: async_sessionmaker[AsyncSession],
    object_store: ObjectStore,
    recording_id: str,
) -> ThumbnailState | None:
    """Generate and record the thumbnail of one recording.

    Returns the recorded state, or None when the recording no longer exists.
    Infrastructure errors (object store, database, missing ffmpeg) propagate and leave
    the recording pending; media problems are recorded as `unavailable`.
    """
    async with session_factory() as session:
        job = await _load_job(session, recording_id)
    if job is None:
        return None
    state: ThumbnailState
    if job.source_ref is None:
        state = job.fixed_state or "unavailable"
        if job.creation_ref is not None:
            # Audio only has no frame to cut, but its header can still carry the creation date.
            url = await _media_source(object_store, job.creation_ref)
            try:
                await note_creation_time(session_factory, job.meeting_id, (await probe_media(url)).creation_time)
            except MediaToolError as exc:
                logger.info("No creation date for recording_id=%s: %s", recording_id, exc)
        await _record_result(session_factory, object_store, job, state, None)
        return state

    source_url = await _media_source(object_store, job.source_ref)
    jpeg: bytes | None = None
    try:
        probe = await probe_media(source_url)
        if job.wants_creation_time:
            await note_creation_time(session_factory, job.meeting_id, probe.creation_time)
        if not probe.has_video:
            state = "audio_only"
        else:
            duration = probe.duration_seconds
            if duration is None and job.recorded_duration_seconds > 0:
                duration = float(job.recorded_duration_seconds)  # live webm has no container duration
            jpeg = await extract_best_frame(source_url, duration, job.offset_seconds)
            state = "ready" if jpeg is not None else "unavailable"
    except MediaToolError as exc:
        logger.warning("Thumbnail unavailable for recording_id=%s: %s", recording_id, exc)
        state = "unavailable"
    await _record_result(session_factory, object_store, job, state, jpeg)
    return state


async def _pending_ids(
    session_factory: async_sessionmaker[AsyncSession], *, include_unavailable: bool, excluded: set[str], limit: int
) -> list[str]:
    pending: ColumnElement[bool] = SessionRecording.thumbnail_state.is_(None)
    if include_unavailable:
        pending = or_(pending, SessionRecording.thumbnail_state == "unavailable")
    statement = select(SessionRecording.id).where(pending)
    if excluded:
        statement = statement.where(SessionRecording.id.not_in(excluded))
    statement = statement.order_by(SessionRecording.finished_at.desc()).limit(limit)
    async with session_factory() as session:
        return list((await session.scalars(statement)).all())


async def process_pending(
    session_factory: async_sessionmaker[AsyncSession],
    object_store: ObjectStore,
    *,
    include_unavailable: bool = False,
    limit: int | None = None,
    failed: set[str] | None = None,
) -> Counter[str]:
    """Generate thumbnails for pending recordings, one at a time, newest first.

    Recordings that hit an infrastructure error are added to `failed` and skipped on later
    calls that share the set. Returns the number of recordings per outcome.
    """
    failed = failed if failed is not None else set()
    attempted: set[str] = set()
    tally: Counter[str] = Counter()
    while limit is None or sum(tally.values()) < limit:
        batch = await _pending_ids(
            session_factory, include_unavailable=include_unavailable, excluded=failed | attempted, limit=1
        )
        if not batch:
            break
        recording_id = batch[0]
        attempted.add(recording_id)
        try:
            state = await generate_thumbnail(session_factory, object_store, recording_id)
        except Exception:
            logger.exception("Thumbnail generation failed for recording_id=%s; it stays pending", recording_id)
            failed.add(recording_id)
            tally[ERROR] += 1
            continue
        if state is not None:
            tally[state] += 1
    return tally


def sweep_interval_seconds() -> int:
    raw = os.environ.get("THUMBNAIL_SWEEP_INTERVAL_SECONDS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_SWEEP_INTERVAL_SECONDS
    except ValueError:
        logger.warning("THUMBNAIL_SWEEP_INTERVAL_SECONDS is not an integer; using the default.")
        return DEFAULT_SWEEP_INTERVAL_SECONDS
    return value if value > 0 else DEFAULT_SWEEP_INTERVAL_SECONDS


async def run_thumbnail_sweeper(
    session_factory: async_sessionmaker[AsyncSession],
    object_store: ObjectStore,
    interval_seconds: int | None = None,
) -> None:
    """Background loop of the worker: thumbnails new and legacy recordings, one at a time."""
    interval = interval_seconds if interval_seconds is not None else sweep_interval_seconds()
    failed: set[str] = set()
    logger.info("Thumbnail sweeper started (interval=%ds)", interval)
    while True:
        try:
            tally = await process_pending(session_factory, object_store, failed=failed)
            if tally:
                logger.info("Thumbnail sweep done: %s", dict(tally))
        except Exception:
            logger.exception("Error in thumbnail sweep")
        await asyncio.sleep(interval)
