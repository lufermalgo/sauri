"""T9/#277 RED: authenticated summary requests freeze an owned template at acceptance.

The real FastAPI app and database are used; no summary route, service or queue is mocked.
The missing route must fail as an HTTP assertion, not an import/collection error.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import Meeting, MeetingSummary, SummaryRequestOutbox, SummaryTemplate, Transcript, User
from app.main import app


def _id() -> str:
    return str(uuid4())


def _headers(user: str, *, sales: bool = True) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user, f'{user}@example.test', 'Synthetic', sales)}"}


@pytest.fixture
async def summary_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str, str, str]]:
    """Persist a completed synthetic transcript and two different owners' templates."""
    url = os.environ.get("SAURI_QA_SUMMARY_READ_URL", f"sqlite+aiosqlite:///{tmp_path / 'requests.db'}")
    disposable_pg = "SAURI_QA_SUMMARY_READ_URL" in os.environ
    if disposable_pg:
        parsed = make_url(url)
        if parsed.drivername != "postgresql+asyncpg" or not re.fullmatch(
            r"sauri_t15_[a-zA-Z0-9_]+",
            parsed.database or "",
        ):
            raise ValueError("SAURI_QA_SUMMARY_READ_URL must target a dedicated sauri_t15_ PostgreSQL database")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        owner, other, meeting_id, transcript_id, own_template, foreign_template = (_id() for _ in range(6))
        now = datetime.now(UTC)
        async with factory() as session, session.begin():
            for user in (owner, other):
                session.add(
                    User(
                        id=user,
                        email=f"{user}@example.test",
                        name="Synthetic",
                        password_hash="test-only",
                        is_sales=True,
                        created_at=now,
                    )
                )
            session.add(
                Meeting(
                    id=meeting_id,
                    meet_link="https://meet.google.com/abc-defg-hij",
                    origin="manual",
                    calendar_invite_id=None,
                    scheduled_start_time=None,
                    process_state="completed",
                    failure_cause=None,
                    created_by=owner,
                    created_at=now,
                )
            )
            session.add(
                Transcript(
                    id=transcript_id,
                    meeting_id=meeting_id,
                    language="es-CO",
                    provider="synthetic",
                    supports_turns=False,
                    expires_at=None,
                    created_at=now,
                )
            )
            await session.flush()
            for user, template, instructions in (
                (owner, own_template, "  Exactly these opaque instructions.\n"),
                (other, foreign_template, "Private foreign instructions"),
            ):
                session.add(
                    SummaryTemplate(
                        id=template,
                        owner_user_id=user,
                        category_id=None,
                        name="Synthetic template",
                        version=1,
                        instructions=instructions,
                        created_at=now,
                        updated_at=now,
                    )
                )
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.delenv("AUTH_DISABLED", raising=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, factory, owner, other, meeting_id, own_template, foreign_template
    finally:
        try:
            if disposable_pg:
                async with engine.begin() as connection:
                    await connection.execute(text("DROP SCHEMA public CASCADE"))
                    await connection.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()


async def _settle(factory: async_sessionmaker[AsyncSession], event_id: str, status: str = "succeeded") -> None:
    """A pending/running request absorbs later posts; settle it to allow a new generation."""
    async with factory() as session, session.begin():
        row = await session.get(SummaryRequestOutbox, event_id)
        assert row is not None
        row.status = status


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
        assert (
            snapshot.meeting_id,
            snapshot.template_id,
            snapshot.template_version,
            snapshot.instructions_snapshot,
            snapshot.generation,
            snapshot.status,
        ) == (meeting, own, 1, "  Exactly these opaque instructions.\n", 1, "pending")
        assert snapshot.delivered_at is None
    async with factory() as session, session.begin():
        template = await session.get(SummaryTemplate, own)
        assert template is not None
        template.instructions = "Edited after acceptance"
        template.version = 2
    async with factory() as session, session.begin():
        accepted = await session.get(SummaryRequestOutbox, event_id)
        assert accepted is not None
        accepted.status = "succeeded"
    second = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    assert second.status_code == 202, second.text
    assert second.json()["generation"] == 2
    assert second.json()["event_id"] != event_id
    async with factory() as session:
        original = await session.get(SummaryRequestOutbox, event_id)
        updated = await session.get(SummaryRequestOutbox, second.json()["event_id"])
        assert original is not None and updated is not None
        assert (original.template_version, original.instructions_snapshot) == (
            1,
            "  Exactly these opaque instructions.\n",
        )
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
            own,
            1,
            "  Exactly these opaque instructions.\n",
        )
    await _settle(factory, response.json()["event_id"])
    # A later default change applies to the next request, never to this event.
    replacement = _id()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(
            SummaryTemplate(
                id=replacement,
                owner_user_id=owner,
                category_id=None,
                name="Replacement",
                version=1,
                instructions="New default instructions",
                created_at=now,
                updated_at=now,
            )
        )
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
        assert (snapshot.template_id, snapshot.instructions_snapshot) == (own, "  Exactly these opaque instructions.\n")
        assert (next_snapshot.template_id, next_snapshot.instructions_snapshot) == (
            replacement,
            "New default instructions",
        )
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
    non_sales_user = _id()
    async with factory() as session, session.begin():
        session.add(
            User(
                id=non_sales_user,
                email=f"{non_sales_user}@example.test",
                name="Synthetic",
                password_hash="test-only",
                is_sales=False,
                created_at=datetime.now(UTC),
            )
        )
    non_sales = await client.post(path, json={"template_id": foreign}, headers=_headers(non_sales_user, sales=False))
    assert non_sales.status_code == 403, non_sales.text
    async with factory() as session:
        assert (await session.scalars(select(SummaryRequestOutbox))).all() == []
        template = await session.get(SummaryTemplate, foreign)
        assert template is not None
        assert (template.owner_user_id, template.instructions) == (other, "Private foreign instructions")
        non_sales_record = await session.get(User, non_sales_user)
        assert non_sales_record is not None and non_sales_record.is_sales is False


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
        if len(accepted) == 1:
            await _settle(factory, accepted[0]["event_id"], "failed")
    async with factory() as session, session.begin():
        previous = await session.get(SummaryRequestOutbox, accepted[0]["event_id"])
        assert previous is not None
        previous.status = "succeeded"
    latest = await client.get(f"{path}/latest", headers=_headers(owner))
    assert latest.status_code == 200, latest.text
    assert {key: latest.json()[key] for key in ("event_id", "generation", "status")} == {
        "event_id": accepted[1]["event_id"],
        "generation": 2,
        "status": "pending",
    }
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


