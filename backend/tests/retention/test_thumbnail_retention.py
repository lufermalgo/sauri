"""Retention deletion removes the thumbnail object together with the recording."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.models import Meeting, SessionRecording
from app.infra.object_store import ObjectStore
from app.retention.worker import run_retention_deletion


class _Store(ObjectStore):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_on: set[str] = set()

    async def save(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        self.objects[key] = content
        return key

    async def get(self, reference: str) -> bytes:
        return self.objects[reference]

    async def delete(self, reference: str) -> None:
        if reference in self.fail_on:
            raise OSError("store down")
        self.objects.pop(reference, None)

    async def temporary_read_url(self, reference: str, ttl_seconds: int = 3600) -> str:
        return reference


async def _expired_recording(factory: async_sessionmaker[AsyncSession], store: _Store) -> tuple[str, str, str]:
    meeting_id, recording_id = str(uuid.uuid4()), str(uuid.uuid4())
    audio, thumb = f"recordings/{meeting_id}/a/audio", f"recordings/{meeting_id}/{recording_id}/thumbnail.jpg"
    await store.save(audio, b"a")
    await store.save(thumb, b"t")
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link=None, origin="manual", process_state="completed",
            created_by="owner", created_at=now,
        ))
        await session.flush()
        session.add(SessionRecording(
            id=recording_id, meeting_id=meeting_id, idempotency_key=str(uuid.uuid4()),
            capture_origin="web_upload", audio_ref=audio, video_ref=None, duration_seconds=1,
            interrupted=False, finished_at=now, expires_at=now - timedelta(days=1),
            thumbnail_ref=thumb, thumbnail_state="ready",
        ))
    return recording_id, audio, thumb


@pytest.mark.asyncio
async def test_expired_recording_takes_its_thumbnail_with_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = _Store()
    _, audio, thumb = await _expired_recording(session_factory, store)

    async with session_factory() as session:
        await run_retention_deletion(session, store, datetime.now(UTC).replace(tzinfo=None))

    assert audio not in store.objects and thumb not in store.objects


@pytest.mark.asyncio
async def test_a_failing_thumbnail_delete_does_not_block_the_rest_of_the_cleanup(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = _Store()
    recording_id, audio, thumb = await _expired_recording(session_factory, store)
    store.fail_on.add(thumb)

    async with session_factory() as session:
        await run_retention_deletion(session, store, datetime.now(UTC).replace(tzinfo=None))

    assert audio not in store.objects
    async with session_factory() as session:
        assert await session.get(SessionRecording, recording_id) is None
