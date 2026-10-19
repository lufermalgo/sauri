"""Contract for GET /api/v1/meetings/{id}/diarization (chrome-side-panel, Tarea 13.1).

Validates: Requirements 6.3, 14.1
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import (
    Diarization,
    Meeting,
    Speaker,
    SpeakerAssignment,
    SpeechTurn,
    Transcript,
)

USER_ID = "user-diar-test"


def _auth_header() -> dict[str, str]:
    token = create_token(USER_ID, "diar@sauri.local", "Diar Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _session_factory(api_db_url: str) -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    engine = create_async_engine(api_db_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


@pytest.mark.asyncio
async def test_diarization_200_with_speakers_and_assignments(api_client: AsyncClient, api_db_url: str) -> None:
    session_factory, engine = await _session_factory(api_db_url)
    meeting_id = str(uuid.uuid4())
    transcript_id = str(uuid.uuid4())
    diarization_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    speaker_id = str(uuid.uuid4())
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

    resp = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/diarization", headers=_auth_header()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["diarization_id"] == diarization_id
    assert body["meeting_id"] == meeting_id
    assert body["diarization_state"] == "completed"
    assert body["speaker_count"] == 1
    assert len(body["speakers"]) == 1
    assert body["speakers"][0]["label"] == "Speaker 1"
    assert body["speakers"][0]["sequence"] == 1
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["turn_id"] == turn_id
    assert body["assignments"][0]["speaker_id"] == speaker_id


@pytest.mark.asyncio
async def test_diarization_404_nonexistent_meeting(api_client: AsyncClient) -> None:
    resp = await api_client.get(
        f"/api/v1/meetings/{uuid.uuid4()}/diarization", headers=_auth_header()
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diarization_404_without_diarization(api_client: AsyncClient, api_db_url: str) -> None:
    session_factory, engine = await _session_factory(api_db_url)
    meeting_id = str(uuid.uuid4())
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
    await engine.dispose()

    resp = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/diarization", headers=_auth_header()
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_diarization_requires_authentication(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"/api/v1/meetings/{uuid.uuid4()}/diarization")
    assert resp.status_code == 401