ApiFixture = tuple[AsyncClient, async_sessionmaker[AsyncSession], str, str, str, str, str]


async def _persist_successes(fixture: ApiFixture) -> list[dict[str, object]]:
    """Seed persisted worker outcomes, not a simulation of provider accuracy."""
    client, factory, owner, _, meeting, template, _ = fixture
    accepted: list[dict[str, object]] = []
    for generation, state in enumerate(("succeeded", "succeeded", "pending", "failed"), start=1):
        response = await client.post(
            f"/api/v1/meetings/{meeting}/summary-requests",
            json={"template_id": template},
            headers=_headers(owner),
        )
        assert response.status_code == 202, response.text
        body = response.json()
        accepted.append(body)
        async with factory() as session, session.begin():
            row = await session.get(SummaryRequestOutbox, body["event_id"])
            assert row is not None
            # An active request absorbs later posts: settle it now and reopen it afterwards.
            row.status = "failed" if state == "pending" else state
            if state == "succeeded":
                now = datetime.now(UTC)
                session.add(
                    MeetingSummary(
                        id=_id(),
                        event_id=row.event_id,
                        meeting_id=meeting,
                        transcript_id=row.transcript_id,
                        template_id=template,
                        template_version=row.template_version,
                        topic=f"Synthetic topic {generation}",
                        key_points_json=json.dumps([f"Point {generation}"]),
                        generation=generation,
                        created_at=now,
                        updated_at=now,
                    )
                )
    async with factory() as session, session.begin():
        reopened = await session.get(SummaryRequestOutbox, accepted[2]["event_id"])
        assert reopened is not None
        reopened.status = "pending"
    return accepted


