"""Opt-in: the gateways run the catalog models installed on this machine with the real binaries.

``SAURI_RUN_NATIVE_TESTS=1 .venv/bin/pytest tests/native/test_local_model_native.py`` loads real models:
``whisper-cli`` on a one-second synthetic tone for every installed transcription model, and the real
``llama-server`` (on a random free port, never 8004) for the smallest installed summary model. Models
count as installed only when ``host-engine`` verified them (manifest) or they are the process default at
the engine's legacy location. Nothing is downloaded, moved or deleted; the owner's running engines are
not touched (this test starts its own processes).
"""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import wave
from pathlib import Path
from types import ModuleType

import pytest

from tests.local_models_support import route_header

pytestmark = pytest.mark.skipif(
    os.environ.get("SAURI_RUN_NATIVE_TESTS") != "1", reason="Set SAURI_RUN_NATIVE_TESTS=1 to load real models",
)
BACKEND = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(BACKEND / "engine-common"), str(BACKEND / "asr-engine"), str(BACKEND / "llm-engine")]


def _load(name: str, directory: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, BACKEND / directory / "native_main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _installed(process: str, legacy_default: Path) -> list[tuple[str, int, Path]]:
    from sauri_engine_common.local_model_use import LocalModelError, load_runtime_catalog, select_local_model

    found = []
    for entry in load_runtime_catalog().models:
        if entry.process != process or entry.kind != "model":
            continue
        try:
            chosen = select_local_model(
                route_header(f"local:{entry.id}", process="transcription" if process == "transcription" else "summary"),
                process="transcription" if process == "transcription" else "summary",
                legacy_default=legacy_default,
            )
        except LocalModelError:
            continue
        assert chosen is not None
        found.append((entry.id, entry.size or 0, chosen.path))
    return found


def test_whisper_cli_loads_every_installed_transcription_model(tmp_path: Path) -> None:
    asr = _load("sauri_native_asr_local", "asr-engine")
    cli = Path(asr.WHISPER_CLI)
    models = _installed("transcription", asr.ASR_MODEL_PATH)
    if not cli.is_file() or not models:
        pytest.skip("whisper-cli or an installed transcription model is missing")
    audio = tmp_path / "tone.wav"
    with wave.open(str(audio), "wb") as tone:
        tone.setnchannels(1)
        tone.setsampwidth(2)
        tone.setframerate(16000)
        tone.writeframes(b"\x00\x00" * 16000)
    for model_id, _size, path in models:
        document = asr._run_whisper(audio, tmp_path / f"out-{model_id}", "en", 300.0, model_path=path)
        assert isinstance(document["transcription"], list), model_id


async def test_llama_server_runs_the_chosen_summary_model(tmp_path: Path) -> None:
    llm = _load("sauri_native_llm_local", "llm-engine")
    server = llm.server
    models = sorted(_installed("summary", server.model), key=lambda item: item[1])
    if not server.binary.is_file() or not models:
        pytest.skip("llama-server or an installed summary model is missing")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server.url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    model_id, _size, path = models[0]
    chosen = llm.LocalSelection(model_id, path)
    try:
        answer = await server.chat({"messages": [{"role": "user", "content": "Say ok."}], "max_tokens": 4}, chosen)
        assert answer["choices"]
        assert server.loaded_model == path
    finally:
        await server.stop()
