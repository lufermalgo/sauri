"""Gateway lifecycle with a real synthetic llama-server subprocess, no model or private data."""

import asyncio
import importlib.util
import json
import os
import socket
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest


@pytest.fixture
async def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[ModuleType]:
    engine_dir = Path(__file__).parents[2] / "llm-engine"
    monkeypatch.syspath_prepend(str(engine_dir))
    spec = importlib.util.spec_from_file_location("sauri_test_llm_native", engine_dir / "native_main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token = tmp_path / "token"
    token.write_text("synthetic-token")
    monkeypatch.setattr(module, "ENGINE_TOKEN_PATH", token)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    fake = tmp_path / "llama-server"
    fake.write_text(f"""#!{sys.executable}
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
assert sys.argv[sys.argv.index('-c') + 1] == '32768'
assert sys.argv[sys.argv.index('--reasoning-budget') + 1] == '0'
assert '--no-context-shift' in sys.argv
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{{}}')
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.path == '/v1/chat/completions'
        assert 'Authorization' not in self.headers
        assert body['reasoning_budget'] == 0
        assert body['chat_template_kwargs']['enable_thinking'] is False
        if body.get('model') == 'context-error':
            self.send_response(400); self.end_headers()
            self.wfile.write(b'{{"error": {{"type": "exceed_context_size_error"}}}}'); return
        time.sleep(0.12)
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({{'choices': [{{'message': {{'content': json.dumps(body)}}}}]}}).encode())
HTTPServer(('127.0.0.1', {port}), Handler).serve_forever()
""")
    fake.chmod(0o700)
    module.server.binary = fake
    module.server.url = f"http://127.0.0.1:{port}"
    module.server.idle_seconds = 0.08
    module.server.startup_seconds = 3
    async with module.lifespan(module.app):
        yield module


async def test_lazy_start_auth_idle_stop_and_restart(native: ModuleType) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert native.server.process is None
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            assert (await client.post("/v1/chat/completions", json={}, headers=headers)).status_code == 401
        assert native.server.process is None
        body = {"model": "synthetic", "messages": [{"role": "user", "content": "synthetic"}]}
        response = await client.post(
            "/v1/chat/completions", json=body, headers={"Authorization": "Bearer synthetic-token"}
        )
        assert response.status_code == 200
        forwarded = json.loads(response.json()["choices"][0]["message"]["content"])
        assert forwarded["messages"] == body["messages"]
        process = native.server.process
        assert process and process.returncode is None
        assert os.getpgid(process.pid) == process.pid
        async with asyncio.timeout(3):
            while native.server.process is not None:
                await asyncio.sleep(0.02)
        assert process.returncode is not None
        assert (
            await client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer synthetic-token"})
        ).status_code == 200
        assert native.server.process.pid != process.pid


async def test_context_overflow_is_categorized_not_truncated(native: ModuleType) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions", json={"model": "context-error"}, headers={"Authorization": "Bearer synthetic-token"}
        )
    assert response.status_code == 400 and response.json()["detail"] == "context_exceeded"


async def test_shutdown_reaps_child_and_missing_binary_is_sanitized(native: ModuleType) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions", json={}, headers={"Authorization": "Bearer synthetic-token"}
        )
        assert response.status_code == 200
        process = native.server.process
        await native.server.stop()
        assert process.returncode is not None
        native.server.binary = Path("/nonexistent/private-model-path")
        response = await client.post(
            "/v1/chat/completions", json={}, headers={"Authorization": "Bearer synthetic-token"}
        )
        assert response.status_code == 503
        assert "private-model-path" not in response.text
        assert native.server.process is None


def test_keep_awake_process_lives_only_inside_context(native: ModuleType) -> None:
    with native.KeepAwake() as awake:
        process = awake.process
        assert process.poll() is None
    assert process.poll() is not None


