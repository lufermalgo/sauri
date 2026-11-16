"""Argon2id hashing, legacy PBKDF2 verification and rehash detection (#1069)."""

from __future__ import annotations

import hmac

import pytest

from app.auth import passwords
from app.auth.passwords import hash_password, needs_rehash, verify_password
from tests.auth.helpers import legacy_hash


def test_new_hashes_are_argon2id_with_owasp_parameters() -> None:
    hashed = hash_password("synthetic-password")
    assert hashed.startswith("$argon2id$")
    assert "m=19456,t=2,p=1" in hashed
    assert hash_password("synthetic-password") != hashed  # random salt
    assert not needs_rehash(hashed)


def test_argon2_hash_verifies_and_wrong_password_fails() -> None:
    hashed = hash_password("synthetic-password")
    assert verify_password("synthetic-password", hashed)
    assert not verify_password("synthetic-passworD", hashed)
    assert not verify_password("", hashed)


def test_legacy_pbkdf2_hash_still_verifies_and_asks_for_rehash() -> None:
    hashed = legacy_hash("synthetic-password")
    assert verify_password("synthetic-password", hashed)
    assert not verify_password("another-password", hashed)
    assert needs_rehash(hashed)


def test_legacy_verification_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(passwords.hmac, "compare_digest", spy)
    assert verify_password("synthetic-password", legacy_hash("synthetic-password"))
    assert not verify_password("wrong", legacy_hash("synthetic-password"))
    assert len(calls) == 2


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "x",
        "plain-text",
        "pbkdf2_sha256$1$zz$zz",
        "pbkdf2_sha256$a$b",
        "$argon2id$broken",
        "$argon2id$v=19$m=1,t=1,p=1$a$b",
    ],
)
def test_malformed_hashes_never_verify(garbage: str) -> None:
    assert not verify_password("synthetic-password", garbage)
    assert needs_rehash(garbage)


def test_weaker_argon2_parameters_need_rehash() -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("synthetic-password")
    assert verify_password("synthetic-password", weak)
    assert needs_rehash(weak)
