"""Local administration service for the host: provider secrets and engine status.

Listens on 127.0.0.1 only and authenticates every call with a management token that the engine
gateways and the worker never receive. No route returns a secret; request bodies of secret writes are
never logged. Responses and errors carry class codes, never values.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from local_models import adopt_on_startup
from local_models import router as local_models_router
from providers import build_router
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sauri_engine_common.route import RouteError, origin_of
from sauri_engine_common.secrets import (
    SecretError,
    SecretRecord,
    SecretStore,
    default_secret_store,
    key_hint,
    validate_ref,
)
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

VERSION: Final = "1.0.0"
MAX_BODY_BYTES: Final = 32 * 1024
# Sized so a record always fits the Keychain command line (see MAX_KEYCHAIN_COMMAND_CHARS) and both
# stores accept exactly the same inputs.
MAX_KEY_CHARS: Final = 2048
MAX_ORIGIN_CHARS: Final = 256
MANAGEMENT_TOKEN_PATH = Path(
    os.getenv("SAURI_MANAGEMENT_TOKEN_FILE", Path.home() / ".config" / "sauri" / "management_token")
)
# (id, port) of the host processes this service reports on; the gateways answer /health unauthenticated.
ENGINES: tuple[tuple[str, int], ...] = (("asr", 8001), ("diar", 8002), ("llm", 8003), ("host", 8005))
PROBE_TIMEOUT_S: Final = 1.0
# Recognize models installed by hand when the service starts (tests turn it off: they never touch real files).
ADOPT_ON_START = os.getenv("SAURI_ADOPT_ON_START", "1") != "0"

logger = logging.getLogger("sauri.host_engine")
_bearer_dependency = Depends(HTTPBearer(auto_error=False))
_store: SecretStore | None = None
_store_lock = asyncio.Lock()


def require_management_token(credentials: HTTPAuthorizationCredentials | None = _bearer_dependency) -> None:
    """Constant-time check against the management token; 503 when the token file is unavailable."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})
    try:
        expected = MANAGEMENT_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise HTTPException(status_code=503, detail="management_auth_unavailable") from None
    if not expected:
        raise HTTPException(status_code=503, detail="management_auth_unavailable")
    if not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthorized", headers={"WWW-Authenticate": "Bearer"})


class PutSecretBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=MAX_KEY_CHARS)
    origin: str = Field(min_length=1, max_length=MAX_ORIGIN_CHARS)


async def get_store() -> SecretStore:
    global _store
    if _store is None:
        async with _store_lock:
            if _store is None:
                _store = await asyncio.to_thread(default_secret_store)
    return _store


def _error(status: int, code: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code}}, headers=headers)


class HardenedMiddleware:
    """Adds no-store headers and turns any unhandled error into a bare 500.

    The server's default handler logs the exception text, which could in principle carry request
    data; here only the exception class name is logged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        try:
            await self.app(scope, receive, guarded_send)
        except Exception as exc:
            logger.error("unhandled_error type=%s", type(exc).__name__)
            if not started:
                await _error(500, "internal_error")(scope, receive, guarded_send)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if ADOPT_ON_START:
        await adopt_on_startup()
    yield


app = FastAPI(title="Sauri Host Engine", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(HardenedMiddleware)
app.include_router(local_models_router, dependencies=[Depends(require_management_token)])


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, str(exc.detail))
    return _error(exc.status_code, code, dict(exc.headers) if exc.headers else None)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    # The default body echoes the rejected input; never return it.
    return _error(422, "invalid_request")


async def _read_limited_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
        raise HTTPException(status_code=413, detail="payload_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="payload_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _valid_ref(ref: str) -> str:
    try:
        return validate_ref(ref)
    except SecretError:
        raise HTTPException(status_code=422, detail="invalid_secret_ref") from None


def _secret_failure(exc: SecretError) -> HTTPException:
    status = 422 if exc.code in ("invalid_secret", "invalid_secret_ref", "secret_too_large") else 503
    return HTTPException(status_code=status, detail=exc.code)


@app.get("/health", dependencies=[Depends(require_management_token)])
async def health() -> dict[str, str]:
    store = await get_store()
    return {"status": "ok", "version": VERSION, "secret_store": store.name}


@app.put("/v1/secrets/{ref:path}", dependencies=[Depends(require_management_token)])
async def put_secret(ref: str, request: Request) -> dict[str, str | None]:
    """Store a key bound to its origin; the response carries only the display hint."""
    ref = _valid_ref(ref)
    if request.url.query:
        raise HTTPException(status_code=422, detail="invalid_request")
    raw = await _read_limited_body(request)
    try:
        body = PutSecretBody.model_validate_json(raw)
        origin = origin_of(body.origin)
    except (ValidationError, RouteError):
        # Neither error text is returned or logged: pydantic messages quote the rejected input.
        raise HTTPException(status_code=422, detail="invalid_request") from None
    store = await get_store()
    try:
        await asyncio.to_thread(store.put, ref, SecretRecord(key=body.key, origin=origin))
    except SecretError as exc:
        raise _secret_failure(exc) from None
    return {"key_hint": key_hint(body.key)}


@app.delete("/v1/secrets/{ref:path}", status_code=204, dependencies=[Depends(require_management_token)])
async def delete_secret(ref: str) -> Response:
    ref = _valid_ref(ref)
    store = await get_store()
    try:
        await asyncio.to_thread(store.delete, ref)
    except SecretError as exc:
        raise _secret_failure(exc) from None
    return Response(status_code=204)


async def _engine_state(engine_id: str, port: int, client: httpx.AsyncClient) -> dict[str, Any]:
    if engine_id == "host":
        return {"id": engine_id, "port": port, "state": "running"}
    try:
        response = await client.get(f"http://127.0.0.1:{port}/health")
    except httpx.HTTPError:
        return {"id": engine_id, "port": port, "state": "stopped"}
    return {"id": engine_id, "port": port, "state": "running" if response.status_code == 200 else "unhealthy"}


@app.get("/v1/engines/status", dependencies=[Depends(require_management_token)])
async def engines_status() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S, trust_env=False) as client:
        engines = await asyncio.gather(*(_engine_state(engine_id, port, client) for engine_id, port in ENGINES))
    store = await get_store()
    return {"engines": list(engines), "secret_store": store.name}


app.include_router(build_router(get_store, require_management_token))
