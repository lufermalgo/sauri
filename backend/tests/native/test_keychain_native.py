"""Opt-in real macOS Keychain cycle under a throwaway service; the owner's ``sauri`` service is never used."""

from __future__ import annotations

import os
import secrets as stdlib_secrets
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine-common"))

from sauri_engine_common.secrets import (  # noqa: E402
    SECURITY_BINARY,
    KeychainSecretStore,
    SecretRecord,
    SecretTooLargeError,
    SecretUnavailableError,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SAURI_RUN_NATIVE_TESTS") != "1" or sys.platform != "darwin",
    reason="Set SAURI_RUN_NATIVE_TESTS=1 on macOS to exercise the real Keychain",
)


@pytest.fixture
def service() -> Iterator[str]:
    name = f"sauri-test-{uuid.uuid4()}"
    assert name != "sauri"
    yield name
    # Remove anything the test left under its own throwaway service (never any other service).
    for _ in range(10):
        gone = subprocess.run(
            [SECURITY_BINARY, "delete-generic-password", "-s", name], capture_output=True, check=False
        )
        if gone.returncode != 0:
            break


def _watch_process_list(marker: str, stop: threading.Event, seen: list[str]) -> None:
    while not stop.is_set():
        listing = subprocess.run(["ps", "-axww", "-o", "command="], capture_output=True, text=True, check=False)
        if marker in listing.stdout:
            seen.append("marker visible in the process list")


def test_put_get_delete_cycle_keeps_the_key_out_of_the_process_list(service: str) -> None:
    store = KeychainSecretStore(service=service)
    ref = f"sauri-test/{uuid.uuid4()}/provider"
    marker = "NATIVEKEY" + stdlib_secrets.token_hex(12)
    record = SecretRecord(key=marker, origin="https://api.example.com")
    seen: list[str] = []
    stop = threading.Event()
    watcher = threading.Thread(target=_watch_process_list, args=(marker, stop, seen))
    watcher.start()
    try:
        for _ in range(10):
            store.put(ref, record)
        assert store.get(ref) == record
        replacement = SecretRecord(key=marker + "-new", origin="https://other.example.com")
        store.put(ref, replacement)
        assert store.get(ref) == replacement
    finally:
        stop.set()
        watcher.join()
        store.delete(ref)
    assert seen == []
    with pytest.raises(SecretUnavailableError):
        store.get(ref)


def test_the_largest_host_record_survives_and_larger_ones_are_refused(service: str) -> None:
    store = KeychainSecretStore(service=service)
    ref = f"sauri-test/{uuid.uuid4()}/large"
    largest = SecretRecord(key="L" * 2048, origin="https://" + "a" * 240 + ".com")
    try:
        store.put(ref, largest)
        assert store.get(ref) == largest
        with pytest.raises(SecretTooLargeError):
            store.put(ref, SecretRecord(key="L" * 6000, origin="https://api.example.com"))
        assert store.get(ref) == largest  # a refused write leaves the stored value intact
    finally:
        store.delete(ref)
