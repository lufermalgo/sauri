"""Authenticated excerpt route, review scope, bounded audio response (T-16/#248).

Synthetic rows and PCM only; real decoder limits are covered by test_speaker_excerpt_limits.
"""

from __future__ import annotations

import io
import uuid
import wave
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import Meeting, SpeakerReview, SpeakerReviewItem
from app.meetings import router as meetings_router

OWNER = "excerpt-owner"
OTHER = "excerpt-other"
MEETING = "a7d46e97-1352-44e4-9a82-2e9788fcdcb6"
SPEAKER = "f51e9f40-756b-4d92-8bd0-22843e8563c9"
BASE = f"/api/v1/meetings/{MEETING}/speaker-review/revisions"
PRIVATE_KEY = "private-bucket/private-audio.webm"


def auth(user: str = OWNER, *, sales: bool = True) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user, f'{user}@sauri.local', 'Synthetic', sales)}"}


class FakeExcerptService:
    def __init__(self) -> None:
        self.played: list[tuple[str, int, str]] = []
        self.audio = b"\x00\x00" * 1600
        self.error: Exception | None = None

    async def play(self, *, recording_id: str, revision_id: int, review_item: SpeakerReviewItem) -> bytes:
        self.played.append((recording_id, revision_id, review_item.speaker_key))
        assert review_item.excerpt_ref == "opaque-test-ref"
        assert review_item.review.meeting_id == recording_id
        if self.error is not None:
            raise self.error
        return self.audio


@pytest.fixture
async def excerpt_api(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    url = f"sqlite+aiosqlite:///{tmp_path / 'speaker-excerpt.db'}"
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(
            Meeting(
                id=MEETING,
                meet_link="https://meet.google.com/abc-defg-hij",
                origin="link",
                calendar_invite_id=None,
                scheduled_start_time=None,
                process_state="completed",
                failure_cause=None,
                created_by=OWNER,
                created_at=datetime.now(UTC),
            )
        )
        for revision in (1, 2):
            review_id = str(uuid.uuid4())
            session.add(
                SpeakerReview(
                    id=review_id,
                    meeting_id=MEETING,
                    processing_revision=revision,
                    status="pending",
                    created_at=datetime.now(UTC),
                )
            )
            session.add(
                SpeakerReviewItem(
                    id=str(uuid.uuid4()),
                    review_id=review_id,
                    speaker_key=SPEAKER,
                    current_label="Speaker 1",
                    excerpt_ref="opaque-test-ref",
                    disposition=None,
                    chosen_label=None,
                    attribution_state="uncertain",
                    version=1,
                )
            )
    await engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    service = FakeExcerptService()
    monkeypatch.setattr(meetings_router, "_get_object_store", lambda: object())
    monkeypatch.setattr(meetings_router, "create_speaker_excerpt_service", lambda _store: service)
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, service, url


def test_excerpt_contract_is_registered_in_openapi() -> None:
    from app.main import app

    path = (
        "/api/v1/meetings/{meeting_id}/speaker-review/revisions/"
        "{revision_id}/speakers/{speaker_id}/excerpt"
    )
    assert "get" in app.openapi()["paths"][path]


@pytest.mark.asyncio
async def test_current_owner_receives_only_bounded_wav(excerpt_api: Any) -> None:
    client, service, _url = excerpt_api
    response = await client.get(f"{BASE}/2/speakers/{SPEAKER}/excerpt", headers=auth())
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.readframes(wav.getnframes()) == service.audio
    assert service.played == [(MEETING, 2, SPEAKER)]
    assert PRIVATE_KEY.encode() not in response.content


@pytest.mark.asyncio
async def test_auth_owner_revision_speaker_and_reference_fail_closed(excerpt_api: Any) -> None:
    client, service, url = excerpt_api
    path = f"{BASE}/2/speakers/{SPEAKER}/excerpt"
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=auth(OTHER))).status_code == 404
    assert (await client.get(path, headers=auth(sales=False))).status_code == 403
    assert (await client.get(f"{BASE}/1/speakers/{SPEAKER}/excerpt", headers=auth())).status_code == 409
    assert (await client.get(f"{BASE}/2/speakers/unknown/excerpt", headers=auth())).status_code == 404
    assert service.played == []
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        from sqlalchemy import select

        item = await session.scalar(
            select(SpeakerReviewItem)
            .join(SpeakerReview)
            .where(SpeakerReview.meeting_id == MEETING, SpeakerReview.processing_revision == 2)
        )
        assert item is not None
        item.excerpt_ref = None
    await engine.dispose()
    assert (await client.get(path, headers=auth())).status_code == 404
    assert service.played == []


@pytest.mark.asyncio
async def test_invalid_or_oversized_audio_and_reference_do_not_leak(excerpt_api: Any) -> None:
    client, service, _url = excerpt_api
    path = f"{BASE}/2/speakers/{SPEAKER}/excerpt"
    for bad_audio in (b"", b"odd", b"\x00\x00" * (10 * 16000 + 1)):
        service.audio = bad_audio
        response = await client.get(path, headers=auth())
        assert response.status_code == 503
        assert response.json() == {"detail": "Speaker excerpt unavailable"}
    service.error = LookupError(PRIVATE_KEY)
    response = await client.get(path, headers=auth())
    assert response.status_code == 404
    assert PRIVATE_KEY not in response.text
    service.error = ValueError(PRIVATE_KEY)
    response = await client.get(path, headers=auth())
    assert response.status_code == 503
    assert PRIVATE_KEY not in response.text
