"""Management service: authentication, secret handling and the absence of any secret-returning route."""

from __future__ import annotations

import json
import logging
import stat
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from conftest import ENGINE_TOKEN, MANAGEMENT_TOKEN
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sauri_engine_common.secrets import SecretRecord, SecretUnavailableError

REF = "sauri/owner-1/provider-1"
URL = f"/v1/secrets/{REF}"
AUTH = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}
ORIGIN = "https://api.example.com"
# The prefix keeps a random key from being a substring of fixed response or log text.
KEYS = st.text(min_size=8, max_size=200, alphabet=st.characters(blacklist_categories=("Cs",))).map(
    lambda text: "KEY-" + text
)
FIXTURE_OK = settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@pytest.fixture
def client(host: ModuleType) -> Iterator[TestClient]:
    with TestClient(host.app, base_url="http://127.0.0.1:8005", raise_server_exceptions=False) as test_client:
        yield test_client


def put(client: TestClient, key: str, origin: str = ORIGIN, headers: dict[str, str] | None = None) -> Any:
    return client.put(URL, json={"key": key, "origin": origin}, headers=headers or AUTH)


# --- authentication ---------------------------------------------------------------------------------

PROTECTED = [
    ("GET", "/health"),
    ("GET", "/v1/engines/status"),
    ("PUT", URL),
    ("DELETE", URL),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_every_route_rejects_missing_and_wrong_credentials(client: TestClient, method: str, path: str) -> None:
    body = {"json": {"key": "k" * 20, "origin": ORIGIN}} if method == "PUT" else {}
    for headers in (
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": f"Bearer {ENGINE_TOKEN}"},  # the engine token authorizes nothing here
        {"Authorization": f"Basic {MANAGEMENT_TOKEN}"},
        {"Authorization": MANAGEMENT_TOKEN},
        {"Authorization": f"Bearer {MANAGEMENT_TOKEN}x"},
        {"Authorization": f"Bearer {MANAGEMENT_TOKEN[:-1]}"},
    ):
        response = client.request(method, path, headers=headers, **body)
        assert response.status_code == 401, (headers, response.text)
        assert response.json() == {"error": {"code": "unauthorized"}}
        assert response.headers["www-authenticate"] == "Bearer"


def test_authentication_is_unavailable_when_the_token_file_is_missing_or_empty(
    client: TestClient, host: ModuleType, tmp_path: Path
) -> None:
    host.MANAGEMENT_TOKEN_PATH = tmp_path / "does-not-exist"
    assert client.get("/health", headers=AUTH).status_code == 503
    empty = tmp_path / "empty"
    empty.write_text("\n")
    host.MANAGEMENT_TOKEN_PATH = empty
    for method, path in PROTECTED:
        response = client.request(method, path, headers=AUTH, **({"json": {}} if method == "PUT" else {}))
        assert response.status_code == 503
        assert response.json() == {"error": {"code": "management_auth_unavailable"}}


def test_the_token_is_compared_in_constant_time() -> None:
    source = (Path(__file__).parents[2] / "host-engine" / "native_main.py").read_text()
    assert "secrets.compare_digest" in source


def test_authenticated_health_reports_status_and_store(client: TestClient) -> None:
    body = client.get("/health", headers=AUTH).json()
    assert body == {"status": "ok", "version": "1.0.0", "secret_store": "file"}


# --- no route returns a secret ----------------------------------------------------------------------


def test_the_route_inventory_has_no_secret_reader(host: ModuleType) -> None:
    routes = {(method, route.path) for route in host.app.routes for method in getattr(route, "methods", set())}
    routes -= {("HEAD", "/health"), ("HEAD", "/v1/engines/status")}
    assert routes == {
        ("GET", "/health"),
        ("GET", "/v1/engines/status"),
        ("PUT", "/v1/secrets/{ref:path}"),
        ("DELETE", "/v1/secrets/{ref:path}"),
    }


def test_a_stored_secret_cannot_be_read_back_through_any_method(client: TestClient) -> None:
    key = "KEY-readback-0123456789"
    assert put(client, key).status_code == 200
    for method in ("GET", "HEAD", "POST", "PATCH", "OPTIONS"):
        response = client.request(method, URL, headers=AUTH)
        assert response.status_code == 405
        assert key not in response.text
    assert client.get("/v1/secrets", headers=AUTH).status_code in (404, 405)
    assert client.get("/openapi.json", headers=AUTH).status_code == 404
    assert client.get("/docs", headers=AUTH).status_code == 404


@FIXTURE_OK
@given(KEYS)
def test_responses_never_contain_the_key_and_the_hint_is_the_last_four(client: TestClient, key: str) -> None:
    """Property 3 for the host service."""
    response = put(client, key)
    assert response.status_code == 200
    assert response.json() == {"key_hint": key[-4:] if len(key) >= 12 else None}
    assert key not in response.text
    assert set(response.json()) == {"key_hint"}
    assert key not in str(dict(response.headers))
    assert key not in client.delete(URL, headers=AUTH).text


def test_short_keys_have_no_hint(client: TestClient) -> None:
    assert put(client, "shortkey123").json() == {"key_hint": None}
    assert put(client, "twelvechars!").json() == {"key_hint": "ars!"}


def test_the_largest_accepted_record_fits_every_store(client: TestClient) -> None:
    assert put(client, "K" * 2048, "https://" + "a" * 240 + ".com").status_code == 200


def test_put_replaces_the_secret_and_binds_the_canonical_origin(client: TestClient, host: ModuleType) -> None:
    assert put(client, "KEY-first-value-1234", "https://API.Example.com:443/v1").status_code == 200
    assert host._store.get(REF) == SecretRecord(key="KEY-first-value-1234", origin=ORIGIN)
    assert put(client, "KEY-second-value-12", "http://127.0.0.1:11434").status_code == 200
    assert host._store.get(REF) == SecretRecord(key="KEY-second-value-12", origin="http://127.0.0.1:11434")
    files = list((host.secrets_dir).iterdir())
    assert len(files) == 1 and stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(host.secrets_dir.stat().st_mode) == 0o700


def test_delete_is_idempotent_and_removes_the_secret(client: TestClient, host: ModuleType) -> None:
    put(client, "KEY-to-delete-1234")
    for _ in range(2):
        response = client.delete(URL, headers=AUTH)
        assert response.status_code == 204 and response.content == b""
    with pytest.raises(SecretUnavailableError):
        host._store.get(REF)


# --- strict inputs ----------------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["bad%20ref", "a%0Ab", "sauri/%C3%B1", "x" * 201, "a%00b"])
def test_invalid_refs_are_rejected(client: TestClient, ref: str) -> None:
    for method in ("PUT", "DELETE"):
        extra = {"json": {"key": "KEY-12345678901", "origin": ORIGIN}} if method == "PUT" else {}
        response = client.request(method, f"/v1/secrets/{ref}", headers=AUTH, **extra)
        # A newline in the path never even reaches the handler (router 404); the rest are refused as invalid.
        assert response.status_code in (404, 422)
        if response.status_code == 422:
            assert response.json() == {"error": {"code": "invalid_secret_ref"}}


@pytest.mark.parametrize(
    "payload",
    [
        {"key": "KEY-12345678901"},
        {"origin": ORIGIN},
        {"key": "", "origin": ORIGIN},
        {"key": "KEY-12345678901", "origin": ""},
        {"key": "KEY-12345678901", "origin": "not an origin"},
        {"key": "KEY-12345678901", "origin": "ftp://api.example.com"},
        {"key": "KEY-12345678901", "origin": "https://user:pw@api.example.com"},
        {"key": 12345678901234, "origin": ORIGIN},
        {"key": "KEY-12345678901", "origin": ORIGIN, "extra": "x"},
        {"key": "K" * 2049, "origin": ORIGIN},
        {"key": "KEY-12345678901", "origin": "https://" + "a" * 250 + ".com"},
        ["KEY-12345678901"],
    ],
)
def test_invalid_bodies_are_rejected_without_echoing_input(client: TestClient, payload: Any) -> None:
    response = client.put(URL, json=payload, headers=AUTH)
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_request"}}
    assert "KEY-" not in response.text


def test_malformed_json_is_rejected_without_echoing_input(client: TestClient) -> None:
    response = client.put(URL, content=b'{"key": "KEY-12345678901", "origin": ', headers={**AUTH})
    assert response.status_code == 422
    assert "KEY-" not in response.text


def test_a_query_string_is_refused(client: TestClient) -> None:
    response = client.put(f"{URL}?key=KEY-12345678901", json={"key": "KEY-12345678901", "origin": ORIGIN}, headers=AUTH)
    assert response.status_code == 422


def test_oversized_bodies_are_refused_by_declared_and_streamed_size(client: TestClient, host: ModuleType) -> None:
    big = {"key": "K" * 40000, "origin": ORIGIN}
    assert client.put(URL, json=big, headers=AUTH).status_code == 413

    def chunks() -> Iterator[bytes]:
        for _ in range(100):
            yield b"x" * 1024

    streamed = client.put(URL, content=chunks(), headers=AUTH)
    assert streamed.status_code == 413
    assert streamed.json() == {"error": {"code": "payload_too_large"}}
    with pytest.raises(SecretUnavailableError):
        host._store.get(REF)


def test_unauthenticated_requests_are_rejected_before_the_body_is_read(client: TestClient) -> None:
    response = client.put(URL, content=b"x" * 40000)
    assert response.status_code == 401


# --- failures keep values out -----------------------------------------------------------------------


class ExplodingStore:
    name = "exploding"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def put(self, ref: str, record: SecretRecord) -> None:
        raise self.error

    def get(self, ref: str) -> SecretRecord:
        raise self.error

    def delete(self, ref: str) -> None:
        raise self.error


def test_a_store_failure_is_a_coded_503(client: TestClient, host: ModuleType) -> None:
    host._store = ExplodingStore(SecretUnavailableError())
    response = put(client, "KEY-12345678901")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "secret_unavailable"}}
    assert client.delete(URL, headers=AUTH).status_code == 503


