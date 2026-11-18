"""Property 6: every registered data route is guarded before parsing or side effects."""

import re

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.local.conftest import ORIGIN, TOKEN, local_application  # noqa: F401
from tests.local.routes import api_routes

ATTACKS = [
    ({}, 403),
    ({"Host": "foreign.test:8000", "Cookie": f"sauri_local={TOKEN}", "Sec-Fetch-Site": "same-origin"}, 421),
    *[
        ({"Cookie": f"sauri_local={TOKEN}", "Sec-Fetch-Site": site}, 403)
        for site in ("same-site", "cross-site", "none", "")
    ],
    ({"Sec-Fetch-Site": "same-origin", "Cookie": "sauri_local=invalid"}, 403),
    ({"Authorization": f"Bearer {TOKEN}", "Origin": "http://localhost:9999"}, 403),
    ({"Authorization": f"Bearer {TOKEN}"}, 403),
    ({"Authorization": "Bearer invalid", "Origin": ORIGIN}, 403),
]


@pytest.mark.parametrize(("headers", "status"), ATTACKS)
async def test_every_data_route_rejects_untrusted_requests(
    local_app: FastAPI, headers: dict[str, str], status: int
) -> None:
    tested = 0
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        for route in api_routes(local_app.routes):
            if route.path.startswith("/api/v1/media/") or route.path == "/api/v1/local/pair":
                continue
            for method in route.methods:
                # Status is the explicit host+same-origin cookie bootstrap exception.
                if (
                    route.path == "/api/v1/local/status"
                    and status == 403
                    and headers.get("Sec-Fetch-Site") == "same-origin"
                ):
                    continue
                path = re.sub(r"\{[^}]+\}", "missing-id", route.path)
                response = await client.request(method, path, headers=headers)
                assert response.status_code == status, (method, path, response.text)
                assert response.json() == {
                    "detail": "local_host_required" if status == 421 else "local_origin_required"
                }
                assert "set-cookie" not in response.headers
                tested += 1
    assert tested >= 54


async def test_preflight_checks_host_and_extension_origin(local_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        headers = {
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        response = await client.options("/api/v1/ingestion/upload", headers=headers)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ORIGIN
        for change, code in [({"Host": "evil.test:8000"}, 421), ({"Origin": "http://localhost:9999"}, 403)]:
            assert (await client.options("/api/v1/ingestion/upload", headers=headers | change)).status_code == code


async def test_host_guard_and_explicit_exclusions(local_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        assert (await client.get("/health", headers={"Host": "monitor.test"})).status_code == 200
        # The media route authorizes by its own signed token: the guard must not answer for it.
        media = await client.get("/api/v1/media/signed")
        assert media.status_code != 421
        assert media.json().get("detail") != "local_origin_required"
        for path in ("/", "/api/v1/media/signed", "/api/v1/local/pair"):
            assert (await client.get(path, headers={"Host": "evil.test:8000"})).status_code == 421
        for host in ("localhost", "localhost:8001", "localhost:8000.evil.test", "localhost:8000@evil.test"):
            assert (await client.get("/api/v1/local/status", headers={"Host": host})).status_code == 421
        response = await client.get("/api/v1/local/status", headers=[("Host", "localhost:8000"), ("Host", "evil.test")])
        assert response.status_code == 421


async def test_simple_fetch_form_and_image_cannot_read_or_write(local_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=local_app), base_url="http://localhost:8000") as client:
        # Even a same-site page that receives the Strict cookie must be rejected by Fetch Metadata.
        client.cookies.set("sauri_local", TOKEN)
        headers = {"Origin": "http://localhost:9999", "Sec-Fetch-Site": "same-site"}
        fetched = await client.get("/api/v1/meetings/", headers=headers)
        image = await client.get(
            "/api/v1/meetings/synthetic-id/download",
            headers=headers | {"Accept": "image/avif,image/webp,*/*", "Sec-Fetch-Dest": "image"},
        )
        form = await client.post(
            "/api/v1/ingestion/upload",
            headers=headers,
            files={"audio": ("synthetic.webm", b"synthetic test content", "audio/webm")},
            data={"data": "{}"},
        )
        for response in (fetched, image, form):
            assert response.status_code == 403
            assert response.json() == {"detail": "local_origin_required"}
            assert "access-control-allow-origin" not in response.headers


async def test_host_guard_follows_the_configured_api_port(local_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setenv("SAURI_API_PORT", "18100")
    application = create_app()
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://localhost:18100") as client:
        for host in ("localhost:18100", "127.0.0.1:18100"):
            response = await client.get("/api/v1/meetings/", headers={"Host": host})
            assert response.status_code == 403, host
            assert response.json() == {"detail": "local_origin_required"}
        for host in ("localhost:8000", "127.0.0.1:8000", "localhost:18101", "evil.test:18100"):
            response = await client.get("/api/v1/meetings/", headers={"Host": host})
            assert response.status_code == 421, host


@pytest.mark.parametrize("value", ["0", "65536", "80a", "-1", " 8000 x"])
def test_invalid_api_port_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from app.auth.local import LocalConfigurationError, local_hosts

    monkeypatch.setenv("SAURI_API_PORT", value)
    with pytest.raises(LocalConfigurationError, match="invalid_api_port"):
        local_hosts()
