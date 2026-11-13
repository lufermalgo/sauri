"""T9/#277 RED: authenticated summary requests freeze an owned template at acceptance.

The real FastAPI app and database are used; no summary route, service or queue is mocked.
The missing route must fail as an HTTP assertion, not an import/collection error.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import Meeting, SummaryRequestOutbox, SummaryTemplate, Transcript, User
from app.main import app


def _id() -> str:
    return str(uuid4())


def _headers(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user, f'{user}@example.test', 'Synthetic', True)}"}


@pytest.fixture
async def summary_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str, str, str]]:
    """Persist a completed synthetic transcript and two different owners' templates."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'requests.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner, other, meeting_id, transcript_id, own_template, foreign_template = (_id() for _ in range(6))
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        for user in (owner, other):
            session.add(User(id=user, email=f"{user}@example.test", name="Synthetic",
                             password_hash="test-only", is_sales=True, created_at=now))
        session.add(Meeting(id=meeting_id, meet_link="https://meet.google.com/abc-defg-hij",
                            origin="manual", calendar_invite_id=None, scheduled_start_time=None,
                            process_state="completed", failure_cause=None, created_by=owner, created_at=now))
        session.add(Transcript(id=transcript_id, meeting_id=meeting_id, language="es-CO",
                               provider="synthetic", supports_turns=False, expires_at=None, created_at=now))
        await session.flush()
        for user, template, instructions in (
            (owner, own_template, "  Exactly these opaque instructions.\n"),
            (other, foreign_template, "Private foreign instructions"),
        ):
            session.add(SummaryTemplate(id=template, owner_user_id=user, category_id=None,
                                        name="Synthetic template", version=1, instructions=instructions,
                                        created_at=now, updated_at=now))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory, owner, other, meeting_id, own_template, foreign_template
    await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_owned_request_freezes_version_instructions_and_increments_generation(
    summary_api: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str, str, str],
) -> None:
    client, factory, owner, _, meeting, own, _ = summary_api
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    first = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    assert first.status_code == 202, first.text
    assert first.json()["generation"] == 1
    event_id = first.json()["event_id"]
    async with factory() as session:
        snapshot = await session.get(SummaryRequestOutbox, event_id)
        assert snapshot is not None
        assert (snapshot.meeting_id, snapshot.template_id, snapshot.template_version,
                snapshot.instructions_snapshot, snapshot.generation, snapshot.status) == (
                    meeting, own, 1, "  Exactly these opaque instructions.\n", 1, "pending")
        assert snapshot.delivered_at is None
    async with factory() as session, session.begin():
        template = await session.get(SummaryTemplate, own)
        assert template is not None
        template.instructions = "Edited after acceptance"
        template.version = 2
    second = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    assert second.status_code == 202, second.text
    assert second.json()["generation"] == 2
    assert second.json()["event_id"] != event_id
    async with factory() as session:
        original = await session.get(SummaryRequestOutbox, event_id)
        updated = await session.get(SummaryRequestOutbox, second.json()["event_id"])
        assert original is not None and updated is not None
        assert (original.template_version, original.instructions_snapshot) == (
            1, "  Exactly these opaque instructions.\n")
        assert (updated.template_version, updated.instructions_snapshot) == (2, "Edited after acceptance")


