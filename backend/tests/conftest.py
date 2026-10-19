"""Pytest configuration and shared fixtures for the sauri backend test suite."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from hypothesis import settings as hypothesis_settings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infra.database import Base
from app.infra.models import Meeting

# ---------------------------------------------------------------------------
# Hypothesis profile: min 100 examples for property-based tests
# ---------------------------------------------------------------------------

hypothesis_settings.register_profile("sauri", max_examples=100)
hypothesis_settings.load_profile("sauri")


# ---------------------------------------------------------------------------
# Database fixtures — SQLite async in-memory for speed
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
# Domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def meeting_recording() -> Meeting:
    """A Meeting fixture in state 'recording' ready for transcription."""
    return Meeting(
        id=str(uuid.uuid4()),
        meet_link="https://meet.google.com/abc-defg-hij",
        origin="link",
        calendar_invite_id=None,
        scheduled_start_time=None,
        process_state="recording",
        failure_cause=None,
        created_by="test-user",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_queue() -> AsyncMock:
    """A mock JobQueue for testing without RabbitMQ."""
    queue = AsyncMock()
    queue.publish = AsyncMock()
    queue.subscribe = AsyncMock()
    queue.connect = AsyncMock()
    queue.disconnect = AsyncMock()
    return queue
