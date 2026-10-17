"""RED contract tests for authenticated, owner-scoped playback manifests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting, SessionRecording

OWNER_ID = "playback-owner"
OTHER_USER_ID = "playback-other"


def _auth_header(user_id: str = OWNER_ID) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Playback Test", True)
    return {"Authorization": f"Bearer {token}"}


async def _meeting_with_recording(api_db_url: str, *, owner_id: str = OWNER_ID) -> str:
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
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
                created_by=owner_id,
                created_at=now,
            )
        )
        session.add(
            SessionRecording(
                id=str(uuid.uuid4()),
                meeting_id=meeting_id,
                idempotency_key=str(uuid.uuid4()),
                capture_origin="chrome_extension",
                audio_ref="private/test/audio.webm",
                video_ref=None,
                duration_seconds=45,
                interrupted=False,
                expires_at=None,
                finished_at=now,
            )
        )
    await engine.dispose()
    return meeting_id


@pytest.mark.asyncio
async def test_playback_manifest_requires_authentication(api_client: AsyncClient):
    response = await api_client.get(f"/api/v1/meetings/{uuid.uuid4()}/playback")
    assert response.status_code == 401
    assert "audio_source" not in response.text
    assert "private/" not in response.text


@pytest.mark.asyncio
async def test_non_owner_cannot_receive_manifest_or_private_references(
    api_client: AsyncClient, api_db_url: str
):
    meeting_id = await _meeting_with_recording(api_db_url)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header(OTHER_USER_ID)
    )
    assert response.status_code == 404
    assert "private/test/audio.webm" not in response.text
    assert "audio_source" not in response.text


@pytest.mark.asyncio
async def test_missing_and_non_owned_meetings_are_indistinguishable(
    api_client: AsyncClient, api_db_url: str
):
    owned_id = await _meeting_with_recording(api_db_url)
    missing_id = str(uuid.uuid4())
    responses = [
        await api_client.get(
            f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header(OTHER_USER_ID)
        )
        for meeting_id in (owned_id, missing_id)
    ]
    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert all("private/test/audio.webm" not in response.text for response in responses)


@pytest.mark.asyncio
async def test_owner_manifest_contains_only_signed_playback_contract(
    api_client: AsyncClient, api_db_url: str
):
    meeting_id = await _meeting_with_recording(api_db_url)
    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/playback", headers=_auth_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meeting_id"] == meeting_id
    assert body["duration_seconds"] == 45
    assert body["audio_source"]["url"].startswith(("http://", "https://"))
    assert body["audio_source"]["source_id"]
    assert body["video_sources"] == []
    assert "private/test/audio.webm" not in response.text
    assert "audio_ref" not in body
    assert "object_ref" not in body


@pytest.mark.asyncio
async def test_invalid_token_cannot_receive_manifest(api_client: AsyncClient):
    response = await api_client.get(
        f"/api/v1/meetings/{uuid.uuid4()}/playback",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401
    assert "private/" not in response.text
