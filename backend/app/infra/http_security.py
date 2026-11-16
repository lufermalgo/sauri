"""HTTP hardening for the API: CORS allow-list, security headers and docs exposure.

Everything here is configured through environment variables so one image serves both the
local stack and a later deployment:

- ``CORS_ALLOWED_ORIGINS``: comma-separated browser origins allowed to call the API
  (default: the portal dev server on ``localhost``/``127.0.0.1`` port 5173).
- ``EXTENSION_ORIGINS``: comma-separated Chrome extension origins (``chrome-extension://<id>``)
  or bare 32-letter extension ids (default: the owner's unpacked build).
- ``APP_ENV`` / ``ENABLE_API_DOCS``: ``/docs``, ``/redoc`` and ``/openapi.json`` exist only when
  ``APP_ENV`` is ``development`` or ``test`` or ``ENABLE_API_DOCS`` is ``true``.

A wildcard origin is never accepted: the application refuses to start with one.
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
# Id of the owner's unpacked extension build; override with EXTENSION_ORIGINS for other builds.
DEFAULT_EXTENSION_ORIGINS = "chrome-extension://ilnkkojmkfnbdilogldabpodoobfigce"

CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOWED_HEADERS = ["Authorization", "Content-Type", "Accept"]
CORS_MAX_AGE_SECONDS = 600

_DOCS_ENVIRONMENTS = {"development", "test"}
_EXTENSION_ID = re.compile(r"^[a-p]{32}$")
_DOCS_PATHS = ("/docs", "/redoc")

# The API serves JSON only: nothing it returns should ever render, load or be framed.
_API_CSP = "default-src 'none'; frame-ancestors 'none'"
_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class HttpSecurityConfigError(ValueError):
    """Raised when an HTTP security setting is unsafe or malformed."""


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_origin(raw: str, variable: str) -> str:
    """Return ``scheme://host[:port]`` or raise; wildcards and paths are rejected."""
    if raw == "*" or "*" in raw:
        raise HttpSecurityConfigError(f"{variable} must list explicit origins; a wildcard is not allowed")
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https", "chrome-extension"} or not parts.netloc:
        raise HttpSecurityConfigError(f"{variable} contains an invalid origin: {raw!r}")
    if parts.path not in {"", "/"} or parts.query or parts.fragment or parts.username or parts.password:
        raise HttpSecurityConfigError(f"{variable} entries must be origins without path or credentials: {raw!r}")
    return f"{parts.scheme}://{parts.netloc}"


def extension_origins() -> list[str]:
    """Chrome extension origins from ``EXTENSION_ORIGINS`` (bare ids are expanded)."""
    raw = os.environ.get("EXTENSION_ORIGINS")
    entries = _split(DEFAULT_EXTENSION_ORIGINS if raw is None else raw)
    origins: list[str] = []
    for entry in entries:
        if _EXTENSION_ID.match(entry):
            entry = f"chrome-extension://{entry}"
        origin = _normalize_origin(entry, "EXTENSION_ORIGINS")
        if not origin.startswith("chrome-extension://"):
            raise HttpSecurityConfigError("EXTENSION_ORIGINS entries must be chrome-extension:// origins or ids")
        origins.append(origin)
    return origins


def cors_allowed_origins() -> list[str]:
    """The exact origins the browser may call the API from, without duplicates."""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS")
    entries = _split(DEFAULT_CORS_ORIGINS if raw is None else raw)
    web = [_normalize_origin(entry, "CORS_ALLOWED_ORIGINS") for entry in entries]
    return list(dict.fromkeys(web + extension_origins()))


def cors_options() -> dict[str, Any]:
    """Keyword arguments for ``CORSMiddleware``; credentials stay off (no cookies are used)."""
    return {
        "allow_origins": cors_allowed_origins(),
        "allow_methods": CORS_ALLOWED_METHODS,
        "allow_headers": CORS_ALLOWED_HEADERS,
        "allow_credentials": False,
        "max_age": CORS_MAX_AGE_SECONDS,
    }


def api_docs_enabled() -> bool:
    """Whether the interactive docs and the OpenAPI schema may be served."""
    if os.environ.get("ENABLE_API_DOCS", "").strip().lower() == "true":
        return True
    return os.environ.get("APP_ENV", "").strip().lower() in _DOCS_ENVIRONMENTS


def docs_paths() -> tuple[str | None, str | None, str | None]:
    """``(docs_url, redoc_url, openapi_url)``: the documentation endpoints, or all ``None`` when hidden."""
    if api_docs_enabled():
        return "/docs", "/redoc", "/openapi.json"
    return None, None, None


def security_headers(*, https: bool, path: str = "") -> list[tuple[str, str]]:
    """Headers added to every API response unless a route already set them."""
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Permissions-Policy", _PERMISSIONS_POLICY),
    ]
    if path.startswith(_DOCS_PATHS):
        # The interactive docs load their own scripts; only framing is denied there.
        headers.append(("Content-Security-Policy", "frame-ancestors 'none'"))
    else:
        headers.append(("Content-Security-Policy", _API_CSP))
    if https:
        headers.append(("Strict-Transport-Security", "max-age=31536000; includeSubDomains"))
    return headers


def apply_security_headers(headers: MutableHeaders, *, https: bool, path: str = "") -> None:
    """Add the security headers to ``headers`` without overriding existing values."""
    for name, value in security_headers(https=https, path=path):
        if name not in headers:
            headers[name] = value


def _is_https(scope: Scope) -> bool:
    return scope.get("scheme") == "https"


class SecurityHeadersMiddleware:
    """Pure ASGI middleware: adds the security headers; HSTS only on HTTPS requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        https = _is_https(scope)
        path = str(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                apply_security_headers(MutableHeaders(scope=message), https=https, path=path)
            await send(message)

        await self.app(scope, receive, send_with_headers)
