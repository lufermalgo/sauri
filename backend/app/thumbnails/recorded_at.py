"""On-demand backfill: python -m app.thumbnails.recorded_at [--limit N].

Reads the creation date from the stored file of each web upload whose recording date is still the
date Sauri received it (or the browser's file date) and keeps it when the container has one.
Idempotent and read-only for media; prints only counts. Recordings from the Chrome extension are
skipped: their capture start is already the best source.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.database import create_engine, create_session_factory
from app.infra.models import Meeting, SessionRecording
from app.infra.object_store import ObjectStore, create_object_store
from app.meetings.recorded_at import SOURCE_FILE_MODIFIED, SOURCE_RECEIVED
from app.meetings.service import load_playback_source_inventory
from app.thumbnails.ffmpeg import MediaToolError, probe_media
from app.thumbnails.service import SOURCE_URL_TTL_SECONDS, note_creation_time

logger = logging.getLogger(__name__)

UPDATED = "updated"
NO_DATE = "no_creation_date"
UNREADABLE = "unreadable"
ERROR = "error"


async def _candidates(session: AsyncSession, limit: int | None) -> list[tuple[str, str]]:
    """(meeting_id, recording_id) of web uploads that a container date could still improve, newest first."""
    statement = (
        select(SessionRecording.meeting_id, SessionRecording.id)
        .join(Meeting, Meeting.id == SessionRecording.meeting_id)
        .where(
            SessionRecording.capture_origin == "web_upload",
            or_(
                Meeting.recorded_at_source.is_(None),
                Meeting.recorded_at_source.in_((SOURCE_RECEIVED, SOURCE_FILE_MODIFIED)),
            ),
        )
        .order_by(Meeting.created_at.desc())
    )
    if limit is not None:
        statement = statement.limit(limit)
    return [(meeting_id, recording_id) for meeting_id, recording_id in (await session.execute(statement)).all()]


async def backfill_recorded_at(
    session_factory: async_sessionmaker[AsyncSession], object_store: ObjectStore, *, limit: int | None = None
) -> Counter[str]:
    """Probe each candidate once; returns how many ended in each outcome."""
    async with session_factory() as session:
        candidates = await _candidates(session, limit)
    tally: Counter[str] = Counter()
    for meeting_id, recording_id in candidates:
        try:
            async with session_factory() as session:
                inventory = await load_playback_source_inventory(session, recording_id)
            if inventory is None or inventory.audio_source is None:
                tally[UNREADABLE] += 1
                continue
            url = await object_store.temporary_read_url(
                inventory.audio_source.object_ref, ttl_seconds=SOURCE_URL_TTL_SECONDS
            )
            probe = await probe_media(url)
            updated = await note_creation_time(session_factory, meeting_id, probe.creation_time)
            tally[UPDATED if updated else NO_DATE] += 1
        except MediaToolError as exc:
            logger.info("Could not probe recording_id=%s: %s", recording_id, exc)
            tally[UNREADABLE] += 1
        except Exception:
            logger.exception("Recording date backfill failed for recording_id=%s", recording_id)
            tally[ERROR] += 1
    return tally


async def _run(limit: int | None) -> None:
    engine = create_engine()
    try:
        tally = await backfill_recorded_at(create_session_factory(engine), create_object_store(), limit=limit)
    finally:
        await engine.dispose()
    summary = ", ".join(f"{name}={count}" for name, count in sorted(tally.items())) or "nothing to do"
    print(f"Recording date backfill finished: {summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill recording dates of old web uploads from their file metadata.")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many recordings")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(_run(args.limit))


if __name__ == "__main__":
    main()
