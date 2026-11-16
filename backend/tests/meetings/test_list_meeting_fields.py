"""Additive contract: list extras (duration, speakers, topic, thumbnail) in GET /api/v1/meetings/."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.infra.models import Diarization, Meeting, MeetingSummary, SessionRecording

OWNER_ID = "list-fields-owner"
OTHER_ID = "list-fields-other"
NEW_FIELDS = ("duration_seconds", "speaker_count", "summary_topic", "thumbnail_url", "media_kind")


def _auth_header(user_id: str = OWNER_ID) -> dict[str, str]:
    token = create_token(user_id, f"{user_id}@sauri.local", "List Fields Test", True)
    return {"Authorization": f"Bearer {token}"}


def _meeting(owner_id: str, created_at: datetime) -> Meeting:
    return Meeting(
        id=str(uuid.uuid4()),
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="completed",
        failure_cause=None,
        created_by=owner_id,
        created_at=created_at,
    )


def _recording(meeting_id: str, duration: int, now: datetime) -> SessionRecording:
    return SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        idempotency_key=str(uuid.uuid4()),
        capture_origin="chrome_extension",
        audio_ref="private/test/audio.webm",
        video_ref=None,
        duration_seconds=duration,
        interrupted=False,
        expires_at=None,
        finished_at=now,
    )


def _diarization(
    meeting_id: str, state: str, speakers: int, revision: int, now: datetime
) -> Diarization:
    return Diarization(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        transcript_id=str(uuid.uuid4()),
        provider="local",
        speaker_count=speakers,
        processing_revision=revision,
        diarization_state=state,
        failure_cause=None,
        created_at=now,
        updated_at=now,
    )


def _summary(meeting_id: str, topic: str, generation: int, now: datetime) -> MeetingSummary:
    return MeetingSummary(
        id=str(uuid.uuid4()),
        event_id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        transcript_id=str(uuid.uuid4()),
        template_id=str(uuid.uuid4()),
        template_version=1,
        topic=topic,
        key_points_json='["Synthetic point"]',
        generation=generation,
        created_at=now,
        updated_at=now,
    )


async def _seed(api_db_url: str, rows: list[Any]) -> None:
    engine = create_async_engine(api_db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all(rows)
    await engine.dispose()


@contextmanager
def _count_statements() -> Iterator[list[str]]:
    statements: list[str] = []

    def _before(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", _before)


@pytest.mark.asyncio
async def test_listing_returns_recording_diarization_and_summary_values(
    api_client: AsyncClient, api_db_url: str
) -> None:
    now = datetime.now(UTC)
    meeting = _meeting(OWNER_ID, now)
    await _seed(
        api_db_url,
        [
            meeting,
            _recording(meeting.id, 1860, now),
            # Older completed revision, a newer failed one and the latest completed one.
            _diarization(meeting.id, "completed", 2, 1, now),
            _diarization(meeting.id, "failed", 9, 3, now),
            _diarization(meeting.id, "completed", 4, 2, now),
            _summary(meeting.id, "Synthetic topic 1", 1, now),
            _summary(meeting.id, "Synthetic topic 2", 2, now),
        ],
    )

    resp = await api_client.get("/api/v1/meetings/", headers=_auth_header())

    assert resp.status_code == 200
    (item,) = resp.json()
    assert item["meeting_id"] == meeting.id
    assert item["duration_seconds"] == 1860
    assert item["speaker_count"] == 4
    assert item["summary_topic"] == "Synthetic topic 2"
    # Existing fields keep their position; the new ones are appended.
    assert list(item)[-len(NEW_FIELDS):] == list(NEW_FIELDS)
    assert list(item)[:7] == [
        "meeting_id", "meet_link", "origin", "process_state",
        "failure_cause", "created_at", "title",
    ]


@pytest.mark.asyncio
async def test_listing_returns_nulls_without_recording_diarization_or_summary(
    api_client: AsyncClient, api_db_url: str
) -> None:
    now = datetime.now(UTC)
    meeting = _meeting(OWNER_ID, now)
    unfinished = _meeting(OWNER_ID, now)
    await _seed(
        api_db_url,
        [meeting, unfinished, _diarization(unfinished.id, "in_progress", 3, 1, now)],
    )

    resp = await api_client.get("/api/v1/meetings/", headers=_auth_header())

    assert resp.status_code == 200
    body = resp.json()
    assert {item["meeting_id"] for item in body} == {meeting.id, unfinished.id}
    for item in body:
        for field in NEW_FIELDS:
            assert field in item
            assert item[field] is None


@pytest.mark.asyncio
async def test_listing_never_exposes_another_users_data(
    api_client: AsyncClient, api_db_url: str
) -> None:
    now = datetime.now(UTC)
    mine = _meeting(OWNER_ID, now)
    theirs = _meeting(OTHER_ID, now)
    await _seed(
        api_db_url,
        [
            mine,
            theirs,
            _recording(theirs.id, 999, now),
            _diarization(theirs.id, "completed", 7, 1, now),
            _summary(theirs.id, "Other user's secret topic", 1, now),
        ],
    )

    resp = await api_client.get("/api/v1/meetings/", headers=_auth_header())

    assert resp.status_code == 200
    body = resp.json()
    assert [item["meeting_id"] for item in body] == [mine.id]
    assert all(item[field] is None for item in body for field in NEW_FIELDS)
    assert "secret" not in resp.text


@pytest.mark.asyncio
async def test_listing_statement_count_does_not_grow_with_meetings(
    api_client: AsyncClient, api_db_url: str
) -> None:
    now = datetime.now(UTC)

    async def _add_meetings(count: int) -> None:
        rows: list[Any] = []
        for _ in range(count):
            meeting = _meeting(OWNER_ID, now)
            rows += [
                meeting,
                _recording(meeting.id, 60, now),
                _diarization(meeting.id, "completed", 2, 1, now),
                _summary(meeting.id, "Synthetic topic", 1, now),
            ]
        await _seed(api_db_url, rows)

    await _add_meetings(1)
    with _count_statements() as few:
        resp = await api_client.get("/api/v1/meetings/", headers=_auth_header())
    assert len(resp.json()) == 1

    await _add_meetings(9)
    with _count_statements() as many:
        resp = await api_client.get("/api/v1/meetings/", headers=_auth_header())
    assert len(resp.json()) == 10
    assert all(item["summary_topic"] == "Synthetic topic" for item in resp.json())

    assert len(many) == len(few)
    # Meetings query plus at most three batched queries for the new fields, plus the account lookup
    # that authentication performs on every request.
    assert len(many) <= 5