@pytest.mark.asyncio
async def test_implicit_request_resolves_current_personal_default_at_acceptance(
    summary_api: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str, str, str],
) -> None:
    client, factory, owner, _, meeting, own, foreign = summary_api
    async with factory() as session, session.begin():
        user = await session.get(User, owner)
        assert user is not None
        user.default_summary_template_id = own
    response = await client.post(f"/api/v1/meetings/{meeting}/summary-requests", json={}, headers=_headers(owner))
    assert response.status_code == 202, response.text
    async with factory() as session:
        snapshot = await session.get(SummaryRequestOutbox, response.json()["event_id"])
        assert snapshot is not None
        assert (snapshot.template_id, snapshot.template_version, snapshot.instructions_snapshot) == (
            own, 1, "  Exactly these opaque instructions.\n")
    # A later default change applies to the next request, never to this event.
    replacement = _id()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(SummaryTemplate(id=replacement, owner_user_id=owner, category_id=None,
                                    name="Replacement", version=1, instructions="New default instructions",
                                    created_at=now, updated_at=now))
        await session.flush()
        user = await session.get(User, owner)
        assert user is not None
        user.default_summary_template_id = replacement
    later = await client.post(f"/api/v1/meetings/{meeting}/summary-requests", json={}, headers=_headers(owner))
    assert later.status_code == 202, later.text
    async with factory() as session:
        snapshot = await session.get(SummaryRequestOutbox, response.json()["event_id"])
        next_snapshot = await session.get(SummaryRequestOutbox, later.json()["event_id"])
        assert snapshot is not None and next_snapshot is not None
        assert (snapshot.template_id, snapshot.instructions_snapshot) == (
            own, "  Exactly these opaque instructions.\n")
        assert (next_snapshot.template_id, next_snapshot.instructions_snapshot) == (
            replacement, "New default instructions")
    # This does NOT request a summary without a default: that outcome is gated.
    assert foreign not in (own, replacement)


@pytest.mark.asyncio
async def test_foreign_template_and_meeting_cannot_enqueue_or_disclose(
    summary_api: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str, str, str],
) -> None:
    client, factory, owner, other, meeting, _, foreign = summary_api
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    denied = await client.post(path, json={"template_id": foreign}, headers=_headers(owner))
    assert denied.status_code == 422, denied.text
    assert "Private foreign instructions" not in denied.text
    not_owner = await client.post(path, json={"template_id": foreign}, headers=_headers(other))
    assert not_owner.status_code == 404, not_owner.text
    no_auth = await client.post(path, json={"template_id": foreign})
    assert no_auth.status_code == 401, no_auth.text
    async with factory() as session:
        assert (await session.scalars(select(SummaryRequestOutbox))).all() == []


@pytest.mark.asyncio
async def test_request_status_latest_resumes_and_never_replaces_old_status(
    summary_api: tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str, str, str],
) -> None:
    client, factory, owner, other, meeting, own, _ = summary_api
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    accepted = []
    for _ in range(2):
        response = await client.post(path, json={"template_id": own}, headers=_headers(owner))
        assert response.status_code == 202, response.text
        accepted.append(response.json())
    async with factory() as session, session.begin():
        previous = await session.get(SummaryRequestOutbox, accepted[0]["event_id"])
        assert previous is not None
        previous.status = "succeeded"
    latest = await client.get(f"{path}/latest", headers=_headers(owner))
    assert latest.status_code == 200, latest.text
    assert {key: latest.json()[key] for key in ("event_id", "generation", "status")} == {
        "event_id": accepted[1]["event_id"], "generation": 2, "status": "pending"}
    previous_response = await client.get(f"{path}/{accepted[0]['event_id']}", headers=_headers(owner))
    assert previous_response.status_code == 200, previous_response.text
    assert previous_response.json()["status"] == "succeeded"
    foreign = await client.get(f"{path}/{accepted[0]['event_id']}", headers=_headers(other))
    assert foreign.status_code == 404, foreign.text
    async with factory() as session, session.begin():
        current = await session.get(SummaryRequestOutbox, accepted[1]["event_id"])
        assert current is not None
        current.status = "running"
    running = await client.get(f"{path}/latest", headers=_headers(owner))
    assert running.status_code == 200 and running.json()["status"] == "running", running.text
    async with factory() as session, session.begin():
        current = await session.get(SummaryRequestOutbox, accepted[1]["event_id"])
        assert current is not None
        current.status = "failed"
    failed = await client.get(f"{path}/{accepted[1]['event_id']}", headers=_headers(owner))
    assert failed.status_code == 200 and failed.json()["status"] == "failed", failed.text
    assert "exception" not in failed.text.lower()
