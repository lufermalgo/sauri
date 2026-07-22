"""Property test for full-data retention deletion (worker.py).

# Feature: meeting-capture-transcription, Property 12: Full-data retention deletion
Task: 12.4 — Validates: Requirements 6.3, 6.6
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Meeting, SessionRecording, Transcript
from app.infra.object_store import AlmacenDeObjetos
from app.retention.worker import run_retention_deletion


class _FakeObjectStore(AlmacenDeObjetos):
    """In-memory fake of AlmacenDeObjetos for tests."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def guardar(self, clave: str, contenido: bytes, content_type: str = "application/octet-stream") -> str:
        self._objects[clave] = contenido
        return clave

    async def obtener(self, referencia: str) -> bytes:
        return self._objects[referencia]

    async def eliminar(self, referencia: str) -> None:
        self._objects.pop(referencia, None)

    async def url_temporal_de_lectura(self, referencia: str, ttl_seconds: int = 3600) -> str:
        return f"https://example.local/{referencia}?ttl={ttl_seconds}"

    def existe(self, referencia: str) -> bool:
        return referencia in self._objects


def _create_meeting(meeting_id: str) -> Meeting:
    return Meeting(
        id=meeting_id,
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="completed",
        failure_cause=None,
        created_by="test-user",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Property 12: Full-data retention deletion
# Feature: meeting-capture-transcription, Property 12: Full-data retention deletion
# Validates: Requirements 6.3, 6.6
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(has_video=st.booleans())
@pytest.mark.asyncio
async def test_property_12_deletion_removes_audio_video_and_transcript(
    db_session: AsyncSession, has_video: bool
) -> None:
    """Deleting an expired Recording expires its audio, its video (if present), and its associated Transcript."""
    meeting_id = str(uuid.uuid4())
    object_store = _FakeObjectStore()

    audio_ref = f"audio/{uuid.uuid4()}.webm"
    video_ref = f"video/{uuid.uuid4()}.webm" if has_video else None
    await object_store.guardar(audio_ref, b"audio-bytes")
    if video_ref:
        await object_store.guardar(video_ref, b"video-bytes")

    now = datetime.now(UTC)
    db_session.add(_create_meeting(meeting_id))
    db_session.add(
        SessionRecording(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            idempotency_key=str(uuid.uuid4()),
            capture_origin="chrome_extension",
            audio_ref=audio_ref,
            video_ref=video_ref,
            duration_seconds=60,
            interrupted=False,
            expires_at=now - timedelta(seconds=1),
            finished_at=now - timedelta(days=91),
        )
    )
    db_session.add(
        Transcript(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            language="es-CO",
            provider="local",
            supports_turns=True,
            expires_at=None,
            created_at=now - timedelta(days=91),
        )
    )
    await db_session.commit()

    await run_retention_deletion(db_session, object_store, now)

    assert not object_store.existe(audio_ref)
    if video_ref:
        assert not object_store.existe(video_ref)

    recording_result = await db_session.execute(
        select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
    )
    assert recording_result.scalar_one_or_none() is None

    transcript_result = await db_session.execute(
        select(Transcript).where(Transcript.meeting_id == meeting_id)
    )
    assert transcript_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_property_12_unexpired_are_preserved(db_session: AsyncSession) -> None:
    """Recordings and Transcripts that haven't expired aren't touched."""
    meeting_id = str(uuid.uuid4())
    object_store = _FakeObjectStore()
    now = datetime.now(UTC)

    audio_ref = f"audio/{uuid.uuid4()}.webm"
    await object_store.guardar(audio_ref, b"audio-bytes")

    db_session.add(_create_meeting(meeting_id))
    db_session.add(
        SessionRecording(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            idempotency_key=str(uuid.uuid4()),
            capture_origin="chrome_extension",
            audio_ref=audio_ref,
            video_ref=None,
            duration_seconds=60,
            interrupted=False,
            expires_at=now + timedelta(days=1),
            finished_at=now,
        )
    )
    await db_session.commit()

    await run_retention_deletion(db_session, object_store, now)

    assert object_store.existe(audio_ref)
    result = await db_session.execute(
        select(SessionRecording).where(SessionRecording.meeting_id == meeting_id)
    )
    assert result.scalar_one_or_none() is not None
