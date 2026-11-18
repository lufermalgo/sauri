"""Short-lived, object-scoped media capabilities; unrelated to engine capabilities."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Literal, TypedDict

from app.infra.secrets import SecretUnavailableError, read_secret


class MediaClaims(TypedDict):
    key: str
    exp: int
    ct: str
    disp: Literal["inline", "attachment"]
    filename: str | None


def _secret() -> bytes:
    # Engine capabilities sign with the raw file bytes, including a trailing newline.
    key_path = Path(os.environ.get(
        "SAURI_RECORDING_CAPABILITY_KEY_FILE", Path.home() / ".config/sauri/recording_capability_key",
    ))
    if os.environ.get("SAURI_RECORDING_CAPABILITY_KEY_FILE"):
        read_secret("SAURI_RECORDING_CAPABILITY_KEY_FILE")
    try:
        secret = key_path.read_bytes()
    except OSError as exc:
        raise SecretUnavailableError("Recording capability key is unavailable") from exc
    if not secret.strip():
        raise SecretUnavailableError("Recording capability key is unavailable")
    return secret


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_media_token(
    key: str, ttl_seconds: int, content_type: str, *, filename: str | None = None,
) -> str:
    claims: MediaClaims = {
        "key": key, "exp": int(time.time()) + ttl_seconds, "ct": content_type,
        "disp": "attachment" if filename is not None else "inline", "filename": filename,
    }
    payload = _encode(json.dumps(claims, separators=(",", ":"), ensure_ascii=True).encode())
    signature = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_media_token(token: str) -> MediaClaims:
    secret = _secret()
    try:
        payload, signature = token.split(".")
        expected = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        raw = base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True)
        claims = json.loads(raw)
        if (
            not isinstance(claims, dict)
            or not isinstance(claims.get("key"), str)
            or type(claims.get("exp")) is not int
            or claims["exp"] <= time.time()
            or not isinstance(claims.get("ct"), str)
            or not claims["ct"]
            or any(ord(c) < 32 or ord(c) > 126 for c in claims["ct"])
            or claims.get("disp") not in {"inline", "attachment"}
            or (claims.get("filename") is not None and not isinstance(claims["filename"], str))
        ):
            raise ValueError
        return MediaClaims(
            key=claims["key"], exp=claims["exp"], ct=claims["ct"],
            disp=claims["disp"], filename=claims.get("filename"),
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid_media_token") from exc
