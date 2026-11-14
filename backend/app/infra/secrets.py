"""Read service credentials from private files mounted into the container.

Each credential can come from a file named by ``<NAME>_FILE`` (preferred: the value never
appears in the container environment) or, as a fallback for tests and CI, from a plain
environment variable. Values are never logged.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit


class SecretUnavailableError(RuntimeError):
    """Raised when a required credential is missing or empty."""


def read_secret(file_env: str, value_env: str | None = None) -> str | None:
    """Return the credential from the file named by ``file_env``, else from ``value_env``."""
    file_path = os.environ.get(file_env)
    if file_path:
        try:
            value = Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SecretUnavailableError(f"{file_env} points to an unreadable file") from exc
        if not value:
            raise SecretUnavailableError(f"{file_env} points to an empty file")
        return value
    if value_env is not None:
        value = os.environ.get(value_env)
        if value:
            return value
    return None


def require_secret(file_env: str, value_env: str | None = None) -> str:
    """Like :func:`read_secret` but fails when the credential is absent."""
    value = read_secret(file_env, value_env)
    if value is None:
        names = f"{file_env} or {value_env}" if value_env else file_env
        raise SecretUnavailableError(f"Set {names}")
    return value


def with_password(url: str, password: str | None) -> str:
    """Insert ``password`` into a ``scheme://user@host/...`` URL (no-op when None)."""
    if password is None:
        return url
    parts = urlsplit(url)
    if parts.username is None:
        raise SecretUnavailableError("Connection URL must name a user to receive the password file")
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{quote(parts.username, safe='')}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def object_store_credentials() -> tuple[str, str]:
    """Access and secret key for the S3-compatible object store."""
    access_key = require_secret("OBJECT_STORE_ACCESS_KEY_FILE", "MINIO_ROOT_USER")
    secret_key = require_secret("OBJECT_STORE_SECRET_KEY_FILE", "MINIO_ROOT_PASSWORD")
    return access_key, secret_key
