"""Allocator scheduling contracts; these tests do not certify acoustic quality."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "native_main.py"
SPEC = importlib.util.spec_from_file_location("native_asr_memory_budget", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)


@pytest.mark.asyncio
async def test_allocator_limits_are_set_before_engine_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    mlx = ModuleType("mlx")
    mlx.core = SimpleNamespace(  # type: ignore[attr-defined]
        set_memory_limit=lambda value: calls.append(("memory", value)),
        set_cache_limit=lambda value: calls.append(("cache", value)),
    )
    whisper = ModuleType("mlx_whisper")

    def transcribe(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"segments": []}

    whisper.transcribe = transcribe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx_whisper", whisper)
    object_store = object()
    monkeypatch.setattr(native.boto3, "client", lambda *args, **kwargs: object_store)

    async with native.lifespan(native.app):
        assert calls == [("memory", 4 * 1024**3), ("cache", 256 * 1024**2)]
        assert native.transcribe_audio is transcribe
        assert native.s3_client is object_store
    assert native.transcribe_audio is None
    assert native.s3_client is None


@pytest.mark.asyncio
async def test_allocator_configuration_failure_does_not_publish_an_unbounded_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_limit: int) -> None:
        raise RuntimeError("synthetic allocator error")

    mlx = ModuleType("mlx")
    mlx.core = SimpleNamespace(set_memory_limit=fail)  # type: ignore[attr-defined]
    whisper = ModuleType("mlx_whisper")
    whisper.transcribe = object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx_whisper", whisper)
    monkeypatch.setattr(native, "transcribe_audio", None)
    monkeypatch.setattr(native.boto3, "client", lambda *args, **kwargs: object())

    with pytest.raises(RuntimeError, match="Unable to initialize mlx-whisper"):
        async with native.lifespan(native.app):
            pytest.fail("engine must not start after allocator setup failure")
    assert native.transcribe_audio is None
