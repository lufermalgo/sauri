"""ChatGPT-plan sign-in routes of the host service (device code; see ``sauri_engine_common.chatgpt_login``).

``start`` asks OpenAI for a code, ``poll`` advances a pending sign-in by one check (the portal calls it every few
seconds; it only reaches OpenAI once per interval), ``status`` only reads, ``logout`` forgets the account.
Responses carry the code to type, the verification address and the account label, never a token.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sauri_engine_common.chatgpt_login import ALLOWED_HOSTS, ChatGptLogin
from sauri_engine_common.external.allowlist_http import AllowlistedHttp
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.safe_http import SafeHttp
from sauri_engine_common.secrets import SecretStore

logger = logging.getLogger("sauri.host_engine.chatgpt")

GetLogin = Callable[[], Awaitable[ChatGptLogin]]


def login_getter(get_store: Callable[[], Awaitable[SecretStore]], http: SafeHttp | None = None) -> GetLogin:
    """One ``ChatGptLogin`` per process, built on first use (the secret store is opened lazily)."""
    login: ChatGptLogin | None = None
    guard = asyncio.Lock()

    async def get() -> ChatGptLogin:
        nonlocal login
        if login is None:
            async with guard:
                if login is None:
                    login = ChatGptLogin(await get_store(), http or AllowlistedHttp(ALLOWED_HOSTS))
        return login

    return get


def status_for(exc: ProviderError) -> int:
    # Never 401: the API client reads it as "the management token is wrong".
    if exc.code == "secret_unavailable":
        return 503
    return 429 if exc.code == "provider_rate_limited" else 502


def failure(exc: ProviderError) -> JSONResponse:
    logger.info("chatgpt_login_failed class=%s cause=%s", exc.code, exc.reason)
    error = {"code": exc.code, "retryable": exc.retryable, "retry_after_s": exc.retry_after_s, "cause": exc.reason}
    return JSONResponse(status_code=status_for(exc), content={"error": error})


def build_router(get_login: GetLogin, require_token: Callable[..., None]) -> APIRouter:
    router = APIRouter(prefix="/v1/oauth/chatgpt", dependencies=[Depends(require_token)])

    @router.post("/start", response_model=None)
    async def start() -> dict[str, Any] | JSONResponse:
        try:
            return await (await get_login()).start()
        except ProviderError as exc:
            return failure(exc)

    @router.post("/poll", response_model=None)
    async def poll() -> dict[str, Any] | JSONResponse:
        try:
            return await (await get_login()).poll()
        except ProviderError as exc:
            return failure(exc)

    @router.get("/status", response_model=None)
    async def status() -> dict[str, Any] | JSONResponse:
        try:
            return await (await get_login()).status()
        except ProviderError as exc:
            return failure(exc)

    @router.post("/logout", status_code=204, response_model=None)
    async def logout() -> Response | JSONResponse:
        try:
            await (await get_login()).disconnect()
        except ProviderError as exc:
            return failure(exc)
        return Response(status_code=204)

    return router
