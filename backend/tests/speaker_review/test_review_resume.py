"""Persistence and owner-scoped retrieval for pending speaker reviews (T-3 RED)."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import Meeting, SpeakerReview, SpeakerReviewItem


@pytest.fixture
async def api_db_url(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[str, None]:
    """Create an isolated SQLite database for the authenticated API contract."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    yield url
    os.remove(path)


@pytest.fixture
async def api_client(api_db_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Create an in-process client using the isolated database fixture."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


OWNER_ID = "speaker-review-owner"
OTHER_OWNER_ID = "speaker-review-other-owner"


def _auth_header(owner_id: str = OWNER_ID) -> dict[str, str]:
    token = create_token(owner_id, f"{owner_id}@sauri.local", "Synthetic Reviewer", True)
    return {"Authorization": f"Bearer {token}"}


async def _persist_pending_review(api_db_url: str) -> tuple[str, str]:
    """Persist synthetic meeting and review rows before the API read."""
    engine = create_async_engine(api_db_url, echo=False)
    meeting_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
                created_by=OWNER_ID,
                created_at=now,
            )
        )
        session.add(
            SpeakerReview(
                id=review_id,
                meeting_id=meeting_id,
                processing_revision=1,
                status="pending",
                created_at=now,
            )
        )
        session.add_all(
            [
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=review_id,
                    speaker_key="speaker-one",
                    current_label="Speaker 1",
                    disposition="named",
                    chosen_label="Synthetic Alice",
                    attribution_state="uncertain",
                    version=2,
                ),
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=review_id,
                    speaker_key="speaker-two",
                    current_label="Speaker 2",
                    disposition=None,
                    chosen_label=None,
                    attribution_state="uncertain",
                    version=1,
                ),
            ]
        )
    await engine.dispose()
    return meeting_id, review_id


async def test_pending_review_reload_returns_only_undisposed_items(api_client: AsyncClient, api_db_url: str) -> None:
    """Leaving and reloading preserves the saved item and resumes the outstanding one."""
    meeting_id, review_id = await _persist_pending_review(api_db_url)

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review",
        headers=_auth_header(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_id"] == review_id
    assert body["revision_id"] == 1
    assert body["status"] == "pending"
    assert body["remaining_speaker_ids"] == ["speaker-two"]
    assert body["labels_by_speaker_id"] == {"speaker-one": "Synthetic Alice", "speaker-two": "Speaker 2"}
    assert body["items"] == [
        {
            "speaker_id": "speaker-two",
            "current_label": "Speaker 2",
            "attribution_state": "uncertain",
            "disposition": None,
            "excerpt_ref": None,
            "expected_version": 1,
        }
    ]

    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        saved_item = await session.scalar(
            select(SpeakerReviewItem).where(
                SpeakerReviewItem.review_id == review_id,
                SpeakerReviewItem.speaker_key == "speaker-one",
            )
        )
    await engine.dispose()
    assert saved_item is not None
    assert saved_item.disposition == "named"
    assert saved_item.chosen_label == "Synthetic Alice"


async def test_completed_review_reload_does_not_request_review_again(api_client: AsyncClient, api_db_url: str) -> None:
    """Once every item is disposed, reload returns completion and no remaining items."""
    meeting_id, review_id = await _persist_pending_review(api_db_url)
    engine = create_async_engine(api_db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session, session.begin():
        from app.meetings.speaker_review_service import SpeakerReviewService

        result = await SpeakerReviewService(session).record_disposition(
            OWNER_ID,
            meeting_id,
            "1",
            "speaker-two",
            {
                "disposition": "confirmed",
                "expected_version": 1,
                "idempotency_key": "resume-completion-key",
            },
            1,
        )
        assert result["outcome"] == "apply"
        assert result["result"]["status"] == "complete"
    await engine.dispose()

    response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review",
        headers=_auth_header(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_id"] == review_id
    assert body["status"] == "complete"
    assert body["remaining_speaker_ids"] == []
    assert body["items"] == []


async def test_review_reload_is_scoped_to_meeting_owner(api_client: AsyncClient, api_db_url: str) -> None:
    """A different authenticated owner cannot retrieve persisted review data."""
    meeting_id, _ = await _persist_pending_review(api_db_url)

    owner_response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review",
        headers=_auth_header(),
    )
    assert owner_response.status_code == 200

    other_owner_response = await api_client.get(
        f"/api/v1/meetings/{meeting_id}/speaker-review",
        headers=_auth_header(OTHER_OWNER_ID),
    )

    assert other_owner_response.status_code == 404
