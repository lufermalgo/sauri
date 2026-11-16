"""Read service credentials from private files mounted into the container.

Each credential can come from a file named by ``<NAME>_FILE`` (preferred: the value never
appears in the container environment) or, as a fallback for tests and CI, from a plain
environment variable. Values are never logged.
"""

from __future__ import annotations

import logging
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
        env_value = os.environ.get(value_env)
        if env_value:
            return env_value
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


def require_url_password(url: str, file_env: str, label: str) -> None:
    """Fail when a network connection URL carries no password (the value is never shown).

    Local SQLite URLs and the explicit test mode (``APP_ENV=test``) are exempt; deployments
    must supply the password inside the URL or through the file named by ``file_env``.
    """
    parts = urlsplit(url)
    if parts.scheme.startswith("sqlite") or parts.password:
        return
    if os.environ.get("APP_ENV", "").lower() == "test":
        return
    raise SecretUnavailableError(f"{label} has no password: set {file_env} to a private credentials file")


def secret_source(file_env: str, value_env: str | None = None) -> str:
    """Where a credential would come from: ``file``, ``env`` or ``missing``. Never reads the value."""
    file_path = os.environ.get(file_env)
    if file_path:
        path = Path(file_path)
        return "file" if path.is_file() and path.stat().st_size > 0 else "missing"
    if value_env is not None and os.environ.get(value_env):
        return "env"
    return "missing"


_STARTUP_SECRETS: tuple[tuple[str, str, str | None], ...] = (
    ("database_password", "DATABASE_PASSWORD_FILE", None),
    ("queue_password", "QUEUE_BROKER_PASSWORD_FILE", None),
    ("object_store_access_key", "OBJECT_STORE_ACCESS_KEY_FILE", "MINIO_ROOT_USER"),
    ("object_store_secret_key", "OBJECT_STORE_SECRET_KEY_FILE", "MINIO_ROOT_PASSWORD"),
    ("jwt_secret", "JWT_SECRET_FILE", "JWT_SECRET"),
    ("queue_message_signing_key", "QUEUE_MESSAGE_SIGNING_KEY_FILE", "QUEUE_MESSAGE_SIGNING_KEY"),
)


def log_secret_sources(logger: logging.Logger) -> None:
    """Log which credential sources were found at startup (names and kinds only, no values)."""
    found = ", ".join(f"{name}={secret_source(file_env, value_env)}" for name, file_env, value_env in _STARTUP_SECRETS)
    logger.info("Secret sources: %s", found)
