"""Properties 6 and 7, local identity and cookie bootstrap with the actual API."""

import re
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_current_user
from app.auth.router import _startup_checks
from app.engines.host_client import HostClient, get_host_client
from app.infra.object_store import ObjectStore
from app.infra.queue import JobQueue
from tests.local.conftest import ORIGIN, TOKEN
from tests.local.routes import api_routes


@pytest.mark.parametrize("credential", ["cookie", "extension"])
async def test_every_route_accepts_real_local_user(
    local_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    credential: str,
) -> None:
    # Isolate I/O boundaries only. Authentication, authorization, routes and the DB remain real.
    host = AsyncMock(spec=HostClient)
    host.local.return_value = (503, {"error": {"code": "host_unavailable"}})
    host.engines_status.return_value = {}
    local_app.dependency_overrides[get_host_client] = lambda: host
    store, queue = AsyncMock(spec=ObjectStore), AsyncMock(spec=JobQueue)
    for module in ("ingestion", "meetings", "regeneration", "summaries"):
        monkeypatch.setattr(f"app.{module}.router._get_object_store", lambda: store, raising=False)
        monkeypatch.setattr(f"app.{module}.router._get_queue", lambda: queue, raising=False)
    headers = (
        {"Cookie": f"sauri_local={TOKEN}", "Sec-Fetch-Site": "same-origin"}
        if credential == "cookie"
        else {"Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
    )
    assert get_current_user not in local_app.dependency_overrides
    tested = 0
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        for route in api_routes(local_app.routes):
            path = re.sub(r"\{[^}]+\}", "missing-id", route.path)
            for method in route.methods:
                request_headers = headers | ({"Origin": ORIGIN} if path == "/api/v1/local/pair" else {})
                response = await client.request(method, path, headers=request_headers)
                # U2's media URLs have their own signature, independent of the local session.
                allowed = {200, 201, 202, 204, 400, 404, 409, 422, 503}
                if route.path.startswith("/api/v1/media/"):
                    allowed.add(403)
                assert response.status_code in allowed, (
                    method,
                    path,
                    response.text,
                )
                tested += 1
    assert tested >= 54


async def test_status_bootstraps_cookie_and_me_uses_database(local_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        response = await client.get("/api/v1/local/status", headers={"Sec-Fetch-Site": "same-origin"})
        assert response.status_code == 200
        assert response.json() == {"ready": True, "processing": 0, "version": local_app.version, "mode": "local"}
        assert response.headers["cache-control"] == "no-store"
        cookie = response.headers["set-cookie"]
        assert all(part in cookie for part in ("sauri_local=", "HttpOnly", "SameSite=Strict", "Path=/"))
        me = await client.get("/api/v1/local/me", headers={"Sec-Fetch-Site": "same-origin"})
        assert me.status_code == 200
        assert me.json()["email"] == "local@sauri.local"
        assert me.json()["name"] == "Local Tester"
        assert me.json()["is_sales"] is True
        assert "password_hash" not in me.json()
        assert (await client.get("/api/v1/meetings/", headers={"Sec-Fetch-Site": "same-origin"})).status_code == 200


async def test_pair_only_trusted_extension_no_cookie_leak(local_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        for origin in (
            None,
            "null",
            "http://localhost:8000",
            "http://localhost:9999",
            "chrome-extension://" + "c" * 32,
        ):
            response = await client.post("/api/v1/local/pair", headers={"Origin": origin} if origin else {})
            assert response.status_code == 403
            assert TOKEN not in response.text
            assert "set-cookie" not in response.headers
        response = await client.post("/api/v1/local/pair", headers={"Origin": ORIGIN})
        assert response.json() == {"token": TOKEN}
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["access-control-allow-origin"] == ORIGIN
        status = await client.get(
            "/api/v1/local/status", headers={"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"}
        )
        assert status.status_code == 200
        assert "set-cookie" not in status.headers


@pytest.mark.parametrize("user_id", ["", "missing-user"])
async def test_missing_local_owner_fails_closed(
    local_app: FastAPI, monkeypatch: pytest.MonkeyPatch, user_id: str
) -> None:
    monkeypatch.setenv("SAURI_LOCAL_USER_ID", user_id)
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        response = await client.get(
            "/api/v1/local/me", headers={"Cookie": f"sauri_local={TOKEN}", "Sec-Fetch-Site": "same-origin"}
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "local_user_missing"}


async def test_local_startup_without_jwt_secret(local_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    async with _startup_checks(local_app):
        pass


async def test_password_mode_has_no_local_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setenv("SAURI_AUTH_MODE", "password")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        for method, path in (("GET", "status"), ("GET", "me"), ("POST", "pair")):
            assert (await client.request(method, f"/api/v1/local/{path}")).status_code == 404


async def test_routes_cover_the_registered_api_schema(local_app: FastAPI) -> None:
    enumerated = {(route.path, method.lower()) for route in api_routes(local_app.routes) for method in route.methods}
    documented = {
        (path, method)
        for path, methods in local_app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in methods
    }
    assert enumerated == documented


async def test_local_role_and_claims_come_from_the_persisted_row(
    local_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from sqlalchemy import update

    from app.infra.database import create_engine, create_session_factory
    from app.infra.models import User

    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session, session.begin():
            await session.execute(
                update(User)
                .where(User.id == os.environ["SAURI_LOCAL_USER_ID"])
                .values(
                    name="Renamed Local Tester",
                    is_sales=False,
                )
            )
    finally:
        await engine.dispose()
    # Local mode grants the owner all local features even if the account was migrated with a different role.
    monkeypatch.setenv("APP_ENV", "production")
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://127.0.0.1:8000") as client:
        headers = {"Cookie": f"sauri_local={TOKEN}", "Sec-Fetch-Site": "same-origin"}
        response = await client.get("/api/v1/local/me", headers=headers)
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed Local Tester"
        assert response.json()["is_sales"] is False
        assert (await client.get("/api/v1/engines/providers", headers=headers)).status_code == 200
