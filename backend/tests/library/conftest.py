"""Shared fixtures for testing the recording library (spec: recording-library-metadata).

Test infrastructure only: no production code. Database fixtures follow the
existing backend test pattern (SQLite aiosqlite in-memory + Base.metadata
create_all, see backend/tests/conftest.py). Data produced by the builders is
synthetic only.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth.token import create_token
from app.infra.database import Base
from app.infra.models import Meeting, SessionRecording, SpeechTurn, Transcript

# ---------------------------------------------------------------------------
# Database fixtures — SQLite async in-memory for speed (existing pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an in-memory SQLite async engine for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session_factory(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the test engine."""
    return async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional session that rolls back after each test."""
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------


def seed_meeting_recording(
    session: AsyncSession,
    *,
    title: str = "Reunión comercial de prueba",  # spanish-sample-data
    created_by: str = "sales-user-00000001",
    finished_at: datetime | None = None,
    video_ref: str | None = None,
    with_transcript: bool = False,
    transcript_turns: list[dict[str, Any]] | None = None,
) -> Meeting:
    """Build a synthetic Meeting + SessionRecording (+ optional Transcript/SpeechTurns).

    Nothing is committed here; callers control the transaction.
    """
    meeting = Meeting(
        id=str(uuid.uuid4()),
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="completed",
        failure_cause=None,
        title=title,
        created_by=created_by,
        created_at=datetime.now(UTC),
    )
    recording = SessionRecording(
        id=str(uuid.uuid4()),
        meeting_id=meeting.id,
        idempotency_key=str(uuid.uuid4()),
        capture_origin="chrome_extension",
        audio_ref=f"s3://sauri-recordings/{meeting.id}/audio.opus",
        video_ref=video_ref,
        duration_seconds=600,
        interrupted=False,
        expires_at=None,
        finished_at=finished_at or datetime.now(UTC),
    )
    session.add_all([meeting, recording])

    if with_transcript:
        transcript = Transcript(
            id=str(uuid.uuid4()),
            meeting_id=meeting.id,
            language="es-CO",
            provider="local",
            supports_turns=True,
            expires_at=None,
            created_at=datetime.now(UTC),
        )
        session.add(transcript)
        turns = transcript_turns or [
            {
                "text": "Buenos días, iniciemos la reunión.",  # spanish-sample-data
                "start_ms": 0,
                "end_ms": 4000,
                "sequence": 0,
            },
            {
                "text": "Gracias, revisemos el punto uno de la agenda.",  # spanish-sample-data
                "start_ms": 4000,
                "end_ms": 12000,
                "sequence": 1,
            },
        ]
        for turn in turns:
            session.add(
                SpeechTurn(
                    id=str(uuid.uuid4()),
                    transcript_id=transcript.id,
                    text=str(turn["text"]),
                    start_ms=int(turn["start_ms"]),
                    end_ms=int(turn["end_ms"]),
                    sequence=int(turn["sequence"]),
                )
            )
    return meeting


# ---------------------------------------------------------------------------
# Auth helpers — mint valid JWTs with the existing auth test utility
# ---------------------------------------------------------------------------


def sales_token(
    user_id: str = "sales-user-00000001",
    email: str = "sales@sauri.local",
    name: str = "Sales User",
) -> str:
    """Mint a valid JWT for an authorized sales user."""
    return create_token(user_id, email, name, True)


def non_sales_token(
    user_id: str = "non-sales-user-00000001",
    email: str = "non-sales@sauri.local",
    name: str = "Non Sales User",
) -> str:
    """Mint a valid JWT for an unauthorized non-sales user."""
    return create_token(user_id, email, name, False)
