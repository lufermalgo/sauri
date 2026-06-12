"""Pytest configuration and shared fixtures for the sauri backend test suite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
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
from app.infra.models import Reunion

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
def reunion_grabando() -> Reunion:
    """A Reunion fixture in state 'grabando' ready for transcription."""
    return Reunion(
        id=str(uuid.uuid4()),
        enlace_meet="https://meet.google.com/abc-defg-hij",
        origen="enlace",
        id_invitacion_calendario=None,
        hora_inicio_programada=None,
        estado_proceso="grabando",
        causa_fallo=None,
        creada_por="test-user",
        creada_en=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_cola() -> AsyncMock:
    """A mock ColaDeTrabajos for testing without RabbitMQ."""
    cola = AsyncMock()
    cola.publicar = AsyncMock()
    cola.suscribir = AsyncMock()
    cola.conectar = AsyncMock()
    cola.desconectar = AsyncMock()
    return cola