@pytest.mark.asyncio
async def test_current_summary_selects_highest_success_not_later_pending_or_failed(summary_api: ApiFixture) -> None:
    client, _, owner, _, meeting, template, _ = summary_api
    await _persist_successes(summary_api)
    response = await client.get(f"/api/v1/meetings/{meeting}/summary", headers=_headers(owner))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["meeting_id"], body["template_id"], body["template_version"], body["generation"]) == (
        meeting,
        template,
        1,
        2,
    )
    assert body["topic"] == "Synthetic topic 2"
    assert body["key_points"] == ["Point 2"]
    assert body["template_name"] == "Synthetic template"
    assert body["summary_id"] and body["created_at"] and body["updated_at"]
    assert "instructions" not in response.text and "instructions_snapshot" not in body


@pytest.mark.asyncio
async def test_current_summary_requires_auth_sales_and_meeting_ownership(summary_api: ApiFixture) -> None:
    client, factory, owner, other, meeting, _, _ = summary_api
    await _persist_successes(summary_api)
    path = f"/api/v1/meetings/{meeting}/summary"
    anonymous = await client.get(path)
    assert anonymous.status_code == 401, anonymous.text
    async with factory() as session, session.begin():
        user = await session.get(User, other)
        assert user is not None
        user.is_sales = False
    denied = await client.get(path, headers=_headers(other, sales=False))
    assert denied.status_code == 403, denied.text
    foreign = await client.get(path, headers=_headers(other))
    assert foreign.status_code == 404, foreign.text
    missing = await client.get(f"/api/v1/meetings/{_id()}/summary", headers=_headers(owner))
    assert missing.status_code == 404, missing.text
    for response in (anonymous, denied, foreign, missing):
        assert "Synthetic topic" not in response.text and "Point 2" not in response.text


