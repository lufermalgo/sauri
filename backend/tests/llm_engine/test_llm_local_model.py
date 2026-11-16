"""The LLM gateway runs the model a ``local:<id>`` route names, restarting llama-server when it changes.

A fake ``llama-server`` executable records how it was started and echoes its model and alias; no real
model or binary is involved. The opt-in check against the installed binaries and models
(``SAURI_RUN_NATIVE_TESTS=1``) lives in ``tests/native/test_local_model_native.py``.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from tests.local_models_support import BIG, SMALL, catalog_entry, install_model, route_header, write_catalog

AUTH = {"Authorization": "Bearer synthetic-token"}
BODY = {"model": "ignored", "messages": [{"role": "user", "content": "synthetic"}]}
DEFAULT = catalog_entry("llm-big", "summary", "big.gguf", BIG, default=True, rank=2)
SMALLER = catalog_entry("llm-small", "summary", "small.gguf", SMALL)


@dataclass
class Gateway:
    module: ModuleType
    client: httpx.AsyncClient
    models: Path
    legacy: Path
    starts: Path

    def started(self) -> list[dict[str, str]]:
        """One record per llama-server start: its model path and alias."""
        if not self.starts.exists():
            return []
        return [json.loads(line) for line in self.starts.read_text().splitlines()]

    async def chat(self, route: str | None) -> httpx.Response:
        headers = {**AUTH, **({"X-Sauri-Route": route} if route else {})}
        return await self.client.post("/v1/chat/completions", json=BODY, headers=headers)


@pytest.fixture
async def gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Gateway]:
    engine_dir = Path(__file__).parents[2] / "llm-engine"
    monkeypatch.syspath_prepend(str(engine_dir))
    spec = importlib.util.spec_from_file_location("sauri_test_llm_local_model", engine_dir / "native_main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token = tmp_path / "token"
    token.write_text("synthetic-token")
    monkeypatch.setattr(module, "ENGINE_TOKEN_PATH", token)
    models = tmp_path / "models"
    legacy = tmp_path / "legacy" / "Qwen-legacy.gguf"
    legacy.parent.mkdir()
    legacy.write_bytes(BIG)
    monkeypatch.setenv("SAURI_MODELS_DIR", str(models))
    monkeypatch.setenv("SAURI_MODEL_CATALOG", str(write_catalog(tmp_path / "catalog.json", [DEFAULT, SMALLER])))
    with socket.socket() as sock:  # a random free port: the owner's engines keep 8001-8005
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    starts = tmp_path / "starts.jsonl"
    fake = tmp_path / "llama-server"
    fake.write_text(f"""#!{sys.executable}
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
argv = sys.argv
record = {{"model": argv[argv.index('-m') + 1], "alias": argv[argv.index('--alias') + 1]}}
with open({str(starts)!r}, 'a') as log:
    log.write(json.dumps(record) + '\\n')
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{{}}')
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({{'choices': [{{'message': {{'content': json.dumps(record)}}}}]}}).encode())
HTTPServer(('127.0.0.1', int(argv[argv.index('--port') + 1])), Handler).serve_forever()
""")
    fake.chmod(0o700)
    module.server.binary = fake
    module.server.model = legacy
    module.server.url = f"http://127.0.0.1:{port}"
    module.server.idle_seconds = 60  # the reaper must not stop the server between the requests of a test
    module.server.startup_seconds = 5
    transport = httpx.ASGITransport(app=module.app)
    async with module.lifespan(module.app), httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Gateway(module, client, models, legacy, starts)


def served(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    result: dict[str, Any] = json.loads(response.json()["choices"][0]["message"]["content"])
    return result


async def test_no_header_keeps_the_built_in_model_and_never_restarts(gateway: Gateway) -> None:
    for _ in range(2):
        assert served(await gateway.chat(None)) == {"model": str(gateway.legacy), "alias": "qwen3.5-9b"}
    assert served(await gateway.chat(route_header("local:default"))) == {
        "model": str(gateway.legacy), "alias": "qwen3.5-9b",
    }
    assert len(gateway.started()) == 1


async def test_model_switch_between_two_requests_restarts_with_the_new_file_and_alias(gateway: Gateway) -> None:
    small = install_model(gateway.models, SMALLER, SMALL)
    big = install_model(gateway.models, DEFAULT, BIG)
    first = gateway.module.server.process
    assert served(await gateway.chat(route_header("local:llm-small"))) == {"model": str(small), "alias": "llm-small"}
    second = gateway.module.server.process
    assert served(await gateway.chat(route_header("local:llm-big"))) == {"model": str(big), "alias": "llm-big"}
    third = gateway.module.server.process
    assert first is None and second is not None and second.returncode is not None  # the first server was stopped
    assert third is not second
    # The same model again keeps the running server.
    assert served(await gateway.chat(route_header("local:llm-big")))["model"] == str(big)
    assert gateway.module.server.process is third
    # Back to the built-in model without a header: the server restarts with the original file and alias.
    assert served(await gateway.chat(None)) == {"model": str(gateway.legacy), "alias": "qwen3.5-9b"}
    assert [(item["alias"]) for item in gateway.started()] == ["llm-small", "llm-big", "qwen3.5-9b"]


async def test_model_not_installed_is_refused_without_touching_the_running_server(gateway: Gateway) -> None:
    assert served(await gateway.chat(None))["alias"] == "qwen3.5-9b"
    running = gateway.module.server.process
    response = await gateway.chat(route_header("local:llm-small"))
    assert response.status_code == 409 and response.json() == {"detail": "model_not_installed"}
    assert gateway.module.server.process is running and running is not None and running.returncode is None
    assert len(gateway.started()) == 1


async def test_a_model_changed_after_install_is_refused(gateway: Gateway) -> None:
    final = install_model(gateway.models, SMALLER, SMALL)
    final.write_bytes(SMALL + b"changed")
    response = await gateway.chat(route_header("local:llm-small"))
    assert response.status_code == 409 and response.json() == {"detail": "model_not_verified"}
    assert gateway.module.server.process is None and gateway.started() == []


async def test_default_model_in_the_legacy_location_is_accepted_by_its_catalog_id(gateway: Gateway) -> None:
    # Nothing in the models directory: the catalog default is the engine's legacy file (same size).
    assert served(await gateway.chat(route_header("local:llm-big"))) == {
        "model": str(gateway.legacy), "alias": "llm-big",
    }
    # The same file as the built-in: no restart.
    assert served(await gateway.chat(None))["model"] == str(gateway.legacy)
    assert len(gateway.started()) == 1
    # The legacy file is left exactly where it was.
    assert gateway.legacy.read_bytes() == BIG


@pytest.mark.parametrize(
    ("route", "status", "code"),
    [
        ("not-a-route", 422, "route_malformed"),
        (route_header("local:unknown-model"), 422, "unknown_model"),
        (route_header("local:llm-big", process="transcription"), 422, "route_capability_mismatch"),
    ],
)
async def test_invalid_routes_are_refused_before_any_server_starts(
    gateway: Gateway, route: str, status: int, code: str
) -> None:
    response = await gateway.chat(route)
    assert response.status_code == status and response.json() == {"detail": code}
    assert gateway.module.server.process is None


async def test_route_requires_the_engine_token(gateway: Gateway) -> None:
    response = await gateway.client.post(
        "/v1/chat/completions", json=BODY, headers={"X-Sauri-Route": route_header("local:llm-small")}
    )
    assert response.status_code == 401
    assert gateway.module.server.process is None
