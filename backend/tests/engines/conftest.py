"""Fixtures for the engines API: a fake host service, and SQLite or disposable PostgreSQL."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.token import create_token
from app.engines import urls as engine_urls
from app.engines.host_client import HostClient, get_host_client
from app.infra.database import Base
from app.infra.models import User
from app.main import app

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "engine-common"))

MANAGEMENT_TOKEN = "synthetic-management-token-0123456789"
OWNER = "00000000-0000-4000-8000-00000000000a"
OTHER = "00000000-0000-4000-8000-00000000000b"


@dataclass
class FakeHost:
    """In-memory stand-in for host-engine; records every call it receives (never the real one)."""

    secrets: dict[str, dict[str, str]] = field(default_factory=dict)
    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    down: bool = False
    probe_answer: dict[str, Any] = field(default_factory=lambda: {"ok": True, "latency_ms": 42})
    probe_status: int = 200
    models_answer: dict[str, Any] = field(default_factory=lambda: {"models": [{"id": "model-a"}]})
    models_status: int = 200
    status_answer: dict[str, Any] = field(
        default_factory=lambda: {"engines": [{"id": "asr", "port": 8001, "state": "running"}], "secret_store": "file"}
    )
    secret_status: int | None = None


def build_fake_host(state: FakeHost) -> FastAPI:
    host = FastAPI(docs_url=None, openapi_url=None)

    def authorized(request: Request) -> bool:
        return request.headers.get("authorization") == f"Bearer {MANAGEMENT_TOKEN}"

    @host.middleware("http")
    async def gate(request: Request, call_next: Any) -> Response:
        body = await request.body()
        try:
            parsed: Any = httpx.Response(200, content=body).json() if body else None
        except ValueError:
            parsed = None
        state.calls.append((request.method, request.url.path, parsed))
        if state.down:
            return JSONResponse({"error": {"code": "unavailable"}}, status_code=503)
        if not authorized(request):
            return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
        return await call_next(request)

    @host.put("/v1/secrets/{ref:path}")
    async def put_secret(ref: str, request: Request) -> Response:
        if state.secret_status is not None:
            return JSONResponse({"error": {"code": "secret_unavailable"}}, status_code=state.secret_status)
        body = await request.json()
        state.secrets[ref] = {"key": body["key"], "origin": body["origin"]}
        key = body["key"]
        return JSONResponse({"key_hint": key[-4:] if len(key) >= 12 else None})

    @host.delete("/v1/secrets/{ref:path}")
    async def delete_secret(ref: str) -> Response:
        state.secrets.pop(ref, None)
        return Response(status_code=204)

    @host.post("/v1/providers/probe")
    async def probe() -> Response:
        return JSONResponse(state.probe_answer, status_code=state.probe_status)

    @host.post("/v1/providers/models")
    async def models() -> Response:
        return JSONResponse(state.models_answer, status_code=state.models_status)

    @host.get("/v1/engines/status")
    async def engines_status() -> Response:
        return JSONResponse(state.status_answer)

    return host


@pytest.fixture
def fake_host() -> FakeHost:
    return FakeHost()


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test resolves real names: every host answers with a public documentation address."""

    async def resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(engine_urls, "resolve_host", resolve)


def auth_headers(user_id: str = OWNER) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user_id, f'{user_id}@sauri.local', 'Test', True)}"}


async def _postgres_database() -> tuple[str, Any]:
    raw = os.getenv("SAURI_QA_POSTGRES_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL (SAURI_QA_POSTGRES_URL)")
    url = make_url(raw)
    database = f"sauri_qa_engines_{uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    await admin.execute(f'CREATE DATABASE "{database}"')
    return url.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False), (
        admin,
        database,
    )


@pytest.fixture(params=["sqlite", "postgres"])
async def engines_db(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    cleanup: Any = None
    if request.param == "sqlite":
        url = f"sqlite+aiosqlite:///{tmp_path / 'engines.db'}"
    else:
        url, cleanup = await _postgres_database()
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        for user_id in (OWNER, OTHER):
            session.add(
                User(
                    id=user_id,
                    email=f"{user_id}@sauri.local",
                    name="Synthetic user",
                    password_hash="not-used-by-jwt",
                    is_sales=True,
                    created_at=datetime.now(UTC),
                )
            )
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("APP_ENV", "test")
    yield factory
    await engine.dispose()
    if cleanup is not None:
        admin, database = cleanup
        await admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", database)
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()


@pytest.fixture
async def api(
    engines_db: async_sessionmaker[AsyncSession],
    fake_host: FakeHost,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    token_file = tmp_path / "management_token"
    token_file.write_text(MANAGEMENT_TOKEN + "\n")
    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(token_file))
    host_client = HostClient("http://host.test", transport=ASGITransport(app=build_fake_host(fake_host)))
    app.dependency_overrides[get_host_client] = lambda: host_client
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_host_client, None)