def test_unexpected_errors_return_a_bare_500_and_log_only_the_class(
    client: TestClient, host: ModuleType, caplog: pytest.LogCaptureFixture
) -> None:
    key = "KEY-explosive-1234567890"
    host._store = ExplodingStore(RuntimeError(f"failed while storing {key}"))
    with caplog.at_level(logging.DEBUG):
        response = put(client, key)
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error"}}
    assert key not in response.text + caplog.text
    assert "RuntimeError" in caplog.text


def test_no_log_line_contains_the_key_on_any_path(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    key = "KEY-logging-probe-1234567"
    with caplog.at_level(logging.DEBUG):
        put(client, key)
        put(client, key, origin="bad origin")
        client.put(URL, json={"key": key}, headers=AUTH)
        client.put(URL, json={"key": key, "origin": ORIGIN}, headers={"Authorization": "Bearer nope"})
        client.put("/v1/secrets/bad%20ref", json={"key": key, "origin": ORIGIN}, headers=AUTH)
        client.delete(URL, headers=AUTH)
    assert key not in caplog.text
    assert MANAGEMENT_TOKEN not in caplog.text


def test_responses_are_not_cacheable(client: TestClient) -> None:
    for response in (client.get("/health", headers=AUTH), put(client, "KEY-12345678901"), client.get("/health")):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


# --- engine status ----------------------------------------------------------------------------------


@pytest.fixture
def fake_gateways() -> Iterator[dict[str, int]]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200 if self.server.healthy else 503)  # type: ignore[attr-defined]
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args: Any) -> None:
            pass

    servers = []
    ports: dict[str, int] = {}
    for name, healthy in (("asr", True), ("diar", False)):
        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.healthy = healthy  # type: ignore[attr-defined]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        ports[name] = server.server_address[1]
    closed = HTTPServer(("127.0.0.1", 0), Handler)
    ports["llm"] = closed.server_address[1]
    closed.server_close()
    yield ports
    for server in servers:
        server.shutdown()
        server.server_close()


def test_engine_status_reports_each_process(
    client: TestClient, host: ModuleType, fake_gateways: dict[str, int]
) -> None:
    host.ENGINES = (
        ("asr", fake_gateways["asr"]), ("diar", fake_gateways["diar"]), ("llm", fake_gateways["llm"]), ("host", 8005),
    )
    body = client.get("/v1/engines/status", headers=AUTH).json()
    states = {engine["id"]: engine["state"] for engine in body["engines"]}
    assert states == {"asr": "running", "diar": "unhealthy", "llm": "stopped", "host": "running"}
    assert body["secret_store"] == "file"
    assert json.dumps(body).find("token") == -1
