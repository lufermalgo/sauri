"""CORS allow-list, security headers and docs exposure of the API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.infra.http_security import HttpSecurityConfigError, cors_allowed_origins
from app.main import create_app

EXTENSION_ORIGIN = "chrome-extension://ilnkkojmkfnbdilogldabpodoobfigce"
PORTAL_ORIGIN = "http://localhost:5173"
FOREIGN_ORIGIN = "https://evil.example"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CORS_ALLOWED_ORIGINS", "EXTENSION_ORIGINS", "APP_ENV", "ENABLE_API_DOCS"):
        monkeypatch.delenv(name, raising=False)


def _client(**kwargs: object) -> TestClient:
    return TestClient(create_app(), **kwargs)  # type: ignore[arg-type]


def test_default_origins_are_the_portal_dev_server_and_the_extension() -> None:
    assert cors_allowed_origins() == [PORTAL_ORIGIN, "http://127.0.0.1:5173", EXTENSION_ORIGIN]


@pytest.mark.parametrize("origin", [PORTAL_ORIGIN, "http://127.0.0.1:5173", EXTENSION_ORIGIN])
def test_allowed_origin_gets_cors_headers(origin: str) -> None:
    response = _client().get("/health", headers={"Origin": origin})
    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("origin", [FOREIGN_ORIGIN, "null", "http://localhost:5174", "chrome-extension://" + "a" * 32])
def test_foreign_origin_gets_no_cors_headers(origin: str) -> None:
    response = _client().get("/health", headers={"Origin": origin})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_preflight_from_allowed_origin_lists_explicit_methods_and_headers() -> None:
    response = _client().options(
        "/api/v1/meetings",
        headers={
            "Origin": EXTENSION_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == EXTENSION_ORIGIN
    assert response.headers["access-control-allow-origin"] != "*"
    assert "PATCH" in response.headers["access-control-allow-methods"]
    assert "*" not in response.headers["access-control-allow-methods"]
    assert "*" not in response.headers["access-control-allow-headers"]
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_from_foreign_origin_is_refused() -> None:
    response = _client().options(
        "/api/v1/meetings",
        headers={"Origin": FOREIGN_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_preflight_with_unlisted_header_is_refused() -> None:
    response = _client().options(
        "/api/v1/meetings",
        headers={
            "Origin": PORTAL_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-custom-injected",
        },
    )
    assert response.status_code == 400


def test_origins_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    other_id = "b" * 32
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://sauri.example.com, https://sauri.example.com/")
    monkeypatch.setenv("EXTENSION_ORIGINS", other_id)
    assert cors_allowed_origins() == ["https://sauri.example.com", f"chrome-extension://{other_id}"]
    client = _client()
    for origin in (PORTAL_ORIGIN, EXTENSION_ORIGIN):
        assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": origin}).headers
    allowed = client.get("/health", headers={"Origin": "https://sauri.example.com"})
    assert allowed.headers["access-control-allow-origin"] == "https://sauri.example.com"


def test_empty_extension_list_disables_extension_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTENSION_ORIGINS", "")
    assert EXTENSION_ORIGIN not in cors_allowed_origins()


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("CORS_ALLOWED_ORIGINS", "*"),
        ("CORS_ALLOWED_ORIGINS", "https://*.example.com"),
        ("CORS_ALLOWED_ORIGINS", "https://example.com/app"),
        ("CORS_ALLOWED_ORIGINS", "example.com"),
        ("EXTENSION_ORIGINS", "*"),
        ("EXTENSION_ORIGINS", "https://example.com"),
    ],
)
def test_unsafe_origin_settings_refuse_to_start(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(HttpSecurityConfigError):
        create_app()


@pytest.mark.parametrize("path", ["/health", "/does-not-exist"])
def test_security_headers_on_every_response(path: str) -> None:
    response = _client().get(path)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_security_headers_also_cover_preflight_answers() -> None:
    response = _client().options(
        "/health", headers={"Origin": PORTAL_ORIGIN, "Access-Control-Request-Method": "GET"}
    )
    assert response.headers["x-content-type-options"] == "nosniff"


def test_hsts_only_over_https() -> None:
    assert "strict-transport-security" not in _client().get("/health").headers
    secure = _client(base_url="https://testserver").get("/health")
    assert secure.headers["strict-transport-security"].startswith("max-age=")


@pytest.mark.parametrize("environment", [None, "production", "staging", ""])
def test_docs_are_off_outside_development_and_test(monkeypatch: pytest.MonkeyPatch, environment: str | None) -> None:
    if environment is not None:
        monkeypatch.setenv("APP_ENV", environment)
    client = _client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


@pytest.mark.parametrize("environment", ["development", "test", "Development"])
def test_docs_are_on_in_development_and_test(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    monkeypatch.setenv("APP_ENV", environment)
    client = _client()
    assert client.get("/openapi.json").status_code == 200
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert docs.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_docs_can_be_forced_on_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    assert _client().get("/openapi.json").status_code == 200
    monkeypatch.setenv("ENABLE_API_DOCS", "yes")
    assert _client().get("/openapi.json").status_code == 404
