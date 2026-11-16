"""Scheduled retention deletion worker (Req. 6.3, 6.6).

Deletes data whose retention period has expired:
- SessionRecording with expires_at <= now: deletes audio + video from the
  object store and the associated Transcript.
- Transcript with expires_at <= now (orphaned): deletes the record.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Diarization, SessionRecording, Transcript
from app.infra.object_store import ObjectStore
from app.retention.cleanup import drain_pending_object_deletions

logger = logging.getLogger(__name__)


async def run_retention_deletion(
    session: AsyncSession,
    object_store: ObjectStore,
    now: datetime,
) -> None:
    """Runs one cycle of expired-data deletion.

    Steps:
    a. Queries SessionRecording with expires_at <= now.
    b. For each expired recording:
       - Deletes the audio blob via object_store.delete(audio_ref).
       - Deletes the video blob via object_store.delete(video_ref) if present.
       - Deletes the library thumbnail if present.
       - Deletes the associated Transcript (by meeting_id).
       - Deletes the SessionRecording record.
    c. Queries Transcript with expires_at <= now (independently expired).
    d. Deletes those Transcript records.
    e. Commit.
    f. Logs how many records were cleaned up.
    """
    deleted_recordings = 0
    deleted_transcripts = 0

    # a. Query expired recordings
    result = await session.execute(
        select(SessionRecording).where(
            SessionRecording.expires_at.isnot(None),
            SessionRecording.expires_at <= now,
        )
    )
    expired_recordings = result.scalars().all()

    # b. For each expired recording
    for recording in expired_recordings:
        # Delete audio blob
        try:
            await object_store.delete(recording.audio_ref)
        except Exception:
            logger.warning(
                "Could not delete audio_ref=%s for recording=%s",
                recording.audio_ref,
                recording.id,
            )

        # Delete video blob if present
        if recording.video_ref is not None:
            try:
                await object_store.delete(recording.video_ref)
            except Exception:
                logger.warning(
                    "Could not delete video_ref=%s for recording=%s",
                    recording.video_ref,
                    recording.id,
                )

        # Delete the library thumbnail if one was cut
        if recording.thumbnail_ref is not None:
            try:
                await object_store.delete(recording.thumbnail_ref)
            except Exception:
                logger.warning(
                    "Could not delete thumbnail_ref=%s for recording=%s",
                    recording.thumbnail_ref,
                    recording.id,
                )

        # Delete the associated Transcript (by meeting_id)
        deleted_transcripts += await _delete_transcripts(
            session, Transcript.meeting_id == recording.meeting_id
        )

        # Delete the SessionRecording record
        await session.delete(recording)
        deleted_recordings += 1

    # c/d. Delete independently expired transcripts
    deleted_transcripts += await _delete_transcripts(
        session, Transcript.expires_at.isnot(None), Transcript.expires_at <= now
    )

    # e. Commit
    await session.commit()

    # f. Recover staged objects whose previous cleanup attempt failed.
    await drain_pending_object_deletions(session, object_store)

    # g. Cleanup log
    total = deleted_recordings + deleted_transcripts
    if total > 0:
        logger.info(
            "Retention deletion complete: %d recordings, %d transcripts removed",
            deleted_recordings,
            deleted_transcripts,
        )
    else:
        logger.debug("Retention deletion: no expired data")


async def _delete_transcripts(
    session: AsyncSession, *criteria: ColumnElement[bool]
) -> int:
    """Deletes matching transcripts and everything derived from them.

    Diarizations reference transcripts without ON DELETE CASCADE, so they are
    removed first (cascading speakers and turn/word assignments). Deleting the
    transcript then cascades speech turns and transcript words in the database.
    """
    transcript_ids = select(Transcript.id).where(*criteria).scalar_subquery()
    await session.execute(
        delete(Diarization).where(Diarization.transcript_id.in_(transcript_ids))
    )
    result = await session.execute(delete(Transcript).where(*criteria))
    return int(result.rowcount)  # type: ignore[attr-defined]


async def start_retention_worker(
    session_factory: async_sessionmaker[AsyncSession],
    object_store: ObjectStore,
    interval_seconds: int = 3600,
) -> None:
    """Runs retention deletion periodically.

    Runs indefinitely, executing run_retention_deletion every
    `interval_seconds` seconds.
    """
    logger.info(
        "Retention worker started (interval=%ds)", interval_seconds
    )
    while True:
        try:
            async with session_factory() as session:
                now = datetime.utcnow()
                await run_retention_deletion(session, object_store, now)
        except Exception:
            logger.exception("Error in retention deletion cycle")

        await asyncio.sleep(interval_seconds)
