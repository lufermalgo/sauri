"""Scoped checkpoint schema compatibility; no pickle security bypass or inference."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_diar_checkpoint_loading", Path(__file__).resolve().parents[2] / "diar-engine/native_main.py"
)
assert SPEC is not None and SPEC.loader is not None
native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)


@pytest.mark.asyncio
@pytest.mark.parametrize("load_fails", [False, True])
async def test_checkpoint_schema_allowlist_is_narrow_and_scoped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, load_fails: bool,
) -> None:
    expected = [type(name, (), {}) for name in ("Specifications", "Problem", "Resolution", "TorchVersion")]
    scopes: list[list[type[Any]]] = []
    events: list[str] = []

    @contextmanager
    def safe_globals(types: list[type[Any]]) -> Iterator[None]:
        assert set(types) == set(expected)
        scopes.append(types)
        events.append("enter")
        try:
            yield
        finally:
            scopes.pop()
            events.append("exit")

    class Pipeline:
        @classmethod
        def from_pretrained(cls, model_id: str, *, use_auth_token: str) -> Any:
            assert scopes and set(scopes[-1]) == set(expected)
            assert model_id == native.MODEL_ID and use_auth_token == "synthetic-test-token"
            events.append("load")
            if load_fails:
                raise ValueError("synthetic load failure")
            return cls()

        def to(self, device: str) -> None:
            assert device == "mps"
            assert not scopes
            events.append("mps")

    modules = {name: ModuleType(name) for name in (
        "torch", "torch.torch_version", "pyannote", "pyannote.audio", "pyannote.audio.core",
        "pyannote.audio.core.task",
    )}
    modules["torch"].serialization = SimpleNamespace(safe_globals=safe_globals)  # type: ignore[attr-defined]
    modules["torch"].device = lambda value: value  # type: ignore[attr-defined]
    modules["torch.torch_version"].TorchVersion = expected[3]  # type: ignore[attr-defined]
    modules["pyannote.audio"].Pipeline = Pipeline  # type: ignore[attr-defined]
    for name, cls in zip(("Specifications", "Problem", "Resolution"), expected[:3], strict=True):
        setattr(modules["pyannote.audio.core.task"], name, cls)
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    token_path = tmp_path / "synthetic-token"
    token_path.write_text("synthetic-test-token")
    monkeypatch.setattr(native, "HF_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "diarization_pipeline", None)
    monkeypatch.setattr(native.boto3, "client", lambda *args, **kwargs: object())

    if load_fails:
        with pytest.raises(RuntimeError, match="Unable to initialize native diarization"):
            async with native.lifespan(native.app):
                pytest.fail("a failed checkpoint must never activate the engine")
        assert native.diarization_pipeline is None
        assert events == ["enter", "load", "exit"]
    else:
        async with native.lifespan(native.app):
            assert isinstance(native.diarization_pipeline, Pipeline)
        assert native.diarization_pipeline is None
        assert events == ["enter", "load", "exit", "mps"]
    assert not scopes
