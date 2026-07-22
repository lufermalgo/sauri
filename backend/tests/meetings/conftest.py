"""Shared fixtures for testing the meetings API contract (chrome-side-panel).

Uses a temporary SQLite file (not ':memory:') because the router creates a
new AsyncEngine per request (`create_engine()` reads `DATABASE_URL` on every
call); a ':memory:' engine wouldn't persist across separate requests.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.infra.database import Base


@pytest.fixture
async def api_db_url(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[str, None]:
    """Creates a temporary SQLite database, applies the schema, and points DATABASE_URL to it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite+aiosqlite:///{path}"

    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")

    yield url

    os.remove(path)


@pytest.fixture
async def api_client(api_db_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client against the real FastAPI app (no server)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
