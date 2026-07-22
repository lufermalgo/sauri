"""Contract for PATCH/DELETE /api/v1/meetings/{id} — managing My_Notes (rename, delete).

Validates: note management (rename and delete) from the Side_Panel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import (
    Diarization,
    Meeting,
    SessionRecording,
    Speaker,
    SpeakerAssignment,
    SpeechTurn,
    Transcript,
)

USER_ID = "user-note-management"
OTHER_USER_ID = "other-user"


def _auth_header(user_id: str = USER_ID) -> dict[str, str]:
    token = create_token(user_id, "management@sauri.local", "Management Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _session_factory(api_db_url: str):
    engine = create_async_engine(api_db_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _create_meeting(api_db_url: str, meeting_id: str, created_by: str = USER_ID) -> None:
    session_factory, engine = await _session_factory(api_db_url)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/abc-defg-hij",
                title="Test Meeting",
                origin="link",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
        )
    await engine.dispose()


# ---------------------------------------------------------------------------
# PATCH /{meeting_id} — rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_200_updates_title(api_client: AsyncClient, api_db_url: str):
    meeting_id = str(uuid.uuid4())
    await _create_meeting(api_db_url, meeting_id)

    resp = await api_client.patch(
        f"/api/v1/meetings/{meeting_id}",
        json={"title": "Renamed Sales Meeting"},
        headers=_auth_header(),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed Sales Meeting"

    listing = await api_client.get("/api/v1/meetings/", headers=_auth_header())
    assert listing.json()[0]["title"] == "Renamed Sales Meeting"


@pytest.mark.asyncio
async def test_rename_404_nonexistent_meeting(api_client: AsyncClient):
    resp = await api_client.patch(
        f"/api/v1/meetings/{uuid.uuid4()}",
        json={"title": "X"},
        headers=_auth_header(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_404_meeting_of_another_user(api_client: AsyncClient, api_db_url: str):
    meeting_id = str(uuid.uuid4())
    await _create_meeting(api_db_url, meeting_id, created_by=OTHER_USER_ID)

    resp = await api_client.patch(
        f"/api/v1/meetings/{meeting_id}",
        json={"title": "Intento ajeno"},
        headers=_auth_header(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_422_empty_title(api_client: AsyncClient, api_db_url: str):
    meeting_id = str(uuid.uuid4())
    await _create_meeting(api_db_url, meeting_id)

    resp = await api_client.patch(
        f"/api/v1/meetings/{meeting_id}",
        json={"title": ""},
        headers=_auth_header(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rename_requires_authentication(api_client: AsyncClient):
    resp = await api_client.patch(
        f"/api/v1/meetings/{uuid.uuid4()}", json={"title": "X"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /{meeting_id} — delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_204_removes_the_meeting(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://localhost:1")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "test-bucket")
    monkeypatch.setenv("MINIO_ROOT_USER", "test")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test")

    meeting_id = str(uuid.uuid4())
    await _create_meeting(api_db_url, meeting_id)

    resp = await api_client.delete(f"/api/v1/meetings/{meeting_id}", headers=_auth_header())
    assert resp.status_code == 204

    listing = await api_client.get("/api/v1/meetings/", headers=_auth_header())
    assert listing.json() == []


@pytest.mark.asyncio
async def test_delete_404_nonexistent_meeting(api_client: AsyncClient):
    resp = await api_client.delete(f"/api/v1/meetings/{uuid.uuid4()}", headers=_auth_header())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_404_meeting_of_another_user(api_client: AsyncClient, api_db_url: str):
    meeting_id = str(uuid.uuid4())
    await _create_meeting(api_db_url, meeting_id, created_by=OTHER_USER_ID)

    resp = await api_client.delete(f"/api/v1/meetings/{meeting_id}", headers=_auth_header())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_requires_authentication(api_client: AsyncClient):
    resp = await api_client.delete(f"/api/v1/meetings/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_with_full_diarization_does_not_violate_fk(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
):
    """A Meeting with Transcript + Diarization + Speaker + SpeakerAssignment +
    SessionRecording must be deletable without violating the FKs that lack
    ondelete=CASCADE (diarizations.meeting_id, diarizations.transcript_id,
    speaker_assignments.turn_id)."""
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://localhost:1")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "test-bucket")
    monkeypatch.setenv("MINIO_ROOT_USER", "test")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test")

    meeting_id = str(uuid.uuid4())
    transcript_id = str(uuid.uuid4())
    diarization_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    speaker_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    session_factory, engine = await _session_factory(api_db_url)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/abc-defg-hij",
                title="With diarization",
                origin="link",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=USER_ID,
                created_at=now,
            )
        )
        session.add(
            SessionRecording(
                id=str(uuid.uuid4()),
                meeting_id=meeting_id,
                idempotency_key=str(uuid.uuid4()),
                capture_origin="chrome_extension",
                audio_ref="recordings/audio.webm",
                video_ref=None,
                duration_seconds=10,
                interrupted=False,
                expires_at=None,
                finished_at=now,
            )
        )
        session.add(
            Transcript(
                id=transcript_id,
                meeting_id=meeting_id,
                language="es-CO",
                provider="local",
                supports_turns=True,
                expires_at=None,
                created_at=now,
            )
        )
        session.add(
            SpeechTurn(
                id=turn_id,
                transcript_id=transcript_id,
                text="Hola",
                start_ms=0,
                end_ms=1000,
                sequence=0,
            )
        )
        session.add(
            Diarization(
                id=diarization_id,
                meeting_id=meeting_id,
                transcript_id=transcript_id,
                provider="local",
                speaker_count=1,
                diarization_state="completed",
                failure_cause=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Speaker(
                id=speaker_id,
                diarization_id=diarization_id,
                raw_label="SPEAKER_00",
                label="Speaker 1",
                sequence=1,
            )
        )
        session.add(
            SpeakerAssignment(
                id=str(uuid.uuid4()),
                diarization_id=diarization_id,
                turn_id=turn_id,
                speaker_id=speaker_id,
            )
        )
    await engine.dispose()

    resp = await api_client.delete(f"/api/v1/meetings/{meeting_id}", headers=_auth_header())
    assert resp.status_code == 204

    listing = await api_client.get("/api/v1/meetings/", headers=_auth_header())
    assert listing.json() == []
