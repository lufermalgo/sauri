"""Additive contract: `title` field (nullable) in GET /api/v1/meetings/
(chrome-side-panel, Tarea 13.5). Validates: Requirements 4.3, 4.4
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Meeting

USER_ID = "user-titulo-test"


def _auth_header() -> dict[str, str]:
    token = create_token(USER_ID, "titulo@sauri.local", "Titulo Test", True)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_listing_includes_null_title(api_client: AsyncClient, api_db_url: str):
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
                created_by=USER_ID,
                created_at=now,
            )
        )
    await engine.dispose()

    resp = await api_client.get("/api/v1/meetings/", headers=_auth_header())
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert "title" in item
    assert item["title"] is None
    # Existing fields are preserved (additive change)
    assert item["meeting_id"] == meeting_id
    assert item["process_state"] == "completed"
