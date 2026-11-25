"""Low-memory mode: below 16 GiB, unless SAURI_LOW_MEMORY says otherwise."""

from __future__ import annotations

import pytest
from sauri_engine_common import memory


@pytest.mark.parametrize(("gib", "low"), [(0, False), (4, True), (8, True), (15.99, True), (16, False), (24, False)])
def test_low_memory_is_a_known_memory_below_16_gib(gib: float, low: bool) -> None:
    assert memory.is_low_memory(gib) is low


def test_the_mode_follows_the_memory_of_this_computer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAURI_LOW_MEMORY", raising=False)
    monkeypatch.setattr(memory, "memory_bytes", lambda: 8 * memory.GIB)
    assert memory.low_memory_mode() is True
    monkeypatch.setattr(memory, "memory_bytes", lambda: 16 * memory.GIB)
    assert memory.low_memory_mode() is False
    monkeypatch.setattr(memory, "memory_bytes", lambda: 0)  # unknown memory keeps the normal behavior
    assert memory.low_memory_mode() is False


@pytest.mark.parametrize(("value", "low"), [("1", True), ("on", True), ("0", False), ("off", False)])
def test_sauri_low_memory_forces_the_mode_either_way(monkeypatch: pytest.MonkeyPatch, value: str, low: bool) -> None:
    monkeypatch.setenv("SAURI_LOW_MEMORY", value)
    monkeypatch.setattr(memory, "memory_bytes", lambda: (24 if low else 8) * memory.GIB)
    assert memory.low_memory_mode() is low


def test_an_unreadable_override_falls_back_to_the_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAURI_LOW_MEMORY", "maybe")
    monkeypatch.setattr(memory, "memory_bytes", lambda: 8 * memory.GIB)
    assert memory.low_memory_mode() is True
