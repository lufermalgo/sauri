"""Host secret store for provider keys: macOS Keychain with a private-file fallback.

Keys are only ever read by native host processes. Every failure is an exception that carries a
class code and never a key, an origin or a path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

SECURITY_BINARY: Final = "/usr/bin/security"
KEYCHAIN_SERVICE: Final = "sauri"
REF_PATTERN: Final = re.compile(r"[A-Za-z0-9._/-]{1,200}")
_SERVICE_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,100}")
_KEY_HINT_MIN_LENGTH: Final = 12
_KEYCHAIN_TIMEOUT_S: Final = 10.0
# ``security -i`` truncates a command line at 4096 bytes (measured on macOS: a 2900-character key is stored
# intact, 3000 is cut). Longer secrets are refused up front instead of being stored corrupted.
MAX_KEYCHAIN_COMMAND_CHARS: Final = 4000


class SecretError(Exception):
    """Base error: ``str(error)`` is the class code only."""

    code = "secret_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class SecretUnavailableError(SecretError):
    """The secret is missing or the store cannot be read or written."""

    code = "secret_unavailable"


SecretUnavailable = SecretUnavailableError  # name used by design.md


class InvalidSecretRefError(SecretError):
    code = "invalid_secret_ref"


class InvalidSecretError(SecretError):
    code = "invalid_secret"


class SecretTooLargeError(InvalidSecretError):
    """The secret does not fit the Keychain command line; use the file store for larger records."""

    code = "secret_too_large"


@dataclass(frozen=True, repr=False)
class SecretRecord:
    """A provider key bound to the origin (``scheme://host[:port]``) it was issued for."""

    key: str
    origin: str

    def __repr__(self) -> str:
        return f"SecretRecord(key=***, origin={self.origin!r})"


def key_hint(key: str) -> str | None:
    """Last four characters, only when the key is long enough that they reveal little."""
    return key[-4:] if len(key) >= _KEY_HINT_MIN_LENGTH else None


def validate_ref(ref: str) -> str:
    if not isinstance(ref, str) or REF_PATTERN.fullmatch(ref) is None:
        raise InvalidSecretRefError
    return ref


def _validate_record(record: SecretRecord) -> None:
    if not record.key or not record.origin:
        raise InvalidSecretError


def _serialize(record: SecretRecord) -> str:
    return json.dumps({"key": record.key, "origin": record.origin}, separators=(",", ":"))


def _deserialize(text: str) -> SecretRecord:
    try:
        data = json.loads(text)
        key, origin = data["key"], data["origin"]
    except (ValueError, KeyError, TypeError):
        raise SecretUnavailableError from None
    if not isinstance(key, str) or not isinstance(origin, str) or not key or not origin:
        raise SecretUnavailableError
    return SecretRecord(key=key, origin=origin)


class SecretStore(Protocol):
    name: str

    def put(self, ref: str, record: SecretRecord) -> None: ...

    def get(self, ref: str) -> SecretRecord: ...

    def delete(self, ref: str) -> None: ...


class FileSecretStore:
    """One 0600 file per secret in a 0700 folder; writes are atomic replacements."""

    name = "file"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else Path.home() / ".config" / "sauri" / "secrets"

    def _path(self, ref: str) -> Path:
        return self.root / hashlib.sha256(validate_ref(ref).encode()).hexdigest()

    def _ensure_root(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.root.is_symlink() or not self.root.is_dir():
                raise SecretUnavailableError
            os.chmod(self.root, 0o700)
        except OSError:
            raise SecretUnavailableError from None

    def put(self, ref: str, record: SecretRecord) -> None:
        path = self._path(ref)
        _validate_record(record)
        self._ensure_root()
        payload = _serialize(record).encode()
        try:
            fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        except OSError:
            raise SecretUnavailableError from None
        try:
            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except OSError:
            Path(tmp_name).unlink(missing_ok=True)
            raise SecretUnavailableError from None

    def get(self, ref: str) -> SecretRecord:
        path = self._path(ref)
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            raise SecretUnavailableError from None
        try:
            with os.fdopen(fd, "rb") as handle:
                text = handle.read().decode()
        except (OSError, UnicodeError):
            raise SecretUnavailableError from None
        return _deserialize(text)

    def delete(self, ref: str) -> None:
        path = self._path(ref)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise SecretUnavailableError from None


class KeychainSecretStore:
    """Generic passwords in the login keychain, always through ``/usr/bin/security``.

    ``put`` sends the command through standard input (``security -i``) so the key never appears in
    ``argv`` or ``ps``. The stored value is base64url(JSON), which needs no quoting in that command
    language and survives ``find-generic-password -w`` unchanged.
    """

    name = "keychain"

    def __init__(
        self,
        service: str = KEYCHAIN_SERVICE,
        binary: str = SECURITY_BINARY,
        timeout_s: float = _KEYCHAIN_TIMEOUT_S,
    ) -> None:
        if _SERVICE_PATTERN.fullmatch(service) is None:
            raise InvalidSecretRefError
        self.service = service
        self.binary = binary
        self.timeout_s = timeout_s

    def _run(self, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.binary, *args],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise SecretUnavailableError from None

    def put(self, ref: str, record: SecretRecord) -> None:
        validate_ref(ref)
        _validate_record(record)
        payload = base64.urlsafe_b64encode(_serialize(record).encode()).decode().rstrip("=")
        command = f"add-generic-password -U -s {self.service} -a {ref} -w {payload}\n"
        if len(command) > MAX_KEYCHAIN_COMMAND_CHARS:
            raise SecretTooLargeError
        self._run(["-i"], stdin=command)
        # Interactive mode reports errors on its output but may still exit 0: confirm by reading back.
        if self.get(ref) != record:
            raise SecretUnavailableError

    def get(self, ref: str) -> SecretRecord:
        validate_ref(ref)
        result = self._run(["find-generic-password", "-s", self.service, "-a", ref, "-w"])
        if result.returncode != 0:
            raise SecretUnavailableError
        encoded = result.stdout.strip()
        try:
            text = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        except (binascii.Error, ValueError):
            raise SecretUnavailableError from None
        return _deserialize(text)

    def delete(self, ref: str) -> None:
        validate_ref(ref)
        result = self._run(["delete-generic-password", "-s", self.service, "-a", ref])
        # 44 = item not found: deleting a missing secret is a no-op.
        if result.returncode not in (0, 44):
            raise SecretUnavailableError


def _keychain_responds() -> bool:
    try:
        result = subprocess.run(
            [SECURITY_BINARY, "default-keychain"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def default_secret_store() -> SecretStore:
    """Keychain on macOS when it answers, otherwise the private-file store.

    ``SAURI_SECRET_STORE=keychain|file`` forces one backend so every host process agrees.
    """
    forced = os.environ.get("SAURI_SECRET_STORE", "auto")
    if forced == "file":
        return FileSecretStore()
    if forced == "keychain":
        return KeychainSecretStore()
    if sys.platform == "darwin" and Path(SECURITY_BINARY).exists() and _keychain_responds():
        return KeychainSecretStore()
    return FileSecretStore()
