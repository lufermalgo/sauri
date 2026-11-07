"""Authorization contracts for meeting detail, mutation, and join routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import AccessLog, Meeting
from app.meetings import router

OWNER_ID = "meeting-route-owner"
OTHER_ID = "meeting-route-other"
NON_SALES_ID = "meeting-route-non-sales"
BASE_PATH = "/api/v1/meetings"


def _headers(user_id: str, is_sales: bool = True) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "Synthetic User", is_sales)
    return {"Authorization": f"Bearer {token}"}


async def _create_meeting(
    api_db_url: str, *, owner: str = OWNER_ID, state: str = "queued", title: str = "Private synthetic title"
) -> str:
    meeting_id = str(uuid.uuid4())
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(Meeting(
            id=meeting_id,
            meet_link="https://meet.google.com/abc-defg-hij",
            title=title,
            origin="link",
            calendar_invite_id=None,
            scheduled_start_time=None,
            process_state=state,
            failure_cause=None,
            created_by=owner,
            created_at=datetime.now(UTC),
        ))
    await engine.dispose()
    return meeting_id


async def _audit_rows(api_db_url: str, user_id: str) -> list[AccessLog]:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(AccessLog).where(AccessLog.user_id == user_id))
        rows = list(result.scalars().all())
    await engine.dispose()
    return rows


async def _meeting_state(api_db_url: str, meeting_id: str) -> str | None:
    engine = create_async_engine(api_db_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        meeting = await session.get(Meeting, meeting_id)
        state = meeting.process_state if meeting else None
    await engine.dispose()
    return state


@pytest.mark.asyncio
async def test_get_meeting_authorizes_owner_and_preserves_response(api_client: AsyncClient, api_db_url: str) -> None:
    meeting_id = await _create_meeting(api_db_url)
    response = await api_client.get(f"{BASE_PATH}/{meeting_id}", headers=_headers(OWNER_ID))
    assert response.status_code == 200
    assert response.json() == {"meeting_id": meeting_id, "title": "Private synthetic title", "process_state": "queued"}
    assert not await _audit_rows(api_db_url, OWNER_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize(("user_id", "is_sales", "status_code", "resource"), [
    (OTHER_ID, True, 404, "GET /api/v1/meetings/"),
    (NON_SALES_ID, False, 403, "GET /api/v1/meetings/"),
])
async def test_get_meeting_denials_are_audited(
    api_client: AsyncClient, api_db_url: str, user_id: str, is_sales: bool, status_code: int, resource: str
) -> None:
    meeting_id = await _create_meeting(api_db_url)
    response = await api_client.get(f"{BASE_PATH}/{meeting_id}", headers=_headers(user_id, is_sales))
    assert response.status_code == status_code
    expected_detail = (
        "Meeting not found" if status_code == 404 else "Access restricted to authorized sales users"
    )
    assert response.json()["detail"] == expected_detail
    assert "Private synthetic title" not in response.text
    rows = await _audit_rows(api_db_url, user_id)
    assert len(rows) == 1
    assert rows[0].result == "denied"
    assert rows[0].resource == f"{resource}{meeting_id}"


@pytest.mark.asyncio
async def test_get_meeting_requires_authentication(api_client: AsyncClient) -> None:
    response = await api_client.get(f"{BASE_PATH}/{uuid.uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_request_join_owner_keeps_success_and_nonqueued_conflict(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[dict[str, object]] = []
    queue = type("Queue", (), {
        "connect": AsyncMock(), "disconnect": AsyncMock(),
        "publish": AsyncMock(side_effect=lambda **kwargs: published.append(kwargs)),
    })()
    monkeypatch.setattr(router, "_get_queue", lambda: queue)
    meeting_id = await _create_meeting(api_db_url)
    response = await api_client.post(f"{BASE_PATH}/{meeting_id}/request-join", headers=_headers(OWNER_ID))
    assert response.status_code == 200
    assert response.json() == {"meeting_id": meeting_id, "process_state": "joining"}
    queue.publish.assert_awaited_once_with(topic="join", message={"meeting_id": meeting_id, "meet_link": "https://meet.google.com/abc-defg-hij"})

    completed_id = await _create_meeting(api_db_url, state="completed")
    conflict = await api_client.post(f"{BASE_PATH}/{completed_id}/request-join", headers=_headers(OWNER_ID))
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Cannot request join: the meeting is in state 'completed'"


@pytest.mark.asyncio
@pytest.mark.parametrize(("user_id", "is_sales", "status_code"), [
    (OTHER_ID, True, 404),
    (NON_SALES_ID, False, 403),
])
async def test_request_join_denials_do_not_change_state_publish_or_skip_audit(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch,
    user_id: str, is_sales: bool, status_code: int,
) -> None:
    queue = type("Queue", (), {"connect": AsyncMock(), "disconnect": AsyncMock(), "publish": AsyncMock()})()
    monkeypatch.setattr(router, "_get_queue", lambda: queue)
    meeting_id = await _create_meeting(api_db_url)
    response = await api_client.post(f"{BASE_PATH}/{meeting_id}/request-join", headers=_headers(user_id, is_sales))
    assert response.status_code == status_code
    assert await _meeting_state(api_db_url, meeting_id) == "queued"
    queue.publish.assert_not_awaited()
    queue.connect.assert_not_awaited()
    rows = await _audit_rows(api_db_url, user_id)
    assert len(rows) == 1
    assert rows[0].result == "denied"
    assert rows[0].resource == f"POST /api/v1/meetings/{meeting_id}/request-join"


@pytest.mark.asyncio
async def test_request_join_with_unknown_meeting_id_is_non_disclosing_404(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing meeting id must be indistinguishable from one owned by someone else.

    Before B-2 the route answered 409 for a missing id, which let a non-owner probe
    for the existence of a meeting id by comparing the status code with the 404
    returned for a meeting owned by somebody else.
    """
    queue = type("Queue", (), {"connect": AsyncMock(), "disconnect": AsyncMock(), "publish": AsyncMock()})()
    monkeypatch.setattr(router, "_get_queue", lambda: queue)
    unknown_id = str(uuid.uuid4())

    response = await api_client.post(f"{BASE_PATH}/{unknown_id}/request-join", headers=_headers(OWNER_ID))

    assert response.status_code == 404
    assert response.json()["detail"] == "Meeting not found"
    assert unknown_id not in response.text
    queue.publish.assert_not_awaited()
    queue.connect.assert_not_awaited()
    rows = await _audit_rows(api_db_url, OWNER_ID)
    assert len(rows) == 1
    assert rows[0].result == "denied"
    assert rows[0].resource == f"POST /api/v1/meetings/{unknown_id}/request-join"


