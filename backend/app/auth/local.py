"""Configuration and credentials for the single-user local API."""

import os
import re
from http.cookies import SimpleCookie
from pathlib import Path

LOCAL_COOKIE = "sauri_local"


class LocalConfigurationError(ValueError):
    """Invalid local configuration; messages never contain credentials."""


def local_mode() -> bool:
    mode = os.environ.get("SAURI_AUTH_MODE", "password")
    if mode not in {"password", "local"}:
        raise LocalConfigurationError("invalid_auth_mode")
    return mode == "local"


def local_token() -> str:
    path = os.environ.get("SAURI_LOCAL_TOKEN_FILE")
    if not path:
        raise LocalConfigurationError("local_token_unavailable")
    try:
        token = Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise LocalConfigurationError("local_token_unavailable") from error
    if not re.fullmatch(r"[0-9a-fA-F]{64}", token):
        raise LocalConfigurationError("local_token_unavailable")
    return token


def local_cookie_header() -> str:
    """Set-Cookie value for U3's index.html response and the same-origin status bootstrap."""
    cookie = SimpleCookie()
    cookie[LOCAL_COOKIE] = local_token()
    cookie[LOCAL_COOKIE]["httponly"] = True
    cookie[LOCAL_COOKIE]["samesite"] = "Strict"
    cookie[LOCAL_COOKIE]["path"] = "/"
    return cookie.output(header="").strip()
