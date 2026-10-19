"""Additive contract: Turn's `id` on each segment of GET /transcript
(chrome-side-panel, Tarea 13.3). Validates: Requirements 8.1, 14.1, 14.2
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting, SpeechTurn, Transcript

USER_ID = "user-turno-test"


def _auth_header(user_id: str = USER_ID) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Turno Test", True)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_segments_include_the_turn_id(api_client: AsyncClient, api_db_url: str) -> None:
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    meeting_id = str(uuid.uuid4())
    transcript_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/abc-defg-hij",
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
                text="Hola mundo",
                start_ms=0,
                end_ms=1500,
                sequence=0,
            )
        )
    await engine.dispose()

    resp = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/transcript", headers=_auth_header()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["segments"]) == 1
    segment = body["segments"][0]
    assert segment["id"] == turn_id
    # Existing fields are preserved (additive change)
    assert segment["text"] == "Hola mundo"
    assert segment["start_ms"] == 0
    assert segment["end_ms"] == 1500
    assert segment["sequence"] == 0


@pytest.mark.asyncio
async def test_non_owner_cannot_read_transcript(api_client: AsyncClient, api_db_url: str):
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    meeting_id = str(uuid.uuid4())
    transcript_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(
            Meeting(
                id=meeting_id,
                meet_link="https://meet.google.com/abc-defg-hij",
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
                id=str(uuid.uuid4()),
                transcript_id=transcript_id,
                text="SYNTHETIC PRIVATE TRANSCRIPT TEXT",
                start_ms=0,
                end_ms=1500,
                sequence=0,
            )
        )
    await engine.dispose()

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/transcript",
        headers={"Authorization": f"Bearer {create_token('different-user', 'other@sauri.local', 'Other', True)}"},
    )
    assert response.status_code == 404
    assert "SYNTHETIC PRIVATE TRANSCRIPT TEXT" not in response.text


@pytest.mark.asyncio
async def test_transcript_requires_authentication(api_client: AsyncClient):
    response = await api_client.get(f"/api/v1/meetings/{uuid.uuid4()}/transcript")
    assert response.status_code == 401
    assert "segments" not in response.text
