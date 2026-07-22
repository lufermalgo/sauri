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

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import SessionRecording, Transcript
from app.infra.object_store import ObjectStore

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

        # Delete the associated Transcript (by meeting_id)
        transcript_result = await session.execute(
            delete(Transcript).where(
                Transcript.meeting_id == recording.meeting_id
            )
        )
        deleted_transcripts += transcript_result.rowcount  # type: ignore[attr-defined]

        # Delete the SessionRecording record
        await session.delete(recording)
        deleted_recordings += 1

    # c. Query independently expired transcripts
    independent_transcripts_result = await session.execute(
        select(Transcript).where(
            Transcript.expires_at.isnot(None),
            Transcript.expires_at <= now,
        )
    )
    orphan_transcripts = independent_transcripts_result.scalars().all()

    # d. Delete independently expired transcripts
    for transcript in orphan_transcripts:
        await session.delete(transcript)
        deleted_transcripts += 1

    # e. Commit
    await session.commit()

    # f. Cleanup log
    total = deleted_recordings + deleted_transcripts
    if total > 0:
        logger.info(
            "Retention deletion complete: %d recordings, %d transcripts removed",
            deleted_recordings,
            deleted_transcripts,
        )
    else:
        logger.debug("Retention deletion: no expired data")


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