async def test_cancelled_request_reaps_child_and_keep_awake(
    native: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes = []
    original = native.KeepAwake

    @contextmanager
    def tracked_awake() -> Iterator[Any]:
        with original() as awake:
            processes.append(awake.process)
            yield awake

    monkeypatch.setattr(native, "KeepAwake", tracked_awake)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        task = asyncio.create_task(
            client.post("/v1/chat/completions", json={}, headers={"Authorization": "Bearer synthetic-token"})
        )
        async with asyncio.timeout(3):
            while native.server.process is None:
                await asyncio.sleep(0.005)
        child = native.server.process
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert child.returncode is not None and native.server.process is None
        assert processes and all(p.poll() is not None for p in processes)


async def test_startup_timeout_reaps_unready_child(native: ModuleType, tmp_path: Path) -> None:
    fake = tmp_path / "unready-server"
    fake.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    fake.chmod(0o700)
    native.server.binary = fake
    native.server.startup_seconds = 0.05
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions", json={}, headers={"Authorization": "Bearer synthetic-token"}
        )
    assert response.status_code == 503
    assert native.server.process is None


async def test_occupied_port_never_launches_or_uses_unrelated_server(
    native: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    port = httpx.URL(native.server.url).port
    occupied = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        "import socket,sys,time; s=socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1]))); "
        "s.listen(); print('ready', flush=True); time.sleep(30)", str(port), stdout=asyncio.subprocess.PIPE,
    )
    try:
        assert occupied.stdout is not None
        assert await asyncio.wait_for(occupied.stdout.readline(), 3) == b"ready\n"
        spawn = AsyncMock(side_effect=AssertionError("An occupied port must not launch a model server"))
        monkeypatch.setattr(native.asyncio, "create_subprocess_exec", spawn)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
            response = await client.post("/v1/chat/completions", json={},
                                         headers={"Authorization": "Bearer synthetic-token"})
        assert response.status_code == 503 and response.json()["detail"] == "llm_port_busy"
        spawn.assert_not_awaited()
        assert native.server.process is None and occupied.returncode is None
    finally:
        occupied.terminate()
        await occupied.wait()


async def test_health_success_from_dead_child_is_rejected(native: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    process = SimpleNamespace(returncode=None)
    monkeypatch.setattr(native.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))

    def respond(request: httpx.Request) -> httpx.Response:
        process.returncode = 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        try:
            with pytest.raises(RuntimeError, match="llama_start_failed"):
                await native.server.start(client)
        finally:
            native.server.process = None  # This test uses no actual child PID.


async def test_stop_kills_process_group_including_helpers(native: ModuleType, tmp_path: Path) -> None:
    import signal

    fake = tmp_path / "llama-with-helper"
    fake.write_text(f"""#!{sys.executable}
import os, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
def stop(*args):
    child.wait(timeout=3)
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
print(child.pid, flush=True)
while True: time.sleep(1)
""")
    fake.chmod(0o700)
    process = await asyncio.create_subprocess_exec(str(fake), start_new_session=True, stdout=asyncio.subprocess.PIPE)
    assert process.stdout is not None
    child_pid = int(await asyncio.wait_for(process.stdout.readline(), 3))
    native.server.process = process
    try:
        await native.server.stop()
        assert process.returncode == 0  # Parent reaped its helper following group TERM.
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        for pid in (process.pid, child_pid):
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def test_llama_port_comes_from_the_desktop_block(native: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAURI_LLAMA_PORT", raising=False)
    assert native.LlamaServer().url == "http://127.0.0.1:8004"
    monkeypatch.setenv("SAURI_LLAMA_PORT", "41754")
    assert native.LlamaServer().url == "http://127.0.0.1:41754"
    for invalid in ("80", "port", "70000"):
        monkeypatch.setenv("SAURI_LLAMA_PORT", invalid)
        with pytest.raises(ValueError, match="SAURI_LLAMA_PORT"):
            native.LlamaServer()


def test_single_budget_covers_gateway_cold_start(
    native: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.summaries.factory import create_summarization_engine

    token = tmp_path / "engine-token"
    token.write_text("synthetic-budget-token")
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(token))
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost:8003/v1")
    monkeypatch.setenv("SUMMARIZATION_TIMEOUT_SECONDS", "240.5")
    gateway = native.LlamaServer()
    client = create_summarization_engine()
    assert gateway.request_seconds == 240.5
    assert gateway.startup_seconds == 120
    assert client.timeout_seconds == gateway.startup_seconds + gateway.request_seconds + 5
