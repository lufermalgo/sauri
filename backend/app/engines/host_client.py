"""Client of the host service (``host-engine``): the only module that holds the management token.

The token is read from the file named by ``MANAGEMENT_TOKEN_FILE`` on every call and sent only to
``HOST_ENGINE_URL``. Keys pass through here in transit when the user saves one; they are never logged,
cached or echoed, and error values carry a class code only.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from app.infra.secrets import SecretUnavailableError, read_secret

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES: Final = 1024 * 1024
SECRET_TIMEOUT_S: Final = 10.0
# Listing the models (up to 10 s) plus the schema check, which asks a model for a small summary (up to 60 s).
PROBE_TIMEOUT_S: Final = 85.0
MODELS_TIMEOUT_S: Final = 45.0
STATUS_TIMEOUT_S: Final = 10.0
LOCAL_TIMEOUT_S: Final = 15.0
# Custom models: the host asks the Hugging Face API (two or more calls of up to 10 s each) before it answers.
CUSTOM_TIMEOUT_S: Final = 30.0
ACCOUNT_TIMEOUT_S: Final = 30.0  # one call to OpenAI plus the keychain
# Same alphabet the host store accepts, but every segment starts with a letter or digit so a reference
# can never climb out of /v1/secrets/ with ".." or "." segments.
SECRET_REF: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*")
MAX_REF_CHARS: Final = 200


class HostError(Exception):
    """A failed call to the host service; ``str(error)`` is the class code only."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HostUnavailableError(HostError):
    """The host service cannot be reached or authenticated against (503 ``host_unavailable``)."""

    def __init__(self) -> None:
        super().__init__("host_unavailable")


class HostRejectedError(HostError):
    """The host service answered with an error status; ``status`` is its HTTP status."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status


def valid_secret_ref(ref: str) -> bool:
    return len(ref) <= MAX_REF_CHARS and SECRET_REF.fullmatch(ref) is not None


def _error_code(response: httpx.Response) -> str:
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return "host_error"
    return code if isinstance(code, str) and 0 < len(code) <= 64 and code.isascii() else "host_error"


class HostClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._transport = transport

    def _url(self) -> str:
        base = self._base_url or os.environ.get("HOST_ENGINE_URL", "")
        parts = urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            logger.error("host_engine_url_invalid")
            raise HostUnavailableError
        return base.rstrip("/")

    def _token(self) -> str:
        try:
            token = read_secret("MANAGEMENT_TOKEN_FILE")
        except SecretUnavailableError:
            token = None
        if not token:
            logger.error("management_token_unavailable")
            raise HostUnavailableError
        return token

    async def _send(
        self, method: str, path: str, *, timeout: float, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        url = self._url() + path
        headers = {"Authorization": f"Bearer {self._token()}"}
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=timeout, follow_redirects=False, trust_env=False
            ) as client:
                return await client.request(method, url, headers=headers, json=json)
        except httpx.HTTPError as exc:
            logger.warning("host_engine_unreachable error=%s", type(exc).__name__)
            raise HostUnavailableError from None

    async def _request(
        self, method: str, path: str, *, timeout: float, json: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        response = await self._send(method, path, timeout=timeout, json=json)
        if response.status_code == 401 or (
            response.status_code == 503 and _error_code(response) != "secret_unavailable"
        ):
            # 401: the token does not match; 503: the host has no token. Both mean "not usable". A 503 that
            # names secret_unavailable is a classified answer (a locked keychain) and is handled as one.
            logger.warning("host_engine_unavailable status=%s", response.status_code)
            raise HostUnavailableError
        if response.status_code >= 400:
            raise HostRejectedError(response.status_code, _error_code(response))
        if response.status_code == 204 or not response.content:
            return None
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise HostUnavailableError
        try:
            body = response.json()
        except ValueError:
            raise HostUnavailableError from None
        if not isinstance(body, dict):
            raise HostUnavailableError
        return body

    async def put_secret(self, ref: str, key: str, origin: str) -> str | None:
        """Store a key bound to ``origin``; returns the display hint (last four, only for long keys)."""
        if not valid_secret_ref(ref):
            raise HostError("invalid_secret_ref")
        body = await self._request(
            "PUT", f"/v1/secrets/{ref}", timeout=SECRET_TIMEOUT_S, json={"key": key, "origin": origin}
        )
        hint = (body or {}).get("key_hint")
        return hint if isinstance(hint, str) and len(hint) == 4 else None

    async def delete_secret(self, ref: str) -> None:
        if not valid_secret_ref(ref):
            raise HostError("invalid_secret_ref")
        await self._request("DELETE", f"/v1/secrets/{ref}", timeout=SECRET_TIMEOUT_S)

    async def probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/v1/providers/probe", timeout=PROBE_TIMEOUT_S, json=payload) or {}

    async def models(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/v1/providers/models", timeout=MODELS_TIMEOUT_S, json=payload) or {}

    async def chatgpt_start(self) -> dict[str, Any]:
        """Ask for a device code. A host refusal (rate limit, store locked) raises ``HostRejectedError``."""
        return await self._request("POST", "/v1/oauth/chatgpt/start", timeout=ACCOUNT_TIMEOUT_S) or {}

    async def chatgpt_poll(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/oauth/chatgpt/poll", timeout=ACCOUNT_TIMEOUT_S) or {}

    async def chatgpt_status(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/oauth/chatgpt/status", timeout=STATUS_TIMEOUT_S) or {}

    async def chatgpt_logout(self) -> None:
        await self._request("POST", "/v1/oauth/chatgpt/logout", timeout=ACCOUNT_TIMEOUT_S)

    async def local(
        self, method: str, path: str, *, json: dict[str, Any] | None = None, timeout: float = LOCAL_TIMEOUT_S
    ) -> tuple[int, dict[str, Any] | None]:
        """One call to the local-model routes; returns the host's status and JSON body.

        ``json`` is sent only by the custom-model routes, built by the caller from a validated request body.

        Unlike the other calls, a host refusal (404, 409, 507...) is returned, not raised: the user needs
        its code and figures (needed space, the processes using a model). Only "cannot talk to or
        authenticate against the host" raises ``HostUnavailableError``. The caller passes a path built
        from its own fixed templates, so the target is never chosen by a request field.
        """
        response = await self._send(method, path, timeout=timeout, json=json)
        code = _error_code(response) if response.status_code >= 400 else None
        if response.status_code == 401 or (response.status_code == 503 and code == "management_auth_unavailable"):
            logger.warning("host_engine_unavailable status=%s", response.status_code)
            raise HostUnavailableError
        if response.status_code == 204 or not response.content:
            return response.status_code, None
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise HostUnavailableError
        try:
            body = response.json()
        except ValueError:
            raise HostUnavailableError from None
        if not isinstance(body, dict):
            raise HostUnavailableError
        return response.status_code, body

    async def engines_status(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/engines/status", timeout=STATUS_TIMEOUT_S) or {}


def get_host_client() -> HostClient:
    """FastAPI dependency; tests override it with a client wired to a fake host service."""
    return HostClient()
