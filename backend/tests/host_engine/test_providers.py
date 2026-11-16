"""Provider probe, model catalog and local discovery: fake servers on 127.0.0.1 and the SSRF policy."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import socket
import ssl
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from conftest import MANAGEMENT_TOKEN
from fastapi import FastAPI
from fastapi.testclient import TestClient
from providers import (
    LOCAL_TIMEOUT_S,
    MAX_RESPONSE_BYTES,
    ProviderService,
    SafeHttp,
    address_allowed,
    classify_address,
    filter_models,
    parse_ip_literal,
    parse_target,
    starter_model,
)
from providers import ModelInfo as Model
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.secrets import FileSecretStore, SecretRecord

KEY = "sk-test-KEY-0123456789abcdef"
REF = "sauri/owner-1/provider-1"
AUTH = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}


# --- fake provider ------------------------------------------------------------------------------------


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class Reply:
    status: int = 200
    body: Any = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    delay_s: float = 0.0
    raw: bytes | None = None


class FakeProvider:
    """Threaded HTTP(S) server on 127.0.0.1; routes map ``"METHOD /path"`` to a reply or a callable."""

    def __init__(self, ssl_context: ssl.SSLContext | None = None) -> None:
        self.routes: dict[str, Reply | Callable[[Seen], Reply]] = {}
        self.seen: list[Seen] = []
        self.sni: list[str | None] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                request = Seen(self.command, self.path, {k.lower(): v for k, v in self.headers.items()},
                               self.rfile.read(length))  # fmt: skip
                outer.seen.append(request)
                route = outer.routes.get(f"{self.command} {self.path.split('?')[0]}")
                reply = route(request) if callable(route) else route or Reply(404, {"error": {"code": "not_found"}})
                if reply.delay_s:
                    time.sleep(reply.delay_s)
                payload = reply.raw if reply.raw is not None else json.dumps(reply.body).encode()
                self.send_response(reply.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                for name, value in reply.headers.items():
                    self.send_header(name, value)
                self.end_headers()
                with contextlib.suppress(OSError):
                    self.wfile.write(payload)

            do_GET = do_POST = _serve  # noqa: N815

            def log_message(self, *_args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if ssl_context is not None:
            ssl_context.sni_callback = lambda _sock, name, _ctx: outer.sni.append(name)  # type: ignore[assignment]
            self.server.socket = ssl_context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    server = FakeProvider()
    yield server
    server.close()


@pytest.fixture
def store(tmp_path: Path) -> FileSecretStore:
    return FileSecretStore(tmp_path / "secrets")


def bind_key(store: FileSecretStore, origin: str, key: str = KEY) -> None:
    store.put(REF, SecretRecord(key=key, origin=origin))


def make_client(store: FileSecretStore, service: ProviderService) -> TestClient:
    from providers import build_router

    async def get_store() -> FileSecretStore:
        return store

    def require_token() -> None:
        return None

    app = FastAPI()
    app.include_router(build_router(get_store, require_token, service))  # type: ignore[arg-type]
    return TestClient(app, raise_server_exceptions=False)


def target(fake_url: str, **extra: Any) -> dict[str, Any]:
    body = {"kind": "openai", "transport": "openai-chat", "base_url": f"{fake_url}/v1", "allow_local": True}
    body.update(extra)
    return body


def models_reply(*ids: str) -> Reply:
    return Reply(200, {"object": "list", "data": [{"id": model_id} for model_id in ids]})


CHAT_OK = Reply(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})


# --- address classifier ---------------------------------------------------------------------------------

PUBLIC = ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"]
LOOPBACK = ["127.0.0.1", "127.255.255.254", "::1", "::ffff:127.0.0.1", "::ffff:7f00:1"]
PRIVATE = ["10.0.0.1", "172.16.0.1", "172.31.255.255", "192.168.1.1", "fd00::1", "fc00::1", "::ffff:10.0.0.1"]
BLOCKED = [
    "0.0.0.0", "0.1.2.3", "169.254.169.254", "169.254.170.2", "100.64.0.1", "100.100.100.200", "192.0.0.192",
    "224.0.0.1", "239.255.255.255", "240.0.0.1", "255.255.255.255", "198.18.0.1", "203.0.113.5",
    "::", "fe80::1", "fec0::1", "ff02::1", "fd00:ec2::254", "::ffff:169.254.169.254", "::ffff:0.0.0.0",
    "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "2002:7f00:1::", "2002:a9fe:a9fe::", "::127.0.0.1", "::10.0.0.1",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2", "2001:db8::1",
]  # fmt: skip


@pytest.mark.parametrize("text", PUBLIC)
def test_public_addresses_are_allowed_everywhere(text: str) -> None:
    assert classify_address(ip_address(text)) == "public"
    assert address_allowed(ip_address(text), allow_local=False)


@pytest.mark.parametrize("text", LOOPBACK)
def test_loopback_needs_the_local_allowance(text: str) -> None:
    assert classify_address(ip_address(text)) == "loopback"
    assert not address_allowed(ip_address(text), allow_local=False)
    assert address_allowed(ip_address(text), allow_local=True)


@pytest.mark.parametrize("text", PRIVATE)
def test_private_ranges_need_the_local_allowance(text: str) -> None:
    assert classify_address(ip_address(text)) == "private"
    assert not address_allowed(ip_address(text), allow_local=False)
    assert address_allowed(ip_address(text), allow_local=True)


@pytest.mark.parametrize("text", BLOCKED)
def test_link_local_metadata_and_special_ranges_are_never_allowed(text: str) -> None:
    assert classify_address(ip_address(text)) == "blocked"
    assert not address_allowed(ip_address(text), allow_local=True)
    assert not address_allowed(ip_address(text), allow_local=False)


HOSTILE_SPELLINGS = [
    ("2130706433", "127.0.0.1"),  # decimal
    ("0x7f000001", "127.0.0.1"),  # single hex
    ("0x7f.0.0.1", "127.0.0.1"),  # mixed hex
    ("0177.0.0.1", "127.0.0.1"),  # octal
    ("017700000001", "127.0.0.1"),  # single octal
    ("127.1", "127.0.0.1"),  # short form
    ("127.0.1", "127.0.0.1"),
    ("0", "0.0.0.0"),
    ("0.0.0.0", "0.0.0.0"),
    ("2852039166", "169.254.169.254"),  # decimal metadata
    ("0xa9fea9fe", "169.254.169.254"),
    ("0251.0376.0251.0376", "169.254.169.254"),
    ("169.254.43518", "169.254.169.254"),
    ("127.0.0.1.", "127.0.0.1"),  # trailing dot
    ("[::1]", "::1"),
    ("::ffff:127.0.0.1", "::ffff:7f00:1"),
]


@pytest.mark.parametrize(("spelling", "expected"), HOSTILE_SPELLINGS)
def test_every_spelling_of_an_address_parses_to_the_address_it_means(spelling: str, expected: str) -> None:
    parsed = parse_ip_literal(spelling)
    assert parsed is not None and parsed == ip_address(expected)
    assert not address_allowed(parsed, allow_local=False)


@pytest.mark.parametrize("name", ["example.com", "localhost", "a.b.c.d.e", "256.1.1.1", "08.0.0.1", "1.2.3.4.5"])
def test_names_and_invalid_numbers_are_not_literals(name: str) -> None:
    assert parse_ip_literal(name) is None


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "https://user:pass@example.com/",
        "https://example.com\\@127.0.0.1/",
        "https://example.com#@127.0.0.1/",
        "https://fe80::1%25en0/",
        "https://example.com:99999/",
        "https://example.com:80:80/",
        "https:///path",
        "https://exa mple.com/",
        "https://example.com/\n",
        "https://" + "a" * 300 + ".com/",
    ],
)
def test_ambiguous_urls_are_rejected_before_any_lookup(url: str) -> None:
    with pytest.raises(ProviderError) as info:
        parse_target(url)
    assert info.value.code == "provider_bad_request"


def test_host_header_keeps_a_non_default_port() -> None:
    assert parse_target("https://Api.Example.com/v1").host_header == "api.example.com"
    assert parse_target("http://[::1]:8080/x").host_header == "[::1]:8080"


# --- SafeHttp: policy before any connection --------------------------------------------------------------


def fixed_resolver(*addresses: str) -> Callable[[str, int], Any]:
    calls: list[str] = []

    async def resolve(host: str, _port: int) -> list[str]:
        calls.append(host)
        return list(addresses)

    resolve.calls = calls  # type: ignore[attr-defined]
    return resolve


async def get(http: SafeHttp, url: str, *, allow_local: bool = False, timeout: float = 5.0) -> Any:
    return await http.request("GET", url, headers={}, allow_local=allow_local, total_timeout_s=timeout)


@pytest.mark.parametrize("spelling", ["127.0.0.1", "2130706433", "0x7f.1", "0177.0.0.1", "[::1]", "0", "localhost"])
async def test_loopback_targets_are_refused_without_the_allowance_and_never_contacted(
    fake: FakeProvider, spelling: str
) -> None:
    host = spelling if spelling != "localhost" else "localhost"
    http = SafeHttp(resolver=fixed_resolver("127.0.0.1"))
    with pytest.raises(ProviderError) as info:
        await get(http, f"http://{host}:{fake.port}/v1/models")
    assert info.value.reason == "address_not_allowed"
    assert fake.seen == []


@pytest.mark.parametrize("address", ["169.254.169.254", "fd00:ec2::254", "10.0.0.5", "0.0.0.0", "::ffff:127.0.0.1"])
async def test_a_name_that_resolves_to_a_forbidden_address_is_refused(address: str) -> None:
    resolver = fixed_resolver(address)
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(resolver=resolver), "https://innocent.example.com/v1/models")
    assert info.value.reason == "address_not_allowed"


async def test_metadata_is_refused_even_with_the_local_allowance() -> None:
    for host in ("169.254.169.254", "2852039166", "[fd00:ec2::254]"):
        with pytest.raises(ProviderError) as info:
            await get(SafeHttp(), f"https://{host}/latest/meta-data/", allow_local=True)
        assert info.value.reason == "address_not_allowed"
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(resolver=fixed_resolver("169.254.169.254")), "https://x.example.com/", allow_local=True)
    assert info.value.reason == "address_not_allowed"


async def test_one_forbidden_address_among_public_ones_rejects_the_call() -> None:
    resolver = fixed_resolver("8.8.8.8", "127.0.0.1")
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(resolver=resolver), "https://mixed.example.com/")
    assert info.value.reason == "address_not_allowed"


async def test_plain_http_is_only_for_loopback_targets() -> None:
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(resolver=fixed_resolver("8.8.8.8")), "http://public.example.com/v1/models")
    assert info.value.reason == "https_required"
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(resolver=fixed_resolver("10.0.0.5")), "http://lan.example.com/v1/models", allow_local=True)
    assert info.value.reason == "https_required"


async def test_an_unresolvable_name_is_classified_as_name_not_resolved() -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        raise socket.gaierror(8, "nodename nor servname provided")

    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(resolver=resolve), "https://nowhere.invalid/v1/models")
    assert (info.value.code, info.value.reason) == ("provider_unavailable", "name_not_resolved")


# --- SafeHttp: connection behavior ------------------------------------------------------------------------


async def test_the_connection_is_pinned_to_the_checked_address_and_resolved_once(fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("a")
    calls: list[str] = []

    async def rebinding(host: str, _port: int) -> list[str]:
        calls.append(host)  # a first answer that passes the check, then one that points at metadata
        return ["127.0.0.1"] if len(calls) == 1 else ["169.254.169.254"]

    http = SafeHttp(resolver=rebinding)
    result = await get(http, f"http://provider.test:{fake.port}/v1/models", allow_local=True)
    assert result.status == 200
    assert len(calls) == 1
    assert fake.seen[0].headers["host"] == f"provider.test:{fake.port}"


async def test_redirects_are_not_followed(fake: FakeProvider) -> None:
    target_server = FakeProvider()
    try:
        fake.routes["GET /v1/models"] = Reply(302, {}, {"location": f"{target_server.url}/steal"})
        result = await get(SafeHttp(), f"{fake.url}/v1/models", allow_local=True)
        assert result.status == 302
        assert target_server.seen == []
    finally:
        target_server.close()


async def test_oversized_responses_are_cut(fake: FakeProvider) -> None:
    fake.routes["GET /big"] = Reply(200, raw=b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(), f"{fake.url}/big", allow_local=True)
    assert info.value.reason == "response_too_large"


async def test_a_slow_server_hits_the_total_timeout(fake: FakeProvider) -> None:
    fake.routes["GET /slow"] = Reply(200, {}, delay_s=1.0)
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(), f"{fake.url}/slow", allow_local=True, timeout=0.2)
    assert (info.value.code, info.value.reason) == ("provider_timeout", "timeout")


async def test_a_closed_port_is_connection_refused() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(ProviderError) as info:
        await get(SafeHttp(), f"http://127.0.0.1:{port}/", allow_local=True)
    assert (info.value.code, info.value.reason) == ("provider_unavailable", "connection_refused")


async def test_the_next_checked_address_is_tried_when_the_first_refuses(fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("a")
    with socket.socket(socket.AF_INET6) as sock:
        try:
            sock.bind(("::1", fake.port))
        except OSError:
            pytest.skip("IPv6 loopback unavailable")
    http = SafeHttp(resolver=fixed_resolver("::1", "127.0.0.1"))
    assert (await get(http, f"http://svc.test:{fake.port}/v1/models", allow_local=True)).status == 200


def make_certificate(tmp_path: Path, name: str) -> Path | None:
    """A self-signed certificate for ``name`` made with whichever openssl works on this machine."""
    pem = tmp_path / "cert.pem"
    for openssl in ("/usr/bin/openssl", shutil.which("openssl")):
        if openssl is None or not Path(openssl).exists():
            continue
        command = [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", f"/CN={name}",
                   "-addext", f"subjectAltName=DNS:{name}", "-keyout", str(pem), "-out", str(pem)]  # fmt: skip
        if subprocess.run(command, capture_output=True, check=False, timeout=60).returncode == 0:
            return pem
    return None


async def test_tls_uses_the_original_name_for_sni_and_certificate_check(tmp_path: Path) -> None:
    pem = make_certificate(tmp_path, "provider.test")
    if pem is None:
        pytest.skip("openssl unavailable")
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(pem)
    client_ctx = ssl.create_default_context(cafile=str(pem))
    server = FakeProvider(server_ctx)
    server.routes["GET /v1/models"] = models_reply("a")
    try:
        # The name resolves to the checked loopback address; the handshake still names provider.test.
        good = SafeHttp(resolver=fixed_resolver("127.0.0.1"), ssl_context=client_ctx)
        assert (await get(good, f"https://provider.test:{server.port}/v1/models", allow_local=True)).status == 200
        assert "provider.test" in server.sni
        # Another name over the same pinned address fails the certificate check.
        with pytest.raises(ProviderError) as info:
            await get(good, f"https://other.test:{server.port}/v1/models", allow_local=True)
        assert info.value.reason == "tls_error"
    finally:
        server.close()


# --- probe -------------------------------------------------------------------------------------------------


def probe(client: TestClient, fake: FakeProvider, **extra: Any) -> dict[str, Any]:
    response = client.post("/v1/providers/probe", json=target(fake.url, **extra))
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.fixture
def service() -> ProviderService:
    return ProviderService(probe_timeout_s=2.0, models_timeout_s=2.0, local_timeout_s=0.5)


@pytest.fixture
def client(store: FileSecretStore, service: ProviderService) -> TestClient:
    return make_client(store, service)


def test_probe_reports_it_responds_with_latency_and_sends_bearer(
    client: TestClient, fake: FakeProvider, store: FileSecretStore
) -> None:
    bind_key(store, fake.url)
    fake.routes["GET /v1/models"] = models_reply("gpt-mini")
    result = probe(client, fake, secret_ref=REF)
    assert result["ok"] is True and result["json_schema_ok"] is None
    assert isinstance(result["latency_ms"], int) and result["latency_ms"] >= 0
    assert fake.seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in json.dumps(result)


def test_probe_uses_the_auth_scheme_of_each_transport(
    client: TestClient, fake: FakeProvider, store: FileSecretStore
) -> None:
    bind_key(store, fake.url)
    fake.routes["GET /v1/models"] = models_reply("claude-haiku-4-5")
    fake.routes["GET /v2/transcript"] = Reply(200, {"transcripts": []})
    fake.routes["GET /v1/projects"] = Reply(200, {"projects": []})
    probe(client, fake, secret_ref=REF, transport="anthropic-messages", base_url=fake.url)
    anthropic = fake.seen[-1]
    assert anthropic.path == "/v1/models?limit=100"
    assert anthropic.headers["x-api-key"] == KEY and anthropic.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in anthropic.headers
    probe(client, fake, secret_ref=REF, transport="anthropic-messages", base_url=f"{fake.url}/v1")
    assert fake.seen[-1].path == "/v1/models?limit=100"
    assert probe(client, fake, secret_ref=REF, transport="assemblyai", base_url=fake.url)["ok"] is True
    assert fake.seen[-1].headers["authorization"] == KEY
    assert probe(client, fake, secret_ref=REF, transport="deepgram", base_url=fake.url)["ok"] is True
    assert fake.seen[-1].headers["authorization"] == f"Token {KEY}"


@pytest.mark.parametrize(
    ("reply", "error_class", "retryable", "cause", "hint"),
    [
        (Reply(401, {"error": {"code": "invalid_api_key"}}), "provider_auth", False, "http_401", "invalid_api_key"),
        (Reply(403, {"error": {"type": "permission_error"}}), "provider_auth", False, "http_403", "permission_error"),
        (Reply(429, {"error": {"code": "rate_limit"}}, {"retry-after": "7"}), "provider_rate_limited", True, "http_429", "rate_limit"),  # noqa: E501
        (Reply(429, {"error": {"code": "insufficient_quota"}}), "provider_quota", True, "http_429", "insufficient_quota"),  # noqa: E501
        (Reply(500, {}), "provider_unavailable", True, "http_500", None),
        (Reply(404, {"error": "no such route"}), "provider_bad_request", False, "http_404", None),
        (Reply(302, {}, {"location": "http://169.254.169.254/"}), "provider_bad_request", False, "redirect_refused", None),  # noqa: E501
        (Reply(200, raw=b"<html>login</html>"), "provider_invalid_output", False, "invalid_response", None),
        (Reply(200, {"data": "nope"}), "provider_invalid_output", False, "invalid_response", None),
    ],
)  # fmt: skip
def test_probe_says_it_does_not_respond_with_a_classified_cause(
    client: TestClient, fake: FakeProvider, reply: Reply, error_class: str, retryable: bool, cause: str,
    hint: str | None,
) -> None:  # fmt: skip
    fake.routes["GET /v1/models"] = reply
    result = probe(client, fake)
    assert result["ok"] is False
    assert (result["error_class"], result["retryable"], result["cause"], result["hint"]) == (
        error_class, retryable, cause, hint,
    )  # fmt: skip
    assert isinstance(result["latency_ms"], int)


def test_probe_carries_retry_after(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = Reply(429, {}, {"retry-after": "7"})
    assert probe(client, fake)["retry_after_s"] == 7


def test_probe_timeout_and_refused_connection(client: TestClient, fake: FakeProvider, store: FileSecretStore) -> None:
    fake.routes["GET /v1/models"] = Reply(200, {}, delay_s=3.0)
    result = probe(make_client(store, ProviderService(probe_timeout_s=0.3)), fake)
    assert (result["ok"], result["error_class"], result["cause"]) == (False, "provider_timeout", "timeout")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    refused = client.post("/v1/providers/probe", json=target(f"http://127.0.0.1:{port}")).json()
    assert (refused["error_class"], refused["cause"]) == ("provider_unavailable", "connection_refused")


def test_probe_name_not_resolved(store: FileSecretStore) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        raise socket.gaierror(8, "unknown")

    client = make_client(store, ProviderService(http=SafeHttp(resolver=resolve)))
    body = {"kind": "openai", "transport": "openai-chat", "base_url": "https://nowhere.invalid/v1"}
    result = client.post("/v1/providers/probe", json=body).json()
    assert (result["ok"], result["error_class"], result["cause"]) == (
        False,
        "provider_unavailable",
        "name_not_resolved",
    )


def test_probe_refuses_forbidden_targets_without_contacting_anything(client: TestClient, fake: FakeProvider) -> None:
    result = client.post("/v1/providers/probe", json=target(fake.url, allow_local=False)).json()
    assert (result["ok"], result["cause"]) == (False, "address_not_allowed")
    metadata = client.post("/v1/providers/probe", json=target("http://169.254.169.254")).json()
    assert metadata["cause"] == "address_not_allowed"
    assert fake.seen == []


def test_probe_does_not_follow_a_redirect_to_another_host(
    client: TestClient, fake: FakeProvider, store: FileSecretStore
) -> None:
    bind_key(store, fake.url)
    elsewhere = FakeProvider()
    try:
        fake.routes["GET /v1/models"] = Reply(307, {}, {"location": f"{elsewhere.url}/v1/models"})
        result = probe(client, fake, secret_ref=REF)
        assert result["cause"] == "redirect_refused"
        assert elsewhere.seen == []  # the key never reaches the redirect target
    finally:
        elsewhere.close()


def test_probe_origin_mismatch_and_missing_key_never_contact_the_provider(
    client: TestClient, fake: FakeProvider, store: FileSecretStore
) -> None:
    bind_key(store, "https://api.openai.com")
    mismatch = probe(client, fake, secret_ref=REF)
    assert (mismatch["ok"], mismatch["error_class"]) == (False, "origin_mismatch")
    missing = probe(client, fake, secret_ref="sauri/owner-1/absent")
    assert (missing["ok"], missing["error_class"]) == (False, "secret_unavailable")
    assert fake.seen == []


def test_probe_never_returns_or_logs_the_key_or_headers(
    client: TestClient, fake: FakeProvider, store: FileSecretStore, caplog: pytest.LogCaptureFixture
) -> None:
    bind_key(store, fake.url)
    caplog.set_level(logging.DEBUG)
    # A hostile provider that echoes the request headers and the key in every error field.
    fake.routes["GET /v1/models"] = lambda seen: Reply(
        401,
        {"error": {"code": seen.headers["authorization"], "type": KEY, "message": KEY, "status": KEY.lower()}},
    )
    response = client.post("/v1/providers/probe", json=target(fake.url, secret_ref=REF))
    assert response.json()["cause"] == "http_401"
    assert response.json()["hint"] is None
    everything = response.text + caplog.text + repr(response.headers)
    assert KEY not in everything and "Bearer" not in everything
    fake.routes["GET /v1/models"] = Reply(401, {"error": {"code": f"bad_{KEY[:8].lower()}_key"}})
    assert client.post("/v1/providers/probe", json=target(fake.url, secret_ref=REF)).json()["hint"] is not None
    assert KEY not in caplog.text


# --- schema check ------------------------------------------------------------------------------------------


def schema_probe(client: TestClient, fake: FakeProvider, **extra: Any) -> dict[str, Any]:
    return probe(client, fake, capability="summary", **extra)


def test_schema_check_accepts_a_provider_that_honors_the_schema(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("text-embedding-3-small", "gpt-4o-mini", "gpt-4o-mini-tts")
    fake.routes["POST /v1/chat/completions"] = CHAT_OK
    result = schema_probe(client, fake)
    assert (result["ok"], result["json_schema_ok"], result["schema_model"]) == (True, True, "gpt-4o-mini")
    sent = json.loads(fake.seen[-1].body)
    assert sent["model"] == "gpt-4o-mini" and sent["stream"] is False
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert "provider" not in sent  # only OpenRouter asks for require_parameters


def test_schema_check_sets_require_parameters_for_openrouter(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("a/model")
    fake.routes["POST /v1/chat/completions"] = CHAT_OK
    assert schema_probe(client, fake, kind="openrouter")["json_schema_ok"] is True
    assert json.loads(fake.seen[-1].body)["provider"] == {"require_parameters": True}


def test_schema_check_rejected_by_the_provider(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("tiny-model")
    fake.routes["POST /v1/chat/completions"] = Reply(400, {"error": {"code": "unsupported_response_format"}})
    result = schema_probe(client, fake)
    assert (result["ok"], result["json_schema_ok"], result["schema_cause"]) == (True, False, "http_400")
    assert result["schema_hint"] == "unsupported_response_format"


@pytest.mark.parametrize("content", ["not json at all", '{"ok": "yes"}', '{"ok": true, "extra": 1}', "[]", None])
def test_schema_check_rejects_output_that_does_not_match(client: TestClient, fake: FakeProvider, content: Any) -> None:
    fake.routes["GET /v1/models"] = models_reply("small-model")
    fake.routes["POST /v1/chat/completions"] = Reply(200, {"choices": [{"message": {"content": content}}]})
    result = schema_probe(client, fake)
    assert (result["json_schema_ok"], result["schema_cause"]) == (False, "output_not_schema")


def test_schema_check_is_unknown_on_transient_failures(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("gpt-4o-mini")
    fake.routes["POST /v1/chat/completions"] = Reply(503, {})
    result = schema_probe(client, fake)
    assert (result["ok"], result["json_schema_ok"], result["schema_error_class"]) == (
        True,
        None,
        "provider_unavailable",
    )


def test_schema_check_needs_a_chat_model(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("text-embedding-3-small")
    result = schema_probe(client, fake)
    assert (result["ok"], result["json_schema_ok"], result["schema_cause"]) == (True, None, "no_chat_model")
    assert [seen.method for seen in fake.seen] == ["GET"]


def test_schema_check_for_anthropic_uses_output_config(
    client: TestClient, fake: FakeProvider, store: FileSecretStore
) -> None:
    bind_key(store, fake.url)
    fake.routes["GET /v1/models"] = Reply(200, {"data": [{"id": "claude-haiku-4-5", "display_name": "Haiku"}]})
    fake.routes["POST /v1/messages"] = Reply(200, {"content": [{"type": "text", "text": '{"ok": true}'}]})
    result = schema_probe(
        client, fake, transport="anthropic-messages", base_url=fake.url, secret_ref=REF, kind="anthropic"
    )
    assert result["json_schema_ok"] is True
    post = fake.seen[-1]
    sent = json.loads(post.body)
    assert post.headers["x-api-key"] == KEY and post.headers["anthropic-version"] == "2023-06-01"
    assert sent["output_config"]["format"]["type"] == "json_schema" and sent["max_tokens"] == 64
    assert "response_format" not in sent


def test_no_schema_check_for_processes_that_do_not_chat(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("whisper-large-v3")
    result = probe(client, fake, capability="transcription", transport="openai-audio")
    assert result["ok"] is True and result["json_schema_ok"] is None and len(fake.seen) == 1


def test_chatgpt_responses_is_not_probed_yet(client: TestClient, fake: FakeProvider) -> None:
    result = probe(client, fake, transport="chatgpt-responses")
    assert (result["ok"], result["error_class"]) == (False, "provider_unsupported")
    assert fake.seen == []


# --- models ------------------------------------------------------------------------------------------------


def list_models(client: TestClient, fake: FakeProvider, **extra: Any) -> Any:
    body = target(fake.url, **{"capability": "summary", **extra})
    return client.post("/v1/providers/models", json=body)


MIXED = models_reply(
    "gpt-4o", "gpt-4o-mini", "gpt-4o-mini-2024-07-18", "text-embedding-3-large", "tts-1", "whisper-1",
    "gpt-image-1", "dall-e-3", "omni-moderation-latest", "gpt-4o-realtime-preview", "gpt-4o-transcribe",
    "gpt-4o-mini-tts", "bge-m3:latest", "embeddinggemma-2:latest", "nomic-embed-text", "multilingual-e5-large",
)  # fmt: skip


def test_models_are_filtered_per_process_and_a_starter_is_chosen(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = MIXED
    chat = list_models(client, fake).json()
    assert [m["id"] for m in chat["models"]] == ["gpt-4o", "gpt-4o-mini", "gpt-4o-mini-2024-07-18"]
    assert chat["starter"] == "gpt-4o-mini"
    audio = list_models(client, fake, capability="transcription").json()
    assert [m["id"] for m in audio["models"]] == ["whisper-1", "gpt-4o-transcribe"]
    assert audio["cached"] is True


def test_models_are_cached_for_24_hours_and_refresh_asks_again(store: FileSecretStore, fake: FakeProvider) -> None:
    now = [1000.0]
    client = make_client(store, ProviderService(clock=lambda: now[0]))
    fake.routes["GET /v1/models"] = models_reply("gpt-4o-mini")
    assert list_models(client, fake).json()["cached"] is False
    assert list_models(client, fake).json()["cached"] is True
    assert len(fake.seen) == 1
    fake.routes["GET /v1/models"] = models_reply("gpt-4o-mini", "gpt-5-mini")
    refreshed = list_models(client, fake, refresh=True).json()
    assert [m["id"] for m in refreshed["models"]] == ["gpt-4o-mini", "gpt-5-mini"] and refreshed["cached"] is False
    assert len(fake.seen) == 2
    now[0] += 24 * 3600 - 1
    assert list_models(client, fake).json()["cached"] is True
    now[0] += 2
    assert list_models(client, fake).json()["cached"] is False
    assert len(fake.seen) == 3


def test_cache_is_per_provider_and_key_reference(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("gpt-4o-mini")
    list_models(client, fake)
    list_models(client, fake, kind="other")
    assert len(fake.seen) == 2


def test_failures_are_not_cached_and_report_a_status(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = Reply(401, {"error": {"code": "invalid_api_key"}})
    response = list_models(client, fake)
    assert response.status_code == 502
    assert response.json() == {"error": {"code": "provider_auth", "retryable": False, "cause": "http_401"}}
    fake.routes["GET /v1/models"] = models_reply("gpt-4o-mini")
    assert list_models(client, fake).status_code == 200


def test_models_request_problems_are_422_and_secret_problems_503(
    client: TestClient, fake: FakeProvider, store: FileSecretStore
) -> None:
    forbidden = list_models(client, fake, allow_local=False)
    assert (forbidden.status_code, forbidden.json()["error"]["cause"]) == (422, "address_not_allowed")
    assert list_models(client, fake, secret_ref="sauri/o/absent").status_code == 503
    bind_key(store, "https://api.openai.com")
    mismatch = list_models(client, fake, secret_ref=REF)
    assert (mismatch.status_code, mismatch.json()["error"]["code"]) == (422, "origin_mismatch")
    assert fake.seen == []


def test_a_local_app_is_asked_every_time(client: TestClient, fake: FakeProvider) -> None:
    fake.routes["GET /v1/models"] = models_reply("qwen2.5:14b")
    list_models(client, fake, kind="ollama")
    list_models(client, fake, kind="ollama")
    assert len(fake.seen) == 2


def test_cache_holds_no_key_material(
    client: TestClient, fake: FakeProvider, store: FileSecretStore, service: ProviderService
) -> None:
    bind_key(store, "http://127.0.0.1:1")
    fake.routes["GET /v1/models"] = models_reply("gpt-4o-mini")
    store.put(REF, SecretRecord(key=KEY, origin=fake.url))
    body = {"kind": "x", "transport": "openai-chat", "base_url": f"{fake.url}/v1", "secret_ref": REF,
            "capability": "summary", "allow_local": False}  # fmt: skip
    assert client.post("/v1/providers/models", json=body).status_code == 422  # loopback needs the allowance
    assert KEY not in repr(service._cache)


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        (["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"], "gpt-4.1-mini"),
        (["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite"], "gemini-2.5-flash"),
        (["claude-opus-4-1", "claude-haiku-4-5-20251001", "claude-haiku-4-5"], "claude-haiku-4-5"),
        (["llama3.2:1b", "qwen2.5:14b"], "qwen2.5:14b"),
        (["o3-preview", "gpt-5-codex"], "gpt-5-codex"),
        ([], None),
    ],
)
def test_starter_model_prefers_the_light_everyday_alias(ids: list[str], expected: str | None) -> None:
    assert starter_model(ids) == expected


def test_filter_keeps_chat_models_only_for_chat_processes() -> None:
    models = [Model(i, i) for i in ("gpt-4o", "bge-m3:latest", "playai-tts", "distil-whisper-large-v3-en")]
    assert [m.id for m in filter_models(models, "summary")] == ["gpt-4o"]
    assert [m.id for m in filter_models(models, "diarization")] == ["distil-whisper-large-v3-en"]


# --- local discovery ----------------------------------------------------------------------------------------


def test_discovery_reports_running_apps_with_chat_models_and_closed_ones(store: FileSecretStore) -> None:
    running = FakeProvider()
    running.routes["GET /v1/models"] = models_reply("qwen2.5:14b", "bge-m3:latest", "embeddinggemma-2:latest")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    apps = (("ollama", "Ollama", running.port), ("lmstudio", "LM Studio", closed_port))
    try:
        client = make_client(store, ProviderService(local_apps=apps, local_timeout_s=0.5))
        result = client.get("/v1/discover/local").json()
    finally:
        running.close()
    ollama, lmstudio = result["apps"]
    assert (ollama["id"], ollama["running"], ollama["base_url"]) == (
        "ollama",
        True,
        f"http://127.0.0.1:{running.port}/v1",
    )
    assert [m["id"] for m in ollama["models"]] == ["qwen2.5:14b"] and ollama["starter"] == "qwen2.5:14b"
    assert (lmstudio["id"], lmstudio["running"]) == ("lmstudio", False) and "models" not in lmstudio
    assert (
        running.seen[0].headers["host"] == f"127.0.0.1:{running.port}"
        and "authorization" not in running.seen[0].headers
    )


def test_discovery_gives_up_on_a_silent_app_and_ignores_garbage(store: FileSecretStore) -> None:
    silent, garbage = FakeProvider(), FakeProvider()
    silent.routes["GET /v1/models"] = Reply(200, {}, delay_s=2.0)
    garbage.routes["GET /v1/models"] = Reply(200, raw=b"not json")
    apps = (("ollama", "Ollama", silent.port), ("lmstudio", "LM Studio", garbage.port))
    try:
        client = make_client(store, ProviderService(local_apps=apps, local_timeout_s=0.3))
        started = time.monotonic()
        result = client.get("/v1/discover/local").json()
        assert time.monotonic() - started < 1.5
    finally:
        silent.close()
        garbage.close()
    assert [app["running"] for app in result["apps"]] == [False, False]


def test_discovery_defaults_target_the_standard_ports_on_loopback_with_a_short_timeout() -> None:
    from providers import LOCAL_APPS

    assert LOCAL_APPS == (("ollama", "Ollama", 11434), ("lmstudio", "LM Studio", 1234))
    assert LOCAL_TIMEOUT_S == 1.5


# --- wired into the host service --------------------------------------------------------------------------


@pytest.fixture
def host_client(host: ModuleType) -> Iterator[TestClient]:
    with TestClient(host.app, base_url="http://127.0.0.1:8005", raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/v1/providers/probe"), ("POST", "/v1/providers/models"), ("GET", "/v1/discover/local")],
)
def test_routes_require_the_management_token(host_client: TestClient, method: str, path: str) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {MANAGEMENT_TOKEN}"}):
        assert host_client.request(method, path, json={}, headers=headers).status_code == 401


def test_the_host_service_probes_with_the_stored_key(
    host_client: TestClient, host: ModuleType, fake: FakeProvider
) -> None:
    host._store.put(REF, SecretRecord(key=KEY, origin=fake.url))
    fake.routes["GET /v1/models"] = models_reply("gpt-4o-mini")
    response = host_client.post("/v1/providers/probe", json=target(fake.url, secret_ref=REF), headers=AUTH)
    assert response.status_code == 200 and response.json()["ok"] is True
    assert fake.seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in response.text and response.headers["cache-control"] == "no-store"
    blocked = host_client.post("/v1/providers/probe", json=target(fake.url, allow_local=False), headers=AUTH)
    assert blocked.json()["cause"] == "address_not_allowed" and len(fake.seen) == 1


def test_invalid_bodies_are_422_without_echoing_the_input(host_client: TestClient) -> None:
    secret = "do-not-echo-" + KEY
    for body in ({"kind": secret}, {**target("http://127.0.0.1:1"), "extra": secret}, {"transport": "ftp"}):
        response = host_client.post("/v1/providers/probe", json=body, headers=AUTH)
        assert response.status_code == 422 and secret not in response.text
    too_big = host_client.post("/v1/providers/probe", content=b"x" * 20000, headers=AUTH)
    assert too_big.status_code == 413
