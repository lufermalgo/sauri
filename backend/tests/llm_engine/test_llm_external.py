"""The LLM gateway serves external routes (``X-Sauri-Route``) next to the local ``llama-server`` flow.

Providers are fake asyncio servers on 127.0.0.1 and ``llama-server`` is a fake executable; no real provider,
key or model is involved, and the owner's engine ports are never touched (every port is a random free one).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import socket
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
import uvicorn
from sauri_engine_common.external.errors import ERROR_CODES
from sauri_engine_common.route import Route, RouteTimeouts, encode_route
from sauri_engine_common.secrets import FileSecretStore, SecretRecord

from tests.llm_engine.external_support import (
    KEY,
    SUMMARY,
    FakeProvider,
    Handler,
    anthropic_events,
    failing,
    hang_after_first_event,
    hang_before_any_byte,
    openai_events,
    replying,
    wait_until,
)

TOKEN = "synthetic-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
REF = "sauri/owner-1/provider-1"
FAST = RouteTimeouts(connect_s=2.0, first_byte_s=5.0, idle_s=5.0, total_s=20.0)
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
REQUEST: dict[str, Any] = {
    "model": "ignored-by-the-gateway",
    "temperature": 0,
    "stream": False,
    "messages": [{"role": "user", "content": "Transcript: private meeting words"}],
    "response_format": {"type": "json_schema", "json_schema": {"name": "summary", "strict": True, "schema": SCHEMA}},
}
Serve = Callable[[Handler], Awaitable[FakeProvider]]


@dataclass
class Gateway:
    module: ModuleType
    client: httpx.AsyncClient
    store: FileSecretStore
    reads: list[str]

    def route(
        self,
        fake: FakeProvider,
        *,
        kind: str = "openai_compatible",
        transport: str = "openai-chat",
        suffix: str = "/v1",
        consent: int | None = 1,
        secret_ref: str | None = REF,
        timeouts: RouteTimeouts = FAST,
        capability: str = "summary",
    ) -> str:
        return encode_route(Route(
            version=1, capability=capability, kind=kind, transport=transport, base_url=f"{fake.url}{suffix}",  # type: ignore[arg-type]
            model="m-requested", secret_ref=secret_ref, consent_version=consent, timeouts=timeouts,
        ))  # fmt: skip

    def store_key(self, fake: FakeProvider, ref: str = REF, *, origin: str | None = None) -> None:
        self.store.put(ref, SecretRecord(key=KEY, origin=origin or fake.url))

    async def chat(
        self, route: str | None, body: dict[str, Any] | None = None, *, token: str | None = TOKEN
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if route is not None:
            headers["X-Sauri-Route"] = route
        return await self.client.post("/v1/chat/completions", json=body or REQUEST, headers=headers)


@pytest.fixture
async def gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Gateway]:
    engine_dir = Path(__file__).parents[2] / "llm-engine"
    monkeypatch.syspath_prepend(str(engine_dir))
    spec = importlib.util.spec_from_file_location("sauri_test_llm_external", engine_dir / "native_main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token = tmp_path / "token"
    token.write_text(TOKEN)
    monkeypatch.setattr(module, "ENGINE_TOKEN_PATH", token)
    store = FileSecretStore(tmp_path / "secrets")
    reads: list[str] = []
    original_get = store.get

    def counting_get(ref: str) -> SecretRecord:
        reads.append(ref)
        return original_get(ref)

    monkeypatch.setattr(store, "get", counting_get)
    monkeypatch.setattr(module, "_secret_store", store)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    fake = tmp_path / "llama-server"
    fake.write_text(f"""#!{sys.executable}
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{{}}')
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({{'choices': [{{'message': {{'content': 'local answer'}}}}]}}).encode())
HTTPServer(('127.0.0.1', {port}), Handler).serve_forever()
""")
    fake.chmod(0o700)
    module.server.binary = fake
    module.server.url = f"http://127.0.0.1:{port}"
    module.server.idle_seconds = 60
    module.server.startup_seconds = 5
    transport = httpx.ASGITransport(app=module.app)
    async with module.lifespan(module.app), httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Gateway(module, client, store, reads)


@pytest.fixture
async def serve() -> AsyncIterator[Serve]:
    started: list[FakeProvider] = []

    async def make(handler: Handler) -> FakeProvider:
        fake = FakeProvider(handler)
        await fake.start()
        started.append(fake)
        return fake

    yield make
    for fake in started:
        await fake.close()


def assert_error(
    response: httpx.Response, status: int, code: str, *, retryable: bool, retry_after: int | None = None
) -> None:
    assert response.status_code == status, response.text
    assert response.json() == {"error": {"code": code, "retryable": retryable, "retry_after_s": retry_after}}
    assert KEY not in response.text


# --- success path ------------------------------------------------------------------------------------------


async def test_openai_route_returns_a_chat_completion_with_usage(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(['{"title": ', '"Weekly sync"}'])))
    gateway.store_key(fake)
    response = await gateway.chat(gateway.route(fake))
    assert response.status_code == 200, response.text
    result = response.json()
    assert json.loads(result["choices"][0]["message"]["content"]) == {"title": "Weekly sync"}
    assert result["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    sent = fake.seen[0]
    assert sent.path == "/v1/chat/completions" and sent.headers["authorization"] == f"Bearer {KEY}"
    assert sent.json()["model"] == "m-requested" and sent.json()["stream"] is True  # the route names the model
    assert sent.json()["response_format"] == REQUEST["response_format"]
    assert gateway.module.server.process is None  # no llama-server was started for an external route


async def test_anthropic_route_adapts_the_schema_and_returns_the_openai_shape(
    gateway: Gateway, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = await serve(replying(anthropic_events([json.dumps(SUMMARY)])))
    gateway.store_key(fake)
    # Anthropic is a public provider; this test points it at a loopback fake, which only local-server kinds may do.
    monkeypatch.setattr(gateway.module, "LOCAL_SERVER_KINDS", frozenset({"anthropic"}))
    schema = {**SCHEMA, "properties": {"title": {"type": "string", "maxLength": 120}}, "additionalProperties": False}
    body = {**REQUEST, "response_format": {"type": "json_schema", "json_schema": {"name": "s", "schema": schema}}}
    route = gateway.route(fake, kind="anthropic", transport="anthropic-messages", suffix="")
    response = await gateway.chat(route, body)
    assert response.status_code == 200, response.text
    assert response.json()["usage"]["total_tokens"] == 18
    sent = fake.seen[0]
    assert sent.path == "/v1/messages" and sent.headers["x-api-key"] == KEY
    assert '"maxLength"' not in json.dumps(sent.json()["output_config"])  # adapted for the provider


async def test_a_public_provider_kind_cannot_be_pointed_at_loopback(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake)
    response = await gateway.chat(gateway.route(fake, kind="openai"))
    assert_error(response, 400, "provider_bad_request", retryable=False)
    assert fake.connections == 0


async def test_external_route_never_takes_the_llama_server_lock(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake)
    async with gateway.module.server.lock:  # local generation is busy
        async with asyncio.timeout(5):
            response = await gateway.chat(gateway.route(fake))
    assert response.status_code == 200


async def test_local_generation_still_works_without_a_header(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake)
    assert (await gateway.chat(gateway.route(fake))).status_code == 200
    local = await gateway.chat(None, {"model": "synthetic", "messages": [{"role": "user", "content": "x"}]})
    assert local.status_code == 200 and local.json()["choices"][0]["message"]["content"] == "local answer"
    assert gateway.module.server.process is not None  # the local path started llama-server


async def test_streaming_requests_are_refused_before_any_connection(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake)
    response = await gateway.chat(gateway.route(fake), {**REQUEST, "stream": True})
    assert_error(response, 400, "provider_bad_request", retryable=False)
    assert fake.connections == 0


# --- refusals: nothing leaves the machine ---------------------------------------------------------------------


async def test_external_route_requires_the_engine_token(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake)
    route = gateway.route(fake)
    assert (await gateway.chat(route, token=None)).status_code == 401
    assert (await gateway.chat(route, token="wrong")).status_code == 401
    assert fake.connections == 0 and gateway.reads == []


async def test_missing_consent_is_refused_without_reading_the_key_or_connecting(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake)
    response = await gateway.chat(gateway.route(fake, consent=None))
    assert_error(response, 403, "consent_missing", retryable=False)
    assert fake.connections == 0 and gateway.reads == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "ollama"},  # not offered (unverified) for the summary process
        {"kind": "assemblyai", "transport": "assemblyai"},  # a provider of another process
        {"transport": "anthropic-messages"},  # the kind does not use that transport
        {"capability": "transcription", "kind": "groq", "transport": "openai-audio"},  # another gateway's process
        {"capability": "diarization"},
    ],
)
async def test_unsupported_pairs_are_refused_without_connecting(
    gateway: Gateway, serve: Serve, overrides: dict[str, Any]
) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake)
    response = await gateway.chat(gateway.route(fake, **overrides))
    assert_error(response, 400, "provider_unsupported", retryable=False)
    assert fake.connections == 0 and gateway.reads == []


async def test_a_key_issued_for_another_origin_is_never_sent(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    gateway.store_key(fake, origin="https://api.other-provider.example")
    response = await gateway.chat(gateway.route(fake))
    assert_error(response, 403, "origin_mismatch", retryable=False)
    assert fake.connections == 0


async def test_an_unreadable_key_is_a_classified_error(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(["{}"])))
    response = await gateway.chat(gateway.route(fake))  # nothing stored under the reference
    assert_error(response, 503, "secret_unavailable", retryable=False)
    assert fake.connections == 0


@pytest.mark.parametrize("header", ["not-a-route", "e30"])
async def test_malformed_headers_keep_the_local_error_codes(gateway: Gateway, header: str) -> None:
    response = await gateway.chat(header)
    assert response.status_code == 422 and "detail" in response.json()
    assert gateway.module.server.process is None


# --- error classes and timeouts -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("handler", "status", "code", "retryable", "retry_after"),
    [
        (
            failing(429, {"error": {"code": "rate_limit_exceeded"}}, {"Retry-After": "7"}),
            429, "provider_rate_limited", True, 7,
        ),
        (failing(401, {"error": {"code": "invalid_api_key"}}), 502, "provider_auth", False, None),
        (failing(402, {"error": {}}), 502, "provider_quota", True, None),
        (failing(503, {"error": {}}), 502, "provider_unavailable", True, None),
        (failing(504, {"error": {}}), 504, "provider_timeout", True, None),
        (failing(400, {"error": {"code": "context_length_exceeded"}}), 400, "provider_context_exceeded", False, None),
        (failing(413, {"error": {}}), 400, "provider_context_exceeded", False, None),
        (failing(400, {"error": {"code": "invalid_value"}}), 400, "provider_bad_request", False, None),
        (replying(openai_events(["this is not json"])), 502, "provider_invalid_output", False, None),
    ],
)
async def test_provider_failures_map_to_status_and_the_error_body(
    gateway: Gateway, serve: Serve, handler: Handler, status: int, code: str, retryable: bool, retry_after: int | None
) -> None:
    fake = await serve(handler)
    gateway.store_key(fake)
    response = await gateway.chat(gateway.route(fake))
    assert_error(response, status, code, retryable=retryable, retry_after=retry_after)
    if retry_after is not None:
        assert response.headers["retry-after"] == str(retry_after)
    assert code in ERROR_CODES


async def test_a_stream_cut_off_midway_is_provider_unavailable(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(replying(openai_events(['{"title": '])[:1]))  # one chunk, then the connection closes
    gateway.store_key(fake)
    response = await gateway.chat(gateway.route(fake))
    assert_error(response, 502, "provider_unavailable", retryable=True)


async def test_the_route_first_byte_timeout_applies(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(hang_before_any_byte)
    gateway.store_key(fake)
    route = gateway.route(fake, timeouts=RouteTimeouts(connect_s=2.0, first_byte_s=0.3, idle_s=5.0, total_s=20.0))
    started = time.monotonic()
    response = await gateway.chat(route)
    assert_error(response, 504, "provider_timeout", retryable=True)
    assert 0.25 <= time.monotonic() - started < 3.0


async def test_the_route_idle_timeout_applies(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(hang_after_first_event(openai_events(["{"])))
    gateway.store_key(fake)
    route = gateway.route(fake, timeouts=RouteTimeouts(connect_s=2.0, first_byte_s=5.0, idle_s=0.3, total_s=20.0))
    started = time.monotonic()
    response = await gateway.chat(route)
    assert_error(response, 504, "provider_timeout", retryable=True)
    assert time.monotonic() - started < 3.0


async def test_the_total_budget_never_exceeds_the_gateway_request_budget(gateway: Gateway, serve: Serve) -> None:
    fake = await serve(hang_after_first_event(openai_events(["{"])))
    gateway.store_key(fake)
    gateway.module.server.request_seconds = 0.4
    route = gateway.route(fake, timeouts=RouteTimeouts(connect_s=2.0, first_byte_s=60.0, idle_s=60.0, total_s=900.0))
    started = time.monotonic()
    response = await gateway.chat(route)
    assert_error(response, 504, "provider_timeout", retryable=True)
    assert time.monotonic() - started < 3.0
    assert fake.open_streams == 0


# --- secrets stay out of logs ------------------------------------------------------------------------------------


async def test_neither_the_key_nor_meeting_text_reach_the_logs(
    gateway: Gateway, serve: Serve, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    ok = await serve(replying(openai_events(['{"title": "x"}'])))
    gateway.store_key(ok)
    await gateway.chat(gateway.route(ok))
    leaky = {"error": {"message": f"Incorrect API key {KEY} private meeting words"}}
    bad = await serve(failing(401, leaky))
    gateway.store_key(bad, ref="sauri/owner-1/provider-2")
    response = await gateway.chat(gateway.route(bad, secret_ref="sauri/owner-1/provider-2"))
    assert response.status_code == 502
    logged = "\n".join(record.getMessage() + str(record.exc_info) for record in caplog.records)
    assert KEY not in logged and "private meeting words" not in logged and "Bearer" not in logged
    assert KEY not in response.text and "private meeting words" not in response.text


# --- disconnect watcher (Property 12) -----------------------------------------------------------------------------


@asynccontextmanager
async def listening(module: ModuleType) -> AsyncIterator[int]:
    """The gateway on a real socket (random free port): only a real server reports a client that went away."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(module.app, log_level="warning", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        await wait_until(lambda: server.started, limit_s=5.0)
        yield port
    finally:
        server.should_exit = True
        await task
        sock.close()


