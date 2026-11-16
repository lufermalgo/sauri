"""Authenticated local chat gateway with lazy, idle-released llama.cpp inference."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
import os
import secrets
import signal
import socket
import time
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Final

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sauri_engine_common.chatgpt_login import ALLOWED_HOSTS, ChatGptLogin
from sauri_engine_common.external import chat_anthropic, chat_openai, chat_responses
from sauri_engine_common.external.allowlist_http import AllowlistedHttp
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.safe_http import SafeHttp
from sauri_engine_common.keep_awake import KeepAwake, KeepAwakeError
from sauri_engine_common.local_model_use import LocalModelError, LocalSelection, select_local_model
from sauri_engine_common.offered_providers import LOCAL_SERVER_KINDS, OfferedMatrix
from sauri_engine_common.route import LOCAL_KIND, ROUTE_HEADER, Route, RouteError, decode_route, validate_route
from sauri_engine_common.secrets import SecretError, SecretRecord, SecretStore, default_secret_store

logger = logging.getLogger("sauri.llm_engine")

INSTALL_DIR = Path.home() / ".local/share/sauri/native-engines/llm"
ENGINE_TOKEN_PATH = Path(os.getenv("SAURI_ENGINE_TOKEN_FILE", Path.home() / ".config/sauri/engine_token"))
_bearer_dependency = Depends(HTTPBearer(auto_error=False))
DEFAULT_ALIAS = "qwen3.5-9b"
# Routes this gateway serves besides the local model: the summary process (``chat`` is reserved and never offered).
EXTERNAL_CAPABILITIES: Final = frozenset({"summary", "chat"})
# How often the handler asks whether the caller is still there; a cancelled call must close the provider stream
# well inside the 2 s the design allows (Property 12).
DISCONNECT_POLL_S: Final = 0.5
# HTTP status per classified error. 401 is reserved for the engine token, so a provider rejecting the key is a 502.
ERROR_STATUS: Final = {
    "provider_bad_request": 400,
    "provider_context_exceeded": 400,
    "provider_unsupported": 400,
    "consent_missing": 403,
    "origin_mismatch": 403,
    "audio_too_large": 413,
    "provider_rate_limited": 429,
    "provider_timeout": 504,
    "secret_unavailable": 503,
}
DEFAULT_ERROR_STATUS: Final = 502


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
        self.request_seconds = float(os.getenv("SUMMARIZATION_TIMEOUT_SECONDS", "1500"))
        if not math.isfinite(self.request_seconds) or self.request_seconds <= 0:
            raise ValueError("SUMMARIZATION_TIMEOUT_SECONDS must be finite and positive")
        self.process: asyncio.subprocess.Process | None = None
        self.loaded_model: Path | None = None  # file the running llama-server was started with
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
        self.loaded_model = None

    async def start(self, client: httpx.AsyncClient, selection: LocalSelection | None = None) -> None:
        """Start llama-server with the chosen model, restarting it when a different one is running.

        No selection means the built-in model and alias, exactly as before the local route existed.
        """
        model = self.model if selection is None else selection.path
        alias = DEFAULT_ALIAS if selection is None else selection.model_id
        if self.process is not None and self.process.returncode is None and self.loaded_model == model:
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
            str(self.binary), "-m", str(model), "-c", "32768", "-ctk", "q8_0", "-ctv", "q8_0",
            "--host", "127.0.0.1", "--port", str(port), "--parallel", "1", "--alias", alias,
            "--reasoning-budget", "0", "--no-context-shift",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        self.loaded_model = model
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

    async def chat(self, body: dict[str, Any], selection: LocalSelection | None = None) -> dict[str, Any]:
        if body.get("stream"):
            raise HTTPException(status_code=422, detail="streaming_not_supported")
        # Serializing requests also prevents the idle reaper from stopping active inference.
        async with self.lock:
            try:
                with KeepAwake():
                    async with httpx.AsyncClient(timeout=self.request_seconds, trust_env=False) as client:
                        async with asyncio.timeout(self.startup_seconds + self.request_seconds):
                            await self.start(client, selection)
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


external_http = SafeHttp()
_secret_store: SecretStore | None = None


@app.exception_handler(ProviderError)
async def provider_error_response(_request: Request, error: ProviderError) -> JSONResponse:
    """``{"error": {"code", "retryable", "retry_after_s"}}``; only the closed code and sub-code are ever logged."""
    logger.warning("external_chat_failed code=%s reason=%s", error.code, error.reason)
    headers = {"Retry-After": str(error.retry_after_s)} if error.retry_after_s is not None else None
    return JSONResponse(
        status_code=ERROR_STATUS.get(error.code, DEFAULT_ERROR_STATUS), content=error.to_payload(), headers=headers
    )


def _external_route(header: str | None) -> Route | None:
    """The decoded route when it names an external provider; ``None`` leaves the request to the local path.

    A malformed header also stays on the local path, which refuses it with its own stable code.
    """
    try:
        route = decode_route(header)
    except RouteError:
        return None
    return None if route is None or route.kind == LOCAL_KIND else route


async def _store() -> SecretStore:
    global _secret_store
    # Both the store probe and the Keychain read run ``/usr/bin/security``: keep them off the event loop.
    if _secret_store is None:
        _secret_store = await asyncio.to_thread(default_secret_store)
    return _secret_store


async def _read_secret(ref: str) -> SecretRecord:
    try:
        return await asyncio.to_thread((await _store()).get, ref)
    except SecretError:
        raise ProviderError("secret_unavailable") from None


# The account sign-in of the ChatGPT plan: tokens come from the secret store at call time, never from the route.
chatgpt_http = AllowlistedHttp(ALLOWED_HOSTS)
_chatgpt_login: ChatGptLogin | None = None


async def _chatgpt() -> ChatGptLogin:
    global _chatgpt_login
    if _chatgpt_login is None:
        _chatgpt_login = ChatGptLogin(await _store(), chatgpt_http)
    return _chatgpt_login


async def _external_secret(route: Route) -> SecretRecord | None:
    """Validate the route, then read its key; nothing is read for a route that is refused anyway."""
    if route.capability not in EXTERNAL_CAPABILITIES:
        raise ProviderError("provider_unsupported", reason="capability_mismatch")
    matrix = OfferedMatrix()
    # Matrix, consent and URL first, without a secret: a refused route never touches the Keychain.
    validate_route(dataclasses.replace(route, secret_ref=None), matrix, None)
    secret = await _read_secret(route.secret_ref) if route.secret_ref is not None else None
    validate_route(route, matrix, secret)  # the key is bound to this URL's origin
    return secret


async def _watch_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(DISCONNECT_POLL_S)


async def _run_until_disconnect(request: Request, call: Any) -> dict[str, Any] | None:
    """Await ``call``; ``None`` when the caller left first, after the call (and its provider stream) was closed."""
    work = asyncio.ensure_future(call)
    watcher = asyncio.create_task(_watch_disconnect(request))
    try:
        await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if work.done():
            result: dict[str, Any] = work.result()
            return result
        return None
    finally:
        for task in (work, watcher):
            task.cancel()
        # Wait for the cancellation to finish: the adapter closes the upstream connection while unwinding.
        await asyncio.gather(work, watcher, return_exceptions=True)


async def _external_chat(request: Request, body: dict[str, Any], route: Route) -> Response:
    if body.get("stream"):
        raise ProviderError("provider_bad_request", reason="streaming_not_supported")
    secret = await _external_secret(route)
    adapter = {"openai-chat": chat_openai, "anthropic-messages": chat_anthropic}.get(route.transport or "")
    if adapter is None and route.transport != "chatgpt-responses":  # unreachable while the matrix agrees; fail closed
        raise ProviderError("provider_unsupported", reason="no_adapter")
    # The route's budget never outlives this gateway's own request budget (the worker waits that long).
    timeouts = dataclasses.replace(route.timeouts, total_s=min(route.timeouts.total_s, server.request_seconds))
    # Not under ``server.lock``: an external call must not wait for, or block, local generation.
    with ExitStack() as stack:
        with suppress(KeepAwakeError):
            stack.enter_context(KeepAwake())
        # Citations and the original schema are checked by the worker, which owns the passages (U3.3).
        if adapter is None:
            call = chat_responses.complete(
                body, route=route, login=await _chatgpt(), http=chatgpt_http, timeouts=timeouts
            )
        else:
            call = adapter.complete(
                body, route=route, secret=secret, http=external_http,
                allow_local=route.kind in LOCAL_SERVER_KINDS, timeouts=timeouts,
            )
        result = await _run_until_disconnect(request, call)
    if result is None:
        return Response(status_code=499)  # nobody is listening any more
    return JSONResponse(result)


@app.post("/v1/chat/completions", dependencies=[Depends(require_engine_token)], response_model=None)
async def chat_completions(
    request: Request,
    body: dict[str, Any],
    route: str | None = Header(default=None, alias=ROUTE_HEADER),
) -> Response | dict[str, Any]:
    external = _external_route(route)
    if external is not None:
        return await _external_chat(request, body, external)
    # Resolved before the lock: a bad or uninstalled model is refused without touching the running server.
    try:
        selection = await asyncio.to_thread(
            select_local_model, route, process="summary", legacy_default=server.model
        )
    except LocalModelError as error:
        raise HTTPException(status_code=error.status, detail=error.code) from None
    return await server.chat(body, selection)
