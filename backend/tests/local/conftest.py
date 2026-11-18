"""Disposable local installation, with real persisted ownership and no external services."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from app.infra.database import Base, create_session_factory
from app.local.bootstrap import ensure_local_user
from app.main import create_app

TOKEN = "ab" * 32
ORIGIN = "chrome-extension://" + "b" * 32


@pytest.fixture(name="local_app")
async def local_application(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    token_file = tmp_path / "local_token"
    token_file.write_text(TOKEN)
    monkeypatch.setenv("SAURI_AUTH_MODE", "local")
    monkeypatch.setenv("SAURI_LOCAL_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("SAURI_EXTENSION_ORIGINS", ORIGIN)
    monkeypatch.setenv("APP_ENV", "test")
    # A test bypass must never take precedence over the persisted local owner.
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'local.db'}")
    for key in ("DATABASE_PASSWORD_FILE", "JWT_SECRET", "JWT_SECRET_FILE"):
        monkeypatch.delenv(key, raising=False)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'local.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as session, session.begin():
        user = await ensure_local_user(session, "Local Tester")
    await engine.dispose()
    monkeypatch.setenv("SAURI_LOCAL_USER_ID", user.id)
    return create_app()