async def post_and_hang_up(port: int, route: str, *, after: Callable[[], bool]) -> float:
    """Send the request, wait until ``after`` holds, close the socket and return when it was closed."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    body = json.dumps(REQUEST).encode()
    head = (
        f"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {TOKEN}\r\n"
        f"X-Sauri-Route: {route}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    )
    writer.write(head.encode() + body)
    await writer.drain()
    await wait_until(after, limit_s=5.0)
    await asyncio.sleep(0.2)
    writer.close()
    closed_at = time.monotonic()
    await asyncio.gather(reader.read(), return_exceptions=True)
    return closed_at


@pytest.mark.parametrize("phase", ["before_first_byte", "mid_stream"])
async def test_closing_the_client_closes_the_provider_stream_within_two_seconds(
    gateway: Gateway, serve: Serve, phase: str
) -> None:
    handler = hang_before_any_byte if phase == "before_first_byte" else hang_after_first_event(openai_events(["{"]))
    fake = await serve(handler)
    gateway.store_key(fake)
    async with listening(gateway.module) as port:
        closed_at = await post_and_hang_up(port, gateway.route(fake), after=lambda: fake.open_streams == 1)
        await wait_until(lambda: fake.open_streams == 0, limit_s=2.0)
        assert time.monotonic() - closed_at <= 2.0
        # The gateway is still healthy and the external call never held the local lock.
        assert not gateway.module.server.lock.locked()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            assert (await client.get("/health")).status_code == 200


async def test_a_client_that_stays_gets_its_answer_while_the_watcher_runs(
    gateway: Gateway, serve: Serve, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = await serve(replying(openai_events(['{"title": "Weekly sync"}'])))
    gateway.store_key(fake)
    monkeypatch.setattr(gateway.module, "DISCONNECT_POLL_S", 0.05)
    async with listening(gateway.module) as port, httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        response = await client.post(
            "/v1/chat/completions", json=REQUEST, headers={**AUTH, "X-Sauri-Route": gateway.route(fake)}
        )
    assert response.status_code == 200
    assert fake.open_streams == 0
