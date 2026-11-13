"""Contract for GET /api/v1/meetings/{id}/diarization (chrome-side-panel, Tarea 13.1).

Validates: Requirements 6.3, 14.1
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import (
    AccessLog,
    Diarization,
    Meeting,
    Speaker,
    SpeakerAssignment,
    SpeechTurn,
    Transcript,
)

USER_ID = "user-diar-test"


def _auth_header(user_id: str = USER_ID, is_sales: bool = True) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Diar Test", is_sales)
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
    assert body["processing_revision"] == 1
    assert body["latest_attempt"] == {
        "processing_revision": 1, "diarization_state": "completed", "failure_cause": None,
    }
    assert body["speaker_count"] == 1
    assert len(body["speakers"]) == 1
    assert body["speakers"][0]["label"] == "Speaker 1"
    assert body["speakers"][0]["sequence"] == 1
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["turn_id"] == turn_id
    assert body["assignments"][0]["speaker_id"] == speaker_id
    assert body["assignments"][0]["overlap_ms"] is None  # legacy assignment


@pytest.mark.parametrize("attempt_state", ["pending", "failed", "not_reconstructible"])
@pytest.mark.asyncio
async def test_diarization_keeps_completed_generation_separate_from_later_attempt(
    api_client: AsyncClient, api_db_url: str, attempt_state: str
) -> None:
    session_factory, engine = await _session_factory(api_db_url)
    meeting_id, transcript_id = str(uuid.uuid4()), str(uuid.uuid4())
    completed_id, attempted_id = str(uuid.uuid4()), str(uuid.uuid4())
    completed_speaker_id, attempted_speaker_id = str(uuid.uuid4()), str(uuid.uuid4())
    completed_turn_id, attempted_turn_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij", origin="link",
            calendar_invite_id=None, scheduled_start_time=None, process_state="completed",
            failure_cause=None, created_by=USER_ID, created_at=now,
        ))
        session.add(Transcript(
            id=transcript_id, meeting_id=meeting_id, language="es-CO", provider="local",
            supports_turns=True, expires_at=None, created_at=now,
        ))
        for turn_id, sequence in ((completed_turn_id, 0), (attempted_turn_id, 1)):
            session.add(SpeechTurn(
                id=turn_id, transcript_id=transcript_id, text="Synthetic speech",
                start_ms=sequence * 1000, end_ms=(sequence + 1) * 1000, sequence=sequence,
            ))
        for diarization_id, revision, state in (
            (completed_id, 1, "completed"), (attempted_id, 2, attempt_state),
        ):
            session.add(Diarization(
                id=diarization_id, meeting_id=meeting_id, transcript_id=transcript_id,
                provider="local", speaker_count=1, processing_revision=revision,
                diarization_state=state,
                failure_cause="audio_unavailable" if state == "not_reconstructible" else None,
                created_at=now, updated_at=now,
            ))
        # Pending/terminal attempts normally have no children; synthetic stale children
        # ensure the endpoint never leaks them into the completed generation.
        for diarization_id, speaker_id, turn_id, overlap in (
            (completed_id, completed_speaker_id, completed_turn_id, 650),
            (attempted_id, attempted_speaker_id, attempted_turn_id, 300),
        ):
            session.add(Speaker(
                id=speaker_id, diarization_id=diarization_id, raw_label="SPEAKER_00",
                label="Speaker 1", sequence=1,
            ))
            session.add(SpeakerAssignment(
                id=str(uuid.uuid4()), diarization_id=diarization_id,
                turn_id=turn_id, speaker_id=speaker_id, overlap_ms=overlap,
            ))
    await engine.dispose()

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/diarization", headers=_auth_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["diarization_id"] == completed_id
    assert body["processing_revision"] == 1
    assert body["diarization_state"] == "completed"
    assert body["latest_attempt"] == {
        "processing_revision": 2,
        "diarization_state": attempt_state,
        "failure_cause": "audio_unavailable" if attempt_state == "not_reconstructible" else None,
    }
    assert body["speakers"] == [{"id": completed_speaker_id, "label": "Speaker 1", "sequence": 1}]
    assert body["assignments"] == [{
        "turn_id": completed_turn_id, "speaker_id": completed_speaker_id, "overlap_ms": 650,
    }]
    assert attempted_speaker_id not in response.text
    assert attempted_turn_id not in response.text


@pytest.mark.asyncio
async def test_diarization_without_completed_generation_exposes_only_latest_attempt(
    api_client: AsyncClient, api_db_url: str
) -> None:
    session_factory, engine = await _session_factory(api_db_url)
    meeting_id, transcript_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij", origin="link",
            calendar_invite_id=None, scheduled_start_time=None, process_state="completed",
            failure_cause=None, created_by=USER_ID, created_at=now,
        ))
        session.add(Transcript(
            id=transcript_id, meeting_id=meeting_id, language="es-CO", provider="local",
            supports_turns=True, expires_at=None, created_at=now,
        ))
        session.add(Diarization(
            id=str(uuid.uuid4()), meeting_id=meeting_id, transcript_id=transcript_id,
            provider="local", speaker_count=0, processing_revision=1,
            diarization_state="not_reconstructible", failure_cause="audio_unavailable",
            created_at=now, updated_at=now,
        ))
    await engine.dispose()

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/diarization", headers=_auth_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["processing_revision"] is None
    assert body["diarization_state"] is None
    assert body["speakers"] == []
    assert body["assignments"] == []
    assert body["latest_attempt"] == {
        "processing_revision": 1, "diarization_state": "not_reconstructible",
        "failure_cause": "audio_unavailable",
    }


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


@pytest.mark.asyncio
async def test_diarization_is_hidden_from_another_meeting_owner(
    api_client: AsyncClient, api_db_url: str
) -> None:
    owner_id = "diarization-owner-synthetic"
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
                origin="link",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=owner_id,
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
                text="Synthetic confidential speech",
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
                label="Synthetic Speaker",
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

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/diarization", headers=_auth_header()
    )

    assert response.status_code == 404
    assert diarization_id not in response.text
    assert "Synthetic Speaker" not in response.text

    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(AccessLog).where(AccessLog.user_id == USER_ID)
        )
        records = result.scalars().all()
    await engine.dispose()
    assert len(records) == 1
    assert records[0].result == "denied"
    assert records[0].resource == f"GET /api/v1/meetings/{meeting_id}/diarization"


@pytest.mark.asyncio
async def test_diarization_requires_sales_authorization_and_audits_denial(
    api_client: AsyncClient, api_db_url: str
) -> None:
    user_id = "unauthorized-diarization-user"
    response = await api_client.get(
        f"/api/v1/meetings/{uuid.uuid4()}/diarization",
        headers=_auth_header(user_id, is_sales=False),
    )

    assert response.status_code == 403
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(AccessLog).where(AccessLog.user_id == user_id)
        )
        records = result.scalars().all()
    await engine.dispose()
    assert len(records) == 1
    assert records[0].result == "denied"
