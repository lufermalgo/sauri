"""The authenticated ``/api/v1/engines/local/*`` proxy of the host's local-model routes.

Two layers: a recording fake host (routing, fixed target, error relay, token safety) and the real
host-engine application with a loopback download server (the whole install and polling flow through the
proxy). Nothing contacts a real provider or the owner's running host service.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.engines.host_client import CUSTOM_TIMEOUT_S, LOCAL_TIMEOUT_S, HostClient, get_host_client
from app.main import app
from tests.engines.conftest import MANAGEMENT_TOKEN, auth_headers
from tests.host_engine.conftest import load_host_module
from tests.local_models_support import REVISION, catalog_entry, write_catalog

LOCAL = "/api/v1/engines/local"
JOB = "a" * 32


@dataclass
class Recorder:
    """What the fake host received, and what it answers next."""

    calls: list[tuple[str, str, str, str | None]] = field(default_factory=list)  # method, path, query, auth
    answer: tuple[int, Any] = (200, {"ok": True})
    raw: bytes | None = None
    bodies: list[bytes] = field(default_factory=list)


def fake_host(recorder: Recorder) -> FastAPI:
    host = FastAPI(docs_url=None, openapi_url=None)

    @host.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def anything(request: Request, path: str) -> Response:
        recorder.calls.append(
            (request.method, "/" + path, request.url.query, request.headers.get("authorization"))
        )
        recorder.bodies.append(await request.body())
        status, body = recorder.answer
        if recorder.raw is not None:
            return Response(recorder.raw, status_code=status, media_type="application/json")
        if status == 204:
            return Response(status_code=204)
        return JSONResponse(body, status_code=status)

    return host


@pytest.fixture
def recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    token_file = tmp_path / "management_token"
    token_file.write_text(MANAGEMENT_TOKEN + "\n")
    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("APP_ENV", "test")
    state = Recorder()
    client = HostClient("http://host.test", transport=ASGITransport(app=fake_host(state)))
    app.dependency_overrides[get_host_client] = lambda: client
    try:
        yield state
    finally:
        app.dependency_overrides.pop(get_host_client, None)


@pytest.fixture
async def http(engines_db: Any) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


ROUTES = [
    ("GET", "/hardware", "/v1/hardware"),
    ("GET", "/models", "/v1/local/models"),
    ("POST", "/adopt", "/v1/local/adopt"),
    ("POST", "/models/whisper-small-q5_1/install", "/v1/local/models/whisper-small-q5_1/install"),
    ("POST", "/models/qwen3.5-4b-q4_k_m/verify", "/v1/local/models/qwen3.5-4b-q4_k_m/verify"),
    ("DELETE", "/models/qwen3.5-4b-q4_k_m", "/v1/local/models/qwen3.5-4b-q4_k_m"),
    ("GET", f"/jobs/{JOB}", f"/v1/local/jobs/{JOB}"),
    ("POST", f"/jobs/{JOB}/cancel", f"/v1/local/jobs/{JOB}/cancel"),
]


@pytest.mark.parametrize(("method", "path", "target"), ROUTES)
async def test_every_route_needs_a_signed_in_user_and_reaches_the_host_only_after(
    http: AsyncClient, recorder: Recorder, method: str, path: str, target: str
) -> None:
    anonymous = await http.request(method, LOCAL + path)
    assert anonymous.status_code == 401 and recorder.calls == []
    forged = await http.request(method, LOCAL + path, headers={"Authorization": "Bearer not-a-token"})
    assert forged.status_code == 401 and recorder.calls == []


@pytest.mark.parametrize(("method", "path", "target"), ROUTES)
async def test_each_route_calls_one_fixed_host_route_with_the_management_token_only(
    http: AsyncClient, recorder: Recorder, method: str, path: str, target: str
) -> None:
    recorder.answer = (204, None) if method == "DELETE" else (202 if method == "POST" else 200, {"state": "ok"})
    # A query string is never forwarded, whatever the caller sends.
    response = await http.request(
        method, f"{LOCAL}{path}?url=https://evil.example/x&token=leak", headers=auth_headers()
    )
    assert response.status_code == {"DELETE": 204, "POST": 202}.get(method, 200), response.text
    assert recorder.calls == [(method, target, "", f"Bearer {MANAGEMENT_TOKEN}")]
    assert response.headers["cache-control"] == "no-store"
    assert MANAGEMENT_TOKEN not in response.text and MANAGEMENT_TOKEN not in str(response.headers)
    assert (response.json() == {"state": "ok"}) if response.content else method == "DELETE"


@pytest.mark.parametrize(
    "path",
    [
        "/models/Upper/install",
        "/models/-leading/verify",
        "/models/" + "a" * 65 + "/install",
        "/models/a%2F..%2F..%2Fsecrets/install",
        "/models/a%20b/verify",
        "/jobs/not-a-job",
        f"/jobs/{'A' * 32}",
        f"/jobs/{'a' * 33}/cancel",
    ],
)
async def test_ids_outside_the_catalog_and_job_alphabets_never_reach_the_host(
    http: AsyncClient, recorder: Recorder, path: str
) -> None:
    method = "GET" if "/jobs/" in path and not path.endswith("cancel") else "POST"
    response = await http.request(method, LOCAL + path, headers=auth_headers())
    assert response.status_code in (404, 422)
    assert recorder.calls == []


async def test_the_listing_relays_the_adoption_fields_untouched(http: AsyncClient, recorder: Recorder) -> None:
    body = {
        "catalog_version": 1, "active_job": None, "recommendations": {},
        "active": {"transcription": "whisper-large-v3-turbo-q5_0", "summary": None},
        "adoption": {"job_id": JOB, "outcomes": {"qwen3.5-9b-q4_k_m": "adopted"}},
        "models": [{
            "id": "qwen3.5-9b-q4_k_m", "state": "installed", "availability": "installed", "active": True,
            "in_use": True, "location": "legacy", "reason": None, "verifying": False, "verified_by": "hash",
            "install": None,
        }],
    }  # fmt: skip
    recorder.answer = (200, body)
    response = await http.get(f"{LOCAL}/models", headers=auth_headers())
    assert response.status_code == 200 and response.json() == body
    assert recorder.calls == [("GET", "/v1/local/models", "", f"Bearer {MANAGEMENT_TOKEN}")]


async def test_adoption_through_the_proxy_reaches_the_real_host_and_never_forwards_the_request(
    http: AsyncClient, recorder: Recorder
) -> None:
    recorder.answer = (409, {"error": {"code": "job_active", "job_id": JOB}})
    response = await http.post(
        f"{LOCAL}/adopt?models_dir=/etc", headers=auth_headers(), json={"path": "/Users/private"}
    )
    assert (response.status_code, response.json()) == (409, {"detail": "job_active", "job_id": JOB})
    assert recorder.calls == [("POST", "/v1/local/adopt", "", f"Bearer {MANAGEMENT_TOKEN}")]


async def test_other_host_routes_are_not_exposed(http: AsyncClient, recorder: Recorder) -> None:
    for method, path in [("GET", "/secrets/x"), ("PUT", "/secrets/x"), ("POST", "/providers/probe")]:
        response = await http.request(method, LOCAL + path, headers=auth_headers())
        assert response.status_code in (404, 405)
    assert recorder.calls == []


async def test_host_refusals_keep_their_status_code_and_figures(http: AsyncClient, recorder: Recorder) -> None:
    cases = [
        (507, {"error": {"code": "insufficient_disk", "needed_bytes": 700, "free_bytes": 5}}, "insufficient_disk"),
        (409, {"error": {"code": "model_in_use", "processes": ["summary"]}}, "model_in_use"),
        (409, {"error": {"code": "job_active", "job_id": JOB}}, "job_active"),
        (404, {"error": {"code": "unknown_model"}}, "unknown_model"),
    ]
    for status, body, code in cases:
        recorder.answer = (status, body)
        response = await http.post(f"{LOCAL}/models/whisper-small-q5_1/install", headers=auth_headers())
        expected = {"detail": code, **{k: v for k, v in body["error"].items() if k != "code"}}
        assert (response.status_code, response.json()) == (status, expected)


async def test_only_scalar_figures_and_short_word_lists_are_relayed(http: AsyncClient, recorder: Recorder) -> None:
    recorder.answer = (409, {"error": {
        "code": "model_in_use", "processes": ["summary"], "nested": {"deep": 1}, "long": "x" * 500,
        "Bad-Name": 1, "detail": "overridden", "many": list(range(40)), "path": "/Users/private", "n": 3,
    }})  # fmt: skip
    response = await http.delete(f"{LOCAL}/models/qwen3.5-4b-q4_k_m", headers=auth_headers())
    body = response.json()
    assert body["detail"] == "model_in_use" and body["processes"] == ["summary"] and body["n"] == 3
    assert not {"nested", "long", "Bad-Name", "many"} & set(body)


@pytest.mark.parametrize(
    ("status", "payload", "raw"),
    [(500, {"error": {"code": "internal_error"}}, None), (400, {"unexpected": True}, None), (409, None, b"[1]")],
)
async def test_unclassifiable_or_server_side_host_answers_become_a_generic_bad_gateway(
    http: AsyncClient, recorder: Recorder, status: int, payload: Any, raw: bytes | None
) -> None:
    recorder.answer, recorder.raw = (status, payload), raw
    response = await http.get(f"{LOCAL}/models", headers=auth_headers())
    if raw is not None:
        assert (response.status_code, response.json()) == (503, {"detail": "host_unavailable"})
    else:
        assert (response.status_code, response.json()) == (502, {"detail": "host_error"})


@pytest.mark.parametrize(
    ("status", "body"),
    [(401, {"error": {"code": "unauthorized"}}), (503, {"error": {"code": "management_auth_unavailable"}})],
)
async def test_an_unusable_management_token_is_reported_as_host_unavailable(
    http: AsyncClient, recorder: Recorder, status: int, body: Any
) -> None:
    recorder.answer = (status, body)
    response = await http.get(f"{LOCAL}/hardware", headers=auth_headers())
    assert (response.status_code, response.json()) == (503, {"detail": "host_unavailable"})
    assert MANAGEMENT_TOKEN not in response.text


async def test_other_service_unavailable_answers_keep_their_code(http: AsyncClient, recorder: Recorder) -> None:
    recorder.answer = (503, {"error": {"code": "catalog_unavailable"}})
    response = await http.get(f"{LOCAL}/models", headers=auth_headers())
    assert (response.status_code, response.json()) == (503, {"detail": "catalog_unavailable"})


async def test_a_missing_token_file_or_unreachable_host_is_host_unavailable(
    http: AsyncClient, recorder: Recorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(tmp_path / "absent"))
    response = await http.get(f"{LOCAL}/models", headers=auth_headers())
    assert (response.status_code, response.json()) == (503, {"detail": "host_unavailable"})

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(tmp_path / "management_token"))
    client = HostClient("http://host.test", transport=httpx.MockTransport(refuse))
    app.dependency_overrides[get_host_client] = lambda: client
    response = await http.get(f"{LOCAL}/models", headers=auth_headers())
    assert (response.status_code, response.json()) == (503, {"detail": "host_unavailable"})


# --- custom models (the only routes with a body) ----------------------------------------------------

SHA = "c" * 40
RESOLVE = {"process": "summary", "source": "https://huggingface.co/someone/tiny-gguf"}
INSTALL = {"process": "summary", "repo": "someone/tiny-gguf", "revision": SHA, "file": "sub/model-Q4_K_M.gguf"}


@pytest.mark.parametrize(
    ("path", "body", "status", "target"),
    [
        ("/custom/resolve", RESOLVE, 200, "/v1/local/custom/resolve"),
        ("/custom/install", INSTALL, 202, "/v1/local/custom/install"),
    ],
)
async def test_custom_routes_forward_only_the_validated_fields(
    http: AsyncClient, recorder: Recorder, path: str, body: dict[str, Any], status: int, target: str
) -> None:
    anonymous = await http.post(LOCAL + path, json=body)
    assert anonymous.status_code == 401 and recorder.calls == []
    recorder.answer = (status, {"state": "ok"})
    response = await http.post(f"{LOCAL}{path}?url=https://evil.example/x", headers=auth_headers(), json=body)
    assert response.status_code == status, response.text
    assert recorder.calls == [("POST", target, "", f"Bearer {MANAGEMENT_TOKEN}")]
    assert json.loads(recorder.bodies[0]) == body
    assert response.headers["cache-control"] == "no-store" and response.json() == {"state": "ok"}


async def test_custom_routes_wait_longer_for_the_host(
    http: AsyncClient, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[float] = []
    original = HostClient._send

    async def spy(self: HostClient, method: str, path: str, *, timeout: float, json: Any = None) -> httpx.Response:
        seen.append(timeout)
        return await original(self, method, path, timeout=timeout, json=json)

    monkeypatch.setattr(HostClient, "_send", spy)
    await http.post(f"{LOCAL}/custom/resolve", headers=auth_headers(), json=RESOLVE)
    await http.post(f"{LOCAL}/custom/install", headers=auth_headers(), json=INSTALL)
    await http.get(f"{LOCAL}/models", headers=auth_headers())
    assert seen == [CUSTOM_TIMEOUT_S, CUSTOM_TIMEOUT_S, LOCAL_TIMEOUT_S] and CUSTOM_TIMEOUT_S >= 30


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/custom/resolve", {"process": "summary"}),
        ("/custom/resolve", RESOLVE | {"extra": 1}),
        ("/custom/resolve", RESOLVE | {"process": "diarization"}),
        ("/custom/resolve", RESOLVE | {"source": ""}),
        ("/custom/resolve", RESOLVE | {"source": "x" * 600}),
        ("/custom/install", INSTALL | {"sha256": "0" * 64}),
        ("/custom/install", INSTALL | {"revision": "main"}),
        ("/custom/install", INSTALL | {"repo": "someone"}),
        ("/custom/install", INSTALL | {"repo": "someone/../x"}),
        ("/custom/install", INSTALL | {"file": "../model.gguf"}),
        ("/custom/install", INSTALL | {"file": "/etc/model.gguf"}),
        ("/custom/install", INSTALL | {"file": "a b.gguf"}),
        ("/custom/install", {k: v for k, v in INSTALL.items() if k != "file"}),
    ],
)
async def test_custom_bodies_outside_the_contract_never_reach_the_host(
    http: AsyncClient, recorder: Recorder, path: str, body: dict[str, Any]
) -> None:
    response = await http.post(LOCAL + path, headers=auth_headers(), json=body)
    assert response.status_code == 422
    assert recorder.calls == []


async def test_custom_refusals_keep_their_code(http: AsyncClient, recorder: Recorder) -> None:
    for status, code in [(422, "host_not_allowed"), (403, "gated"), (404, "not_found"), (503, "unreachable")]:
        recorder.answer = (status, {"error": {"code": code}})
        response = await http.post(f"{LOCAL}/custom/resolve", headers=auth_headers(), json=RESOLVE)
        assert (response.status_code, response.json()) == (status, {"detail": code})


# --- the real host application behind the proxy ----------------------------------------------------

PAYLOAD = b"synthetic-model-bytes-" * 5000


class Hub:
    """A loopback server that serves the one model file at the catalog's download path."""

    def __init__(self, path: str, data: bytes) -> None:
        wanted, payload = path, data

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                body = payload if self.path == wanted else b""
                self.send_response(200 if self.path == wanted else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
async def real(engines_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    token_file = tmp_path / "management_token"
    token_file.write_text(MANAGEMENT_TOKEN + "\n")
    token_file.chmod(0o600)
    module: ModuleType = load_host_module(token_file, tmp_path / "secrets")
    import local_models as host_models  # the host module; load_host_module put its folder on sys.path

    entry = catalog_entry("e2e-model", "transcription", "e2e.bin", PAYLOAD, default=True)
    catalog_path = write_catalog(tmp_path / "catalog.json", [entry])
    from sauri_engine_common.recommend import load_catalog

    hub = Hub(f"/test/repo/resolve/{REVISION}/e2e.bin", PAYLOAD)
    policy = host_models.DownloadPolicy(
        base_url=hub.base, scheme="http", host_suffixes=("127.0.0.1",), ports=None, token_hosts=()
    )
    service = host_models.LocalModelService(
        tmp_path / "models", load_catalog(catalog_path), policy, tmp_path / "no-token"
    )
    monkeypatch.setattr(host_models, "_service", service)
    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("APP_ENV", "test")
    client = HostClient("http://host.test", transport=ASGITransport(app=module.app))
    app.dependency_overrides[get_host_client] = lambda: client
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            yield api, service
    finally:
        app.dependency_overrides.pop(get_host_client, None)
        hub.close()


async def test_the_real_host_install_poll_verify_and_remove_flow_through_the_proxy(real: Any) -> None:
    api, service = real
    headers = auth_headers()
    models = await api.get(f"{LOCAL}/models", headers=headers)
    assert models.status_code == 200
    listed = {model["id"]: model for model in models.json()["models"]}
    assert listed["e2e-model"]["state"] == "not_installed"

    started = await api.post(f"{LOCAL}/models/e2e-model/install", headers=headers)
    assert started.status_code == 202
    job = started.json()
    async with asyncio.timeout(20):
        while job["state"] == "running":
            await asyncio.sleep(0.02)
            polled = await api.get(f"{LOCAL}/jobs/{job['id']}", headers=headers)
            assert polled.status_code == 200
            job = polled.json()
    assert job["state"] == "done" and job["result"] == "installed" and job["bytes_done"] == len(PAYLOAD)
    assert (service.models_dir / "e2e.bin").read_bytes() == PAYLOAD
    again = await api.post(f"{LOCAL}/models/e2e-model/install", headers=headers)
    assert (again.status_code, again.json()) == (409, {"detail": "already_installed"})

    after = await api.get(f"{LOCAL}/models", headers=headers)
    assert {m["id"]: m for m in after.json()["models"]}["e2e-model"]["state"] == "installed"
    verify = await api.post(f"{LOCAL}/models/e2e-model/verify", headers=headers)
    assert verify.status_code == 202
    async with asyncio.timeout(20):
        while (await api.get(f"{LOCAL}/jobs/{verify.json()['id']}", headers=headers)).json()["state"] == "running":
            await asyncio.sleep(0.02)

    # The catalog default of a process is in use until another model is chosen: removal is refused with
    # the processes that use it.
    blocked = await api.delete(f"{LOCAL}/models/e2e-model", headers=headers)
    assert (blocked.status_code, blocked.json()) == (409, {"detail": "model_in_use", "processes": ["transcription"]})
    (service.models_dir / "selection.json").write_text('{"transcription": "another"}', encoding="utf-8")
    removed = await api.delete(f"{LOCAL}/models/e2e-model", headers=headers)
    assert removed.status_code == 204 and not (service.models_dir / "e2e.bin").exists()


async def test_the_real_host_answers_for_hardware_and_unknown_ids(real: Any) -> None:
    api, _service = real
    headers = auth_headers()
    hardware = await api.get(f"{LOCAL}/hardware", headers=headers)
    assert hardware.status_code == 200 and {"arch", "memory_gib", "cores", "disk_free_bytes"} <= set(hardware.json())
    unknown = await api.post(f"{LOCAL}/models/not-in-catalog/install", headers=headers)
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "unknown_model"})
    assert (await api.get(f"{LOCAL}/jobs/{JOB}", headers=headers)).json() == {"detail": "unknown_job"}
    cancel = await api.post(f"{LOCAL}/jobs/{JOB}/cancel", headers=headers)
    assert (cancel.status_code, cancel.json()) == (404, {"detail": "unknown_job"})
    missing = await api.post(f"{LOCAL}/models/e2e-model/verify", headers=headers)
    assert (missing.status_code, missing.json()) == (404, {"detail": "not_installed"})


async def test_the_real_host_refuses_another_host_through_the_proxy_without_any_download(real: Any) -> None:
    api, service = real
    body = {"process": "summary", "source": "https://example.com/someone/tiny-gguf"}
    response = await api.post(f"{LOCAL}/custom/resolve", headers=auth_headers(), json=body)
    assert (response.status_code, response.json()) == (422, {"detail": "host_not_allowed"})
    asr_body = INSTALL | {"process": "transcription"}
    incompatible = await api.post(f"{LOCAL}/custom/install", headers=auth_headers(), json=asr_body)
    assert (incompatible.status_code, incompatible.json()) == (422, {"detail": "no_compatible_files"})
    assert not (service.models_dir / "custom").exists()
