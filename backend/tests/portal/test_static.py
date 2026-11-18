"""Portal routing, cache policy and isolation from API routes and private files."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Headers

from app.main import create_app
from app.portal.csp import inline_script_hash

INDEX = '<!doctype html><html><script>window.theme = "dark";</script><div id="root"></div></html>'


@pytest.fixture
def portal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "dist"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (assets / "x.js").write_text("window.loaded = true;")
    (assets / "style.css").write_text("body { color: black; }")
    monkeypatch.setenv("SAURI_PORTAL_DIR", str(root))
    return root


def assert_portal_headers(headers: Headers) -> None:
    # Keep the full portal policy, not the JSON-only policy of the API middleware.
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()"
    )
    assert "strict-transport-security" not in headers
    csp = headers["content-security-policy"]
    for directive in (
        "default-src 'self'", "style-src 'self'", "img-src 'self' data:", "media-src 'self' blob:",
        "font-src 'self'", "connect-src 'self'", "object-src 'none'", "base-uri 'self'",
        "form-action 'self'", "frame-ancestors 'none'",
    ):
        assert directive in csp.split("; ")
    assert "unsafe-inline" not in csp
    assert "http:" not in csp
    assert "https:" not in csp


@pytest.mark.parametrize("path", ["/", "/index.html", "/meetings/abc", "/settings/motores", "/unknown?query=value"])
def test_spa_fallback(portal: Path, path: str) -> None:
    response = TestClient(create_app()).get(path)
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    script_source = f"script-src 'self' '{inline_script_hash(portal / 'index.html')}'"
    assert script_source in response.headers["content-security-policy"]
    assert_portal_headers(response.headers)


@pytest.mark.parametrize("filename", ["x.js", "style.css"])
def test_assets_are_immutable(portal: Path, filename: str) -> None:
    client = TestClient(create_app())
    response = client.get(f"/assets/{filename}")
    assert response.status_code == 200
    assert response.content == (portal / "assets" / filename).read_bytes()
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert_portal_headers(response.headers)
    cached = client.get(f"/assets/{filename}", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304
    assert cached.headers["cache-control"] == response.headers["cache-control"]
    assert_portal_headers(cached.headers)


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/v1/does-not-exist", "/api-health"])
def test_unknown_api_paths_stay_json_404(portal: Path, path: str) -> None:
    response = TestClient(create_app()).get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found"}
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "cache-control" not in response.headers


def test_health_unaffected(portal: Path) -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "cache-control" not in response.headers
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


@pytest.mark.parametrize("path", ["/assets/missing.js", "/assets/%2e%2e/index.html", "/assets/..%2f..%2fprivate.txt"])
def test_assets_never_fall_back_or_escape(portal: Path, path: str) -> None:
    (portal.parent / "private.txt").write_text("private fixture")
    response = TestClient(create_app()).get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert "private fixture" not in response.text
    assert INDEX not in response.text
    assert "cache-control" not in response.headers


def test_assets_reject_symlinks_outside_their_directory(portal: Path) -> None:
    (portal / "assets/leak.html").symlink_to(portal / "index.html")
    response = TestClient(create_app()).get("/assets/leak.html")
    assert response.status_code == 404
    assert INDEX not in response.text


@pytest.mark.parametrize("setting", [None, "missing", "file"])
def test_portal_is_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str | None) -> None:
    monkeypatch.delenv("SAURI_PORTAL_DIR", raising=False)
    if setting is not None:
        path = tmp_path / setting
        if setting == "file":
            path.write_text(INDEX)
        monkeypatch.setenv("SAURI_PORTAL_DIR", str(path))
    client = TestClient(create_app())
    assert client.get("/").status_code == 404
    assert client.get("/assets/x.js").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


def test_invalid_build_refuses_to_start(portal: Path) -> None:
    (portal / "index.html").write_text("<html>No theme script</html>")
    with pytest.raises(ValueError, match="expected exactly one inline script"):
        create_app()


def test_spa_only_handles_get(portal: Path) -> None:
    response = TestClient(create_app()).post("/settings/motores")
    assert response.status_code == 405
    assert response.headers["content-type"] == "application/json"


def test_api_trailing_slash_redirect_is_not_shadowed_by_the_portal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI

    from app.portal.static import mount_portal

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html><script>1</script></html>")
    monkeypatch.setenv("SAURI_PORTAL_DIR", str(tmp_path))
    application = FastAPI()

    @application.get("/api/v1/items/")
    def items() -> list[str]:
        return []

    mount_portal(application)
    client = TestClient(application)
    redirected = client.get("/api/v1/items", follow_redirects=False)
    assert redirected.status_code == 307
    assert redirected.headers["location"].endswith("/api/v1/items/")
    assert client.get("/api/v1/items").json() == []
    assert client.get("/api/v1/unknown").headers["content-type"].startswith("application/json")
