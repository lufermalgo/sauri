"""Explicit, re-runnable backfill of legacy diarization (never run during migration).

Run only under an authorized operator's control; no production data is touched by
importing this module. Jobs contain only persisted meeting/revision identifiers.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.diarization.repository import DiarizationRepository
from app.infra.models import Diarization, Meeting, SessionRecording, Transcript
from app.infra.object_store import ObjectStore
from app.infra.queue import JobQueue


def expired(value: datetime | None, now: datetime) -> bool:
    """SQLite test timestamps can lose their timezone; production is UTC."""
    if value is None:
        return False
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value) <= now


async def reprocess_legacy(
    session_factory: async_sessionmaker[AsyncSession], store: ObjectStore, queue: JobQueue,
) -> None:
    """Reserve eligible legacy attempts and publish only after transaction commit.

    Repeated executions republish a pending revision after a broker outage. The
    worker's conditional claim makes duplicate deliveries harmless.
    """
    repo = DiarizationRepository(session_factory)
    async with session_factory() as session:
        meeting_ids = (await session.scalars(
            select(Diarization.meeting_id).where(Diarization.is_legacy.is_(True))
            .distinct()
        )).all()

    for meeting_id in meeting_ids:
        pending_revision: int | None = None
        async with session_factory() as session, session.begin():
            # Serialize selection, inspection and reservation with all other revisions.
            meeting = await session.scalar(
                select(Meeting).where(Meeting.id == meeting_id).with_for_update()
            )
            if meeting is None:
                continue
            latest = await session.scalar(
                select(Diarization).where(Diarization.meeting_id == meeting_id)
                .order_by(Diarization.processing_revision.desc()).limit(1)
            )
            if latest is None or (not latest.is_legacy and latest.diarization_state != "pending"):
                continue  # Completed, terminal or in-progress new generation is immutable.
            transcript = await session.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id))
            if transcript is None or expired(transcript.expires_at, datetime.now(UTC)):
                continue  # Transcript retention is independent of audio retention.
            if latest.transcript_id != transcript.id:
                continue
            recording = await session.scalar(
                select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
            )
            if recording is None or not recording.audio_ref:
                continue  # Unknown is not proof of irreconstructibility.
            unavailable = expired(recording.expires_at, datetime.now(UTC))
            if not unavailable:
                availability = await store.inspect(recording.audio_ref)
                if availability not in {"available", "missing"}:
                    raise ValueError("object availability response is invalid")
                unavailable = availability == "missing"
            attempt = await repo.reserve_next_revision(
                session, meeting_id, transcript.id, audio_unavailable=unavailable,
            )
            if attempt.diarization_state == "pending":
                pending_revision = attempt.processing_revision
        if pending_revision is not None:
            await repo.publish_pending_revision(meeting_id, pending_revision, queue)


async def _run_command() -> None:
    from app.infra.database import create_engine, create_session_factory
    from app.infra.object_store import create_object_store
    from app.infra.queue import create_job_queue

    engine = create_engine()
    queue = create_job_queue()
    try:
        await queue.connect()
        try:
            await reprocess_legacy(create_session_factory(engine), create_object_store(), queue)
        finally:
            await queue.disconnect()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explicit legacy diarization backfill")
    parser.add_argument("--execute", action="store_true", help="Reserve and publish eligible attempts")
    args = parser.parse_args()
    if not args.execute:
        parser.error("no data accessed; pass --execute only after operator approval")
    asyncio.run(_run_command())