@pytest.mark.asyncio
async def test_request_join_requires_authentication(api_client: AsyncClient) -> None:
    response = await api_client.post(f"{BASE_PATH}/{uuid.uuid4()}/request-join")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "user_id", "is_sales", "status_code"), [
    ("patch", OTHER_ID, True, 404),
    ("patch", NON_SALES_ID, False, 403),
    ("delete", OTHER_ID, True, 404),
    ("delete", NON_SALES_ID, False, 403),
])
async def test_mutation_denials_are_audited_and_preserve_meeting(
    api_client: AsyncClient, api_db_url: str, monkeypatch: pytest.MonkeyPatch,
    method: str, user_id: str, is_sales: bool, status_code: int,
) -> None:
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://localhost:1")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "test-bucket")
    monkeypatch.setenv("MINIO_ROOT_USER", "test")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test")
    meeting_id = await _create_meeting(api_db_url)
    request = getattr(api_client, method)
    kwargs = {"headers": _headers(user_id, is_sales)}
    if method == "patch":
        kwargs["json"] = {"title": "Unauthorized rename"}
    response = await request(f"{BASE_PATH}/{meeting_id}", **kwargs)
    assert response.status_code == status_code
    assert await _meeting_state(api_db_url, meeting_id) == "queued"
    rows = await _audit_rows(api_db_url, user_id)
    assert len(rows) == 1
    assert rows[0].result == "denied"
    assert rows[0].resource == f"{method.upper()} /api/v1/meetings/{meeting_id}"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post", "patch", "delete"])
async def test_meeting_routes_require_authentication(api_client: AsyncClient, method: str) -> None:
    meeting_id = str(uuid.uuid4())
    path = f"{BASE_PATH}/{meeting_id}"
    if method == "post":
        path += "/request-join"
    request = getattr(api_client, method)
    kwargs = {"json": {"title": "Synthetic title"}} if method == "patch" else {}
    response = await request(path, **kwargs)
    assert response.status_code == 401
