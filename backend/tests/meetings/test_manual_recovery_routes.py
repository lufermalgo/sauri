"""Synthetic API contracts for disabled manual meeting recovery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting, MeetingRecoveryOperation, MeetingRecoveryOutbox
from app.meetings import router

BASE_PATH = "/api/v1/meetings"
OWNER_ID = "manual-recovery-owner"
OTHER_ID = "manual-recovery-other"
PRIVATE_TITLE = "Synthetic recovery fixture title"


def _headers(user_id: str) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Synthetic User", True)
    return {"Authorization": f"Bearer {token}"}


async def _create_meeting(api_db_url: str, *, owner: str = OWNER_ID) -> str:
    meeting_id = str(uuid.uuid4())
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id,
            meet_link="https://meet.google.com/syn-tet-ic0",
            title=PRIVATE_TITLE,
            origin="link",
            calendar_invite_id=None,
            scheduled_start_time=None,
            process_state="queued",
            failure_cause=None,
            created_by=owner,
            created_at=datetime.now(UTC),
        ))
    await engine.dispose()
    return meeting_id


async def _database_snapshot(api_db_url: str, meeting_id: str) -> tuple[tuple[object, ...], int, int]:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None
        meeting_values = (
            meeting.id,
            meeting.title,
            meeting.process_state,
            meeting.failure_cause,
            meeting.created_by,
        )
        operations = await session.scalar(
            select(func.count()).select_from(MeetingRecoveryOperation).where(
                MeetingRecoveryOperation.meeting_id == meeting_id
            )
        )
        outbox = await session.scalar(
            select(func.count())
            .select_from(MeetingRecoveryOutbox)
            .join(MeetingRecoveryOperation, MeetingRecoveryOutbox.operation_id == MeetingRecoveryOperation.id)
            .where(MeetingRecoveryOperation.meeting_id == meeting_id)
        )
    await engine.dispose()
    return meeting_values, int(operations or 0), int(outbox or 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [None, "disabled", "pilot", "invalid"])
async def test_disabled_owner_recovery_is_content_free_noop(
    api_client: AsyncClient,
    api_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    mode: str | None,
) -> None:
    if mode is None:
        monkeypatch.delenv("SAURI_MANUAL_RECOVERY_MODE", raising=False)
    else:
        monkeypatch.setenv("SAURI_MANUAL_RECOVERY_MODE", mode)
    monkeypatch.delenv("SAURI_RECOVERY_PILOT_MEETING_ID", raising=False)
    queue = type("Queue", (), {
        "connect": AsyncMock(),
        "disconnect": AsyncMock(),
        "publish": AsyncMock(),
    })()
    monkeypatch.setattr(router, "_get_queue", lambda: queue)

    meeting_id = await _create_meeting(api_db_url)
    if mode == "pilot":
        monkeypatch.setenv("SAURI_RECOVERY_PILOT_MEETING_ID", meeting_id)
    before = await _database_snapshot(api_db_url, meeting_id)
    response = await api_client.post(
        f"{BASE_PATH}/{meeting_id}/recover",
        headers={**_headers(OWNER_ID), "Idempotency-Key": str(uuid.uuid4())},
    )

    # The approved contract specifies a no-op reason, not an HTTP status mapping.
    assert response.status_code != 404, "the owner-scoped recovery route must be registered"
    body = response.json()
    assert body["status"] == "pilot_not_armed"
    assert body["reason_code"] == "pilot_not_armed"
    assert set(body) == {"status", "reason_code"}
    assert PRIVATE_TITLE not in caplog.text
    assert PRIVATE_TITLE not in response.text
    assert await _database_snapshot(api_db_url, meeting_id) == before
    queue.publish.assert_not_awaited()
    queue.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_owner_recovery_is_nondisclosing_not_found(
    api_client: AsyncClient,
    api_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAURI_MANUAL_RECOVERY_MODE", "disabled")
    queue = type("Queue", (), {
        "connect": AsyncMock(),
        "disconnect": AsyncMock(),
        "publish": AsyncMock(),
    })()
    monkeypatch.setattr(router, "_get_queue", lambda: queue)

    meeting_id = await _create_meeting(api_db_url)
    before = await _database_snapshot(api_db_url, meeting_id)
    response = await api_client.post(
        f"{BASE_PATH}/{meeting_id}/recover",
        headers={**_headers(OTHER_ID), "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Meeting not found"
    assert PRIVATE_TITLE not in response.text
    assert meeting_id not in response.text
    absent = await api_client.post(
        f"{BASE_PATH}/{uuid.uuid4()}/recover",
        headers={**_headers(OTHER_ID), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert (absent.status_code, absent.json()) == (response.status_code, response.json())
    assert await _database_snapshot(api_db_url, meeting_id) == before
    queue.publish.assert_not_awaited()
    queue.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_requires_authentication(api_client: AsyncClient, api_db_url: str) -> None:
    meeting_id = await _create_meeting(api_db_url)
    before = await _database_snapshot(api_db_url, meeting_id)
    response = await api_client.post(
        f"{BASE_PATH}/{meeting_id}/recover", headers={"Idempotency-Key": "synthetic-request"}
    )
    assert response.status_code == 401
    assert PRIVATE_TITLE not in response.text
    assert await _database_snapshot(api_db_url, meeting_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "", "x" * 129])
async def test_recovery_requires_bounded_idempotency_key(
    api_client: AsyncClient, api_db_url: str, key: str | None,
) -> None:
    meeting_id = await _create_meeting(api_db_url)
    before = await _database_snapshot(api_db_url, meeting_id)
    headers = _headers(OWNER_ID)
    if key is not None:
        headers["Idempotency-Key"] = key
    response = await api_client.post(f"{BASE_PATH}/{meeting_id}/recover", headers=headers)
    assert response.status_code == 422
    assert PRIVATE_TITLE not in response.text
    assert await _database_snapshot(api_db_url, meeting_id) == before
