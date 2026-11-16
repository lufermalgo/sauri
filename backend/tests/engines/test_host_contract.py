"""The API's host client against the real host-engine application (ASGI, in process).

Only a closed loopback port is ever contacted, so no provider and no real key store is involved: the
secrets live in a temporary directory. This pins the request and response shapes both sides agree on.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from httpx import ASGITransport

from app.engines import service
from app.engines.host_client import HostClient, HostRejectedError
from tests.host_engine.conftest import MANAGEMENT_TOKEN, load_host_module


@pytest.fixture
def real_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[HostClient, ModuleType]]:
    token_file = tmp_path / "management_token"
    token_file.write_text(MANAGEMENT_TOKEN + "\n")
    token_file.chmod(0o600)
    module = load_host_module(token_file, tmp_path / "secrets")
    monkeypatch.setenv("MANAGEMENT_TOKEN_FILE", str(token_file))
    yield HostClient("http://host.test", transport=ASGITransport(app=module.app)), module


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def test_secret_round_trip_through_the_real_host(
    real_host: tuple[HostClient, ModuleType], tmp_path: Path
) -> None:
    client, _module = real_host
    ref = "sauri/00000000-0000-4000-8000-00000000000a/00000000-0000-4000-8000-00000000000b"
    key = "synthetic-provider-key-0123456789"
    assert await client.put_secret(ref, key, "https://api.example.com") == key[-4:]
    assert await client.put_secret(ref, "short", "https://api.example.com") is None  # replaced, no hint
    await client.delete_secret(ref)
    await client.delete_secret(ref)  # deleting twice is not an error
    assert not any(path.is_file() and key in path.read_text() for path in tmp_path.rglob("*"))


async def test_invalid_secret_requests_are_rejected_by_the_real_host(real_host: tuple[HostClient, ModuleType]) -> None:
    client, _module = real_host
    with pytest.raises(HostRejectedError) as raised:
        await client.put_secret("sauri/o/p", "k" * 20, "not a url")
    assert raised.value.status == 422


async def test_status_has_the_shape_the_api_reads(real_host: tuple[HostClient, ModuleType]) -> None:
    client, _module = real_host
    raw = await client.engines_status()
    assert {engine["id"] for engine in raw["engines"]} == {"asr", "diar", "llm", "host"}
    assert all(isinstance(engine["port"], int) and isinstance(engine["state"], str) for engine in raw["engines"])
    assert isinstance(raw["secret_store"], str)


async def test_probe_and_models_payloads_are_accepted_and_answers_are_classified(
    real_host: tuple[HostClient, ModuleType],
) -> None:
    client, _module = real_host
    base = f"http://127.0.0.1:{_closed_port()}/v1"
    probe_payload = {
        "kind": "ollama",
        "transport": "openai-chat",
        "base_url": base,
        "capability": "summary",
        "allow_local": True,
    }
    probe = await client.probe(probe_payload)
    assert probe["ok"] is False and probe["error_class"] == "provider_unavailable"
    assert isinstance(probe["latency_ms"], int)
    with pytest.raises(HostRejectedError) as raised:
        await client.models({**probe_payload, "refresh": False})
    assert (raised.value.status, raised.value.code) == (502, "provider_unavailable")
    # Without the local-app flag the host refuses a loopback target outright.
    refused = await client.probe({**probe_payload, "allow_local": False})
    assert refused["ok"] is False and refused["error_class"] == "provider_bad_request"


async def test_the_unknown_payload_fields_the_api_must_not_send_are_refused(
    real_host: tuple[HostClient, ModuleType],
) -> None:
    client, _module = real_host
    with pytest.raises(HostRejectedError) as raised:
        await client.probe({"kind": "ollama", "transport": "openai-chat", "base_url": "http://127.0.0.1:9", "key": "x"})
    assert raised.value.status == 422


async def test_api_service_maps_the_real_status_answer(real_host: tuple[HostClient, ModuleType]) -> None:
    client, _module = real_host
    out = await service.get_status(client)
    assert {engine.id for engine in out.engines} == {"asr", "diar", "llm", "host"}
    assert out.secret_store is not None
