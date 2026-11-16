"""Password hashing and verification for the minimal User store.

New hashes use Argon2id (OWASP minimum profile: 19 MiB of memory, 2 passes, 1 lane) through
``argon2-cffi``. The hash string is self-describing (``$argon2id$...``), so the scheme needs no extra
column. Hashes created before the migration to Argon2id (``pbkdf2_sha256$<iterations>$<salt>$<hash>``)
still verify with a constant-time comparison, and ``needs_rehash`` tells the login flow to upgrade them
transparently after a successful verification. Not an integration with Summan's IdP (Req. 13.1, 13.2).
"""

from __future__ import annotations

import hashlib
import hmac
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_LEGACY_ALGORITHM = "pbkdf2_sha256"
_ARGON2_PREFIX = "$argon2id$"

# OWASP password storage cheat sheet, Argon2id minimum: m=19 MiB, t=2, p=1.
_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)


def hash_password(password: str) -> str:
    """Hash a password with Argon2id and a random salt."""
    return _HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an Argon2id hash or a legacy PBKDF2 hash."""
    if password_hash.startswith(_ARGON2_PREFIX):
        try:
            return _HASHER.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
    return _verify_legacy(password, password_hash)


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash is not Argon2id with the current parameters."""
    if not password_hash.startswith(_ARGON2_PREFIX):
        return True
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@cache
def _dummy_hash() -> str:
    # Computed once with the live parameters so an unknown account costs the same as a known one.
    return _HASHER.hash("sauri-timing-equalization-dummy")


def verify_dummy_password(password: str) -> None:
    """Spend the same work as verifying a real hash; the result is always a mismatch."""
    verify_password(password, _dummy_hash())


def _verify_legacy(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_str, salt_hex, hash_hex = password_hash.split("$")
        if algorithm != _LEGACY_ALGORITHM:
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)
