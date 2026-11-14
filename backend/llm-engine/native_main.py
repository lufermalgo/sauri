"""Authenticated local chat gateway with lazy, idle-released llama.cpp inference."""

from __future__ import annotations

import asyncio
import math
import os
import secrets
import signal
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
    from sauri_engine_common.keep_awake import KeepAwake
except ModuleNotFoundError:
    from keep_awake import KeepAwake

INSTALL_DIR = Path.home() / ".local/share/sauri/native-engines/llm"
ENGINE_TOKEN_PATH = Path(os.getenv("SAURI_ENGINE_TOKEN_FILE", Path.home() / ".config/sauri/engine_token"))
_bearer_dependency = Depends(HTTPBearer(auto_error=False))


def require_engine_token(credentials: HTTPAuthorizationCredentials | None = _bearer_dependency) -> None:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        expected = ENGINE_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise HTTPException(status_code=503, detail="Engine authentication unavailable") from None
    if not expected:
        raise HTTPException(status_code=503, detail="Engine authentication unavailable")
    if not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


class LlamaServer:
    def __init__(self) -> None:
        self.binary = Path(os.getenv("SAURI_LLAMA_SERVER", INSTALL_DIR / "bin/llama-server"))
        self.model = Path(os.getenv("SAURI_LLM_MODEL_FILE", INSTALL_DIR / "models/Qwen3.5-9B-Q4_K_M.gguf"))
        self.url = "http://127.0.0.1:8004"
        self.idle_seconds = 120.0
        self.startup_seconds = 120.0
        self.request_seconds = float(os.getenv("SUMMARIZATION_TIMEOUT_SECONDS", "900"))
        if not math.isfinite(self.request_seconds) or self.request_seconds <= 0:
            raise ValueError("SUMMARIZATION_TIMEOUT_SECONDS must be finite and positive")
        self.process: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.last_used = time.monotonic()

    async def stop(self) -> None:
        process = self.process
        if process is None:
            return
        # The child owns a session/process group. Signal that group even if its
        # leader has already exited, so helpers cannot survive the model server.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            pass
        finally:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        self.process = None

    async def start(self, client: httpx.AsyncClient) -> None:
        if self.process is not None and self.process.returncode is None:
            return
        await self.stop()
        port = httpx.URL(self.url).port or 8004
        # Fail before spawning or probing HTTP: an occupied port may belong to an
        # unrelated service that also returns 200 from /health.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise HTTPException(status_code=503, detail="llm_port_busy") from None
        self.process = await asyncio.create_subprocess_exec(
            str(self.binary), "-m", str(self.model), "-c", "32768", "-ctk", "q8_0", "-ctv", "q8_0",
            "--host", "127.0.0.1", "--port", str(port), "--parallel", "1", "--alias", "qwen3.5-9b",
            "--reasoning-budget", "0", "--no-context-shift",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        # No llama.cpp request/prompt diagnostics are allowed into the gateway log.
        async with asyncio.timeout(self.startup_seconds):
            while True:
                if self.process.returncode is not None:
                    raise RuntimeError("llama_start_failed")
                try:
                    response = await client.get(f"{self.url}/health", timeout=1)
                    if response.status_code == 200:
                        if self.process.returncode is not None:
                            raise RuntimeError("llama_start_failed")
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)

    async def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("stream"):
            raise HTTPException(status_code=422, detail="streaming_not_supported")
        # Serializing requests also prevents the idle reaper from stopping active inference.
        async with self.lock:
            try:
                with KeepAwake():
                    async with httpx.AsyncClient(timeout=self.request_seconds, trust_env=False) as client:
                        async with asyncio.timeout(self.startup_seconds + self.request_seconds):
                            await self.start(client)
                            response = await client.post(f"{self.url}/v1/chat/completions", json={
                                **body, "stream": False, "reasoning_budget": 0,
                                "chat_template_kwargs": {"enable_thinking": False},
                            })
                if response.is_error:
                    if any(marker in response.text.lower() for marker in (
                        "context_exceeded", "context_length_exceeded", "exceed_context_size",
                        "exceeds the available context", "maximum context length",
                    )):
                        raise HTTPException(status_code=400, detail="context_exceeded")
                    raise HTTPException(status_code=502, detail="llama_request_failed")
                result: dict[str, Any] = response.json()
                return result
            except HTTPException:
                raise
            except asyncio.CancelledError:
                await self.stop()
                raise
            except Exception:
                await self.stop()
                raise HTTPException(status_code=503, detail="llama_unavailable") from None
            finally:
                self.last_used = time.monotonic()

    async def reap_idle(self) -> None:
        while True:
            await asyncio.sleep(min(self.idle_seconds, 1.0))
            async with self.lock:
                if time.monotonic() - self.last_used >= self.idle_seconds:
                    await self.stop()


server = LlamaServer()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(server.reap_idle())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        async with server.lock:
            await server.stop()


app = FastAPI(title="Sauri Native LLM Engine", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions", dependencies=[Depends(require_engine_token)])
async def chat_completions(body: dict[str, Any]) -> dict[str, Any]:
    return await server.chat(body)
