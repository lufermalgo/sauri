"""Object-store credentials for the native engines, read from the private config folder."""

from __future__ import annotations

import os
from pathlib import Path

_CONFIG_DIR = Path.home() / ".config" / "sauri"


class CredentialsUnavailableError(RuntimeError):
    """Raised when the object-store keys are missing; values are never included."""


def _read(value_env: str, file_env: str, default_name: str) -> str:
    explicit = os.environ.get(value_env)
    if explicit:
        return explicit
    path = Path(os.environ.get(file_env, _CONFIG_DIR / default_name))
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CredentialsUnavailableError(f"Object-store key file is unavailable: {path} (run make build)") from exc
    if not value:
        raise CredentialsUnavailableError(f"Object-store key file is empty: {path}")
    return value


def object_store_credentials() -> tuple[str, str]:
    """Access and secret key: env override first, then ~/.config/sauri files."""
    return (
        _read("MINIO_ROOT_USER", "SAURI_OBJECT_STORE_ACCESS_KEY_FILE", "object_store_access_key"),
        _read("MINIO_ROOT_PASSWORD", "SAURI_OBJECT_STORE_SECRET_KEY_FILE", "object_store_secret_key"),
    )