@pytest.mark.asyncio
async def test_no_successful_summary_returns_404_even_with_a_pending_request(summary_api: ApiFixture) -> None:
    client, _, owner, _, meeting, template, _ = summary_api
    # A successful owner read in the same test prevents a missing route from
    # satisfying the absence assertion vacuously.
    await _persist_successes(summary_api)
    present = await client.get(f"/api/v1/meetings/{meeting}/summary", headers=_headers(owner))
    assert present.status_code == 200, present.text
    _, factory, _, _, _, _, _ = summary_api
    other_meeting, other_transcript = _id(), _id()
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(
            Meeting(
                id=other_meeting,
                meet_link="https://meet.google.com/abc-defg-hij",
                origin="manual",
                process_state="completed",
                created_by=owner,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            Transcript(
                id=other_transcript,
                meeting_id=other_meeting,
                language="es",
                provider="synthetic",
                supports_turns=False,
                created_at=now,
            )
        )
    path = f"/api/v1/meetings/{other_meeting}"
    absent = await client.get(f"{path}/summary", headers=_headers(owner))
    assert absent.status_code == 404, absent.text
    accepted = await client.post(f"{path}/summary-requests", json={"template_id": template}, headers=_headers(owner))
    assert accepted.status_code == 202, accepted.text
    pending = await client.get(f"{path}/summary", headers=_headers(owner))
    assert pending.status_code == 404, pending.text
    assert "Synthetic topic" not in pending.text


@pytest.mark.asyncio
async def test_latest_summary_request_route_resolves_before_event_id(summary_api: ApiFixture) -> None:
    client, _, owner, _, meeting, _, _ = summary_api
    events = await _persist_successes(summary_api)
    response = await client.get(f"/api/v1/meetings/{meeting}/summary-requests/latest", headers=_headers(owner))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.pop("requested_at")  # accepted through the API, so the acceptance time is recorded
    assert body == {"event_id": events[-1]["event_id"], "generation": 4, "status": "failed"}


@pytest.mark.asyncio
async def test_status_routes_enforce_meeting_association_sales_and_owner(summary_api: ApiFixture) -> None:
    client, factory, owner, other, meeting, _, _ = summary_api
    events = await _persist_successes(summary_api)
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    event = events[0]["event_id"]
    own = await client.get(f"{path}/{event}", headers=_headers(owner))
    assert own.status_code == 200, own.text
    own_body = own.json()
    assert own_body.pop("requested_at")
    assert own_body == {"event_id": event, "generation": 1, "status": "succeeded"}
    for suffix in ("latest", str(event)):
        no_auth = await client.get(f"{path}/{suffix}")
        assert no_auth.status_code == 401, no_auth.text
        foreign = await client.get(f"{path}/{suffix}", headers=_headers(other))
        assert foreign.status_code == 404, foreign.text
        missing = await client.get(f"/api/v1/meetings/{_id()}/summary-requests/{suffix}", headers=_headers(owner))
        assert missing.status_code == 404, missing.text
    # Existing event in a DIFFERENT, real meeting owned by the same caller.
    second_meeting = _id()
    async with factory() as session, session.begin():
        session.add(
            Meeting(
                id=second_meeting,
                meet_link="https://meet.google.com/abc-defg-hij",
                origin="manual",
                process_state="completed",
                created_by=owner,
                created_at=datetime.now(UTC),
            )
        )
        user = await session.get(User, other)
        assert user is not None
        user.is_sales = False
    mismatch = await client.get(
        f"/api/v1/meetings/{second_meeting}/summary-requests/{event}",
        headers=_headers(owner),
    )
    assert mismatch.status_code == 404, mismatch.text
    for suffix in ("latest", str(event)):
        denied = await client.get(f"{path}/{suffix}", headers=_headers(other, sales=False))
        assert denied.status_code == 403, denied.text


async def test_no_personal_default_seeds_editable_starter_and_accepts(summary_api: ApiFixture) -> None:
    from app.copy.templates_es import DEFAULT_INSTRUCTIONS_V2, DEFAULT_NAME, DEFAULT_PROVENANCE_V2
    from app.templates.seed import seed_id

    client, factory, owner, other, meeting, _, _ = summary_api
    async with factory() as session, session.begin():
        user = await session.get(User, owner)
        assert user is not None
        user.default_summary_template_id = None
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    response = await client.post(path, json={}, headers=_headers(owner))
    assert response.status_code == 202, response.text
    template_id = seed_id(owner, "template")
    async with factory() as session:
        request = await session.get(SummaryRequestOutbox, response.json()["event_id"])
        assert request is not None and request.template_id == template_id
        assert request.instructions_snapshot == DEFAULT_INSTRUCTIONS_V2
    template = await client.get(f"/api/v1/templates/{template_id}", headers=_headers(owner))
    assert template.status_code == 200
    assert template.json()["name"] == DEFAULT_NAME and template.json()["is_default"]
    assert template.json()["provenance"] == DEFAULT_PROVENANCE_V2
    assert (await client.get(f"/api/v1/templates/{template_id}", headers=_headers(other))).status_code == 404
    updated = await client.patch(f"/api/v1/templates/{template_id}", json={"instructions": "Edited synthetic"},
                                 headers=_headers(owner))
    assert updated.status_code == 200
    await _settle(factory, response.json()["event_id"])
    later = await client.post(path, json={}, headers=_headers(owner))
    assert later.status_code == 202
    async with factory() as session:
        request = await session.get(SummaryRequestOutbox, later.json()["event_id"])
        assert request is not None and request.instructions_snapshot == "Edited synthetic"
        assert request.template_version == 2 and request.template_id == template_id


async def test_grounded_summary_is_exposed_as_draft(summary_api: ApiFixture) -> None:
    client, factory, owner, _, meeting, _, _ = summary_api
    events = await _persist_successes(summary_api)
    points = [{"text": "Synthetic point", "sources": [{"passage_id": "P0000", "start_ms": 0, "end_ms": 1000}]}]
    async with factory() as session, session.begin():
        summary = await session.scalar(select(MeetingSummary).where(MeetingSummary.event_id == events[1]["event_id"]))
        assert summary is not None
        summary.key_points_json = json.dumps(points)
    response = await client.get(f"/api/v1/meetings/{meeting}/summary", headers=_headers(owner))
    assert response.status_code == 200
    assert response.json()["key_points"] == points
    assert response.json()["review_state"] == "draft"
    assert response.json()["schema_version"] == 1 and response.json()["conclusion"] is None


async def test_v2_summary_is_exposed_with_blocks_and_conclusion(summary_api: ApiFixture) -> None:
    from app.summaries.passages import CanonicalSummary, encode_key_points

    client, factory, owner, _, meeting, _, _ = summary_api
    events = await _persist_successes(summary_api)
    canonical = CanonicalSummary.model_validate({
        "topic": "Synthetic topic paragraph", "conclusion": "Synthetic conclusion paragraph",
        "key_points": [{
            "title": "Synthetic block",
            "items": [{"text": "Synthetic item", "sub_items": ["Synthetic sub-item"]}],
            "sources": [{"passage_id": "P0000", "start_ms": 0, "end_ms": 1000}],
        }],
    })
    async with factory() as session, session.begin():
        summary = await session.scalar(select(MeetingSummary).where(MeetingSummary.event_id == events[1]["event_id"]))
        assert summary is not None
        summary.key_points_json = encode_key_points(canonical)
    body = (await client.get(f"/api/v1/meetings/{meeting}/summary", headers=_headers(owner))).json()
    assert body["schema_version"] == 2 and body["conclusion"] == "Synthetic conclusion paragraph"
    assert body["key_points"] == [block.model_dump() for block in canonical.key_points]


@pytest.mark.parametrize("edit", [{"name": "Edited title"}, {"instructions": "Edited instructions"},
                                  {"category_id": None}])
async def test_editing_starter_removes_owner_proposal_provenance(
    summary_api: ApiFixture, edit: dict[str, str | None]
) -> None:
    from app.copy.templates_es import DEFAULT_PROVENANCE_V2
    from app.templates.seed import ensure_default

    client, factory, owner, _, _, _, _ = summary_api
    async with factory() as session, session.begin():
        user = await session.get(User, owner)
        assert user is not None
        user.default_summary_template_id = None
        template_id = await ensure_default(session, owner)
    path = f"/api/v1/templates/{template_id}"
    assert (await client.get(path, headers=_headers(owner))).json()["provenance"] == DEFAULT_PROVENANCE_V2
    edited = await client.patch(path, json=edit, headers=_headers(owner))
    assert edited.status_code == 200
    assert edited.json()["provenance"] is None
    assert (await client.get(path, headers=_headers(owner))).json()["provenance"] is None


async def test_migrated_legacy_default_shows_owner_proposal_provenance_until_edited(
    summary_api: ApiFixture,
) -> None:
    from app.copy.templates_es import DEFAULT_INSTRUCTIONS_V2, DEFAULT_NAME, DEFAULT_PROVENANCE_V2

    client, factory, owner, _, _, _, _ = summary_api
    legacy_id = "legacy-default-id"
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(SummaryTemplate(
            id=legacy_id, owner_user_id=owner, category_id=None, name=DEFAULT_NAME,
            instructions=DEFAULT_INSTRUCTIONS_V2, version=2, created_at=now, updated_at=now,
        ))
        await session.flush()
        user = await session.get(User, owner)
        assert user is not None
        user.default_summary_template_id = legacy_id
    path = f"/api/v1/templates/{legacy_id}"
    shown = (await client.get(path, headers=_headers(owner))).json()
    assert shown["is_default"] and shown["provenance"] == DEFAULT_PROVENANCE_V2
    # Same text and name, but not the user's default: no owner-proposal note.
    copy = await client.post("/api/v1/templates", json={"name": DEFAULT_NAME, "instructions": DEFAULT_INSTRUCTIONS_V2},
                             headers=_headers(owner))
    assert copy.status_code == 201, copy.text
    assert copy.json()["provenance"] is None
    edited = await client.patch(path, json={"instructions": "Edited synthetic"}, headers=_headers(owner))
    assert edited.status_code == 200 and edited.json()["provenance"] is None


async def test_categorized_failure_is_returned_by_status_routes(summary_api: ApiFixture) -> None:
    client, factory, owner, _, meeting, template, _ = summary_api
    base = f"/api/v1/meetings/{meeting}/summary-requests"
    response = await client.post(base, json={"template_id": template}, headers=_headers(owner))
    event_id = response.json()["event_id"]
    async with factory() as session, session.begin():
        request = await session.get(SummaryRequestOutbox, event_id)
        assert request is not None
        request.status = "failed"
        request.failure_cause = "context_exceeded"
    for suffix in (event_id, "latest"):
        response = await client.get(f"{base}/{suffix}", headers=_headers(owner))
        assert response.status_code == 200
        assert response.json()["failure_cause"] == "context_exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("active", ["pending", "running"])
async def test_active_request_is_returned_instead_of_a_new_generation(summary_api: ApiFixture, active: str) -> None:
    client, factory, owner, _, meeting, own, _ = summary_api
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    first = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    assert first.status_code == 202, first.text
    if active == "running":
        async with factory() as session, session.begin():
            row = await session.get(SummaryRequestOutbox, first.json()["event_id"])
            assert row is not None
            row.status = "running"
    for body in ({"template_id": own}, {}):
        again = await client.post(path, json=body, headers=_headers(owner))
        assert again.status_code == 202, again.text
        assert again.json() == {**first.json(), "status": active}
    async with factory() as session:
        rows = (await session.scalars(select(SummaryRequestOutbox))).all()
        assert [(row.event_id, row.generation) for row in rows] == [(first.json()["event_id"], 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize("settled", ["succeeded", "failed"])
async def test_settled_request_allows_a_new_generation(summary_api: ApiFixture, settled: str) -> None:
    client, factory, owner, _, meeting, own, _ = summary_api
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    first = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    await _settle(factory, first.json()["event_id"], settled)
    second = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    assert second.status_code == 202, second.text
    assert second.json()["generation"] == 2 and second.json()["event_id"] != first.json()["event_id"]
    # The new request is now the active one: a third post converges on it.
    third = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    assert third.json()["event_id"] == second.json()["event_id"]


@pytest.mark.asyncio
async def test_auto_request_path_is_independent_of_the_active_manual_request(summary_api: ApiFixture) -> None:
    from app.summaries.service import accept_request

    client, factory, owner, _, meeting, own, _ = summary_api
    manual = await client.post(
        f"/api/v1/meetings/{meeting}/summary-requests", json={"template_id": own}, headers=_headers(owner),
    )
    assert manual.json()["generation"] == 1

    async def auto(revision: int) -> SummaryRequestOutbox:
        async with factory() as session, session.begin():
            return await accept_request(session, meeting, owner, own, processing_revision=revision)

    first_auto, repeated_auto = await auto(1), await auto(1)
    assert first_auto.generation == 2 and first_auto.event_id != manual.json()["event_id"]
    assert repeated_auto.event_id == first_auto.event_id  # deterministic identity is unchanged
    assert (await auto(2)).generation == 3  # a newer processing revision is always accepted


@pytest.mark.asyncio
async def test_status_exposes_request_and_start_times_and_omits_missing_ones(summary_api: ApiFixture) -> None:
    client, factory, owner, _, meeting, own, _ = summary_api
    path = f"/api/v1/meetings/{meeting}/summary-requests"
    before = datetime.now(UTC)
    accepted = await client.post(path, json={"template_id": own}, headers=_headers(owner))
    event_id = accepted.json()["event_id"]
    assert "started_at" not in accepted.json()
    requested = datetime.fromisoformat(accepted.json()["requested_at"])
    assert requested.utcoffset() == timedelta(0) and before <= requested <= datetime.now(UTC)
    assert accepted.json()["requested_at"].endswith("Z")
    started = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    async with factory() as session, session.begin():
        row = await session.get(SummaryRequestOutbox, event_id)
        assert row is not None
        row.status, row.started_at = "running", started
    for url in (f"{path}/latest", f"{path}/{event_id}"):
        body = (await client.get(url, headers=_headers(owner))).json()
        assert body["requested_at"] == accepted.json()["requested_at"]
        assert datetime.fromisoformat(body["started_at"]) == started and body["started_at"].endswith("Z")
    # A row created before the timestamps existed exposes neither field.
    async with factory() as session, session.begin():
        row = await session.get(SummaryRequestOutbox, event_id)
        assert row is not None
        row.status, row.requested_at, row.started_at = "succeeded", None, None
    legacy = (await client.get(f"{path}/latest", headers=_headers(owner))).json()
    assert legacy == {"event_id": event_id, "generation": 1, "status": "succeeded"}
