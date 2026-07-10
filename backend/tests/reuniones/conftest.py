"""Fixtures compartidas para pruebas de contrato de la API de reuniones (chrome-side-panel).

Usa un archivo SQLite temporal (no ':memory:') porque el router crea un
AsyncEngine nuevo por solicitud (`create_engine()` lee `DATABASE_URL` en
cada llamada); un ':memory:' no persistiría entre solicitudes distintas.
"""

from __future__ import annotations

import os
import tempfile
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.infra.database import Base


@pytest.fixture
async def api_db_url(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[str, None]:
    """Crea un SQLite temporal, aplica el esquema y apunta DATABASE_URL a él."""
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
    """Cliente HTTP asíncrono contra la app FastAPI real (sin servidor)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
