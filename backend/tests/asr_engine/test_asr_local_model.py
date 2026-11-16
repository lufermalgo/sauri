"""The ASR gateway transcribes with the model a ``local:<id>`` route names, using a fake ``whisper-cli``.

The fake executable records the ``-m`` argument of every run and writes a minimal whisper JSON result, so
no real model or binary is involved. The opt-in check against the installed binaries and models
(``SAURI_RUN_NATIVE_TESTS=1``) lives in ``tests/native/test_local_model_native.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import sys
import time
from contextlib import nullcontext
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.local_models_support import BIG, SMALL, catalog_entry, install_model, route_header, write_catalog

MODULE_PATH = Path(__file__).resolve().parents[2] / "asr-engine" / "native_main.py"
sys.path[:0] = [str(MODULE_PATH.parent), str(MODULE_PATH.parent.parent / "engine-common")]
SPEC = importlib.util.spec_from_file_location("native_asr_engine_local_model", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
native: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)

DEFAULT = catalog_entry("asr-big", "transcription", "ggml-big.bin", BIG, default=True, rank=2)
SMALLER = catalog_entry("asr-small", "transcription", "ggml-small.bin", SMALL)
FAKE_WHISPER = """#!{python}
import json, sys
argv = sys.argv
with open({log!r}, 'a') as log:
    log.write(argv[argv.index('-m') + 1] + '\\n')
document = {{"result": {{"language": "en"}}, "transcription": [{{
    "text": " hello", "offsets": {{"from": 250, "to": 1500}},
    "tokens": [{{"text": " hello", "id": 1, "p": 0.9, "offsets": {{"from": 500, "to": 700}}}}],
}}]}}
with open(argv[argv.index('-of') + 1] + '.json', 'w') as out:
    json.dump(document, out)
"""


class Setup:
    def __init__(self, tmp_path: Path, headers: dict[str, str]) -> None:
        self.models = tmp_path / "models"
        self.legacy = tmp_path / "legacy" / "ggml-large-v3-turbo-q5_0.bin"
        self.runs = tmp_path / "runs.log"
        self.headers = headers

    def models_used(self) -> list[str]:
        return self.runs.read_text().splitlines() if self.runs.exists() else []

    async def transcribe(self, route: str | None) -> httpx.Response:
        headers = {**self.headers, **({"X-Sauri-Route": route} if route else {})}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
            return await client.post(
                "/transcribe", json={"audio_ref": "synthetic/recording.wav", "language": "en"}, headers=headers
            )


class SyntheticS3:
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"Body": BytesIO(b"synthetic audio")}


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Setup:
    monkeypatch.setenv("SAURI_ASR_VAD", "off")
    monkeypatch.setenv("SAURI_ASR_SUPPRESS_NST", "off")
    monkeypatch.setenv("SAURI_ASR_VOCABULARY_FILE", str(tmp_path / "absent-vocabulary"))
    token = tmp_path / "engine_token"
    token.write_text("synthetic-token")
    key = tmp_path / "capability_key"
    key.write_bytes(b"synthetic-secret")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native, "s3_client", SyntheticS3())
    monkeypatch.setattr(native, "KeepAwake", nullcontext)
    monkeypatch.setattr(native.tempfile, "tempdir", str(tmp_path))

    def normalize(source: Path, dest: Path, **kwargs: Any) -> Any:
        dest.write_bytes(b"normalized")
        return SimpleNamespace(audio_ms=2000, seconds=0.01)

    monkeypatch.setattr(native, "normalize_to_wav", normalize)
    expires = int(time.time()) + 60
    signature = hmac.new(b"synthetic-secret", f"synthetic/recording.wav\n{expires}".encode(), hashlib.sha256)
    setup = Setup(tmp_path, {
        "Authorization": "Bearer synthetic-token",
        "X-Sauri-Recording-Capability": f"{expires}.{signature.hexdigest()}",
    })  # fmt: skip
    fake = tmp_path / "whisper-cli"
    fake.write_text(FAKE_WHISPER.format(python=sys.executable, log=str(setup.runs)))
    fake.chmod(0o700)
    setup.legacy.parent.mkdir()
    setup.legacy.write_bytes(BIG)
    monkeypatch.setattr(native, "WHISPER_CLI", str(fake))
    monkeypatch.setattr(native, "ASR_MODEL_PATH", setup.legacy)
    monkeypatch.setenv("SAURI_MODELS_DIR", str(setup.models))
    monkeypatch.setenv("SAURI_MODEL_CATALOG", str(write_catalog(tmp_path / "catalog.json", [DEFAULT, SMALLER])))
    return setup


async def test_no_header_changes_nothing(setup: Setup) -> None:
    for route in (None, route_header("local:default", process="transcription")):
        response = await setup.transcribe(route)
        assert response.status_code == 200, response.text
        assert response.json()["engine"] == {"name": "whisper.cpp", "model": native.MODEL_ID, "device": "metal"}
    assert setup.models_used() == [str(setup.legacy)] * 2


async def test_model_switch_between_two_requests(setup: Setup) -> None:
    small = install_model(setup.models, SMALLER, SMALL)
    big = install_model(setup.models, DEFAULT, BIG)
    first = await setup.transcribe(route_header("local:asr-small", process="transcription"))
    second = await setup.transcribe(route_header("local:asr-big", process="transcription"))
    third = await setup.transcribe(None)
    assert [r.status_code for r in (first, second, third)] == [200, 200, 200]
    assert setup.models_used() == [str(small), str(big), str(setup.legacy)]
    assert [first.json()["engine"]["model"], second.json()["engine"]["model"], third.json()["engine"]["model"]] == [
        "asr-small", "asr-big", native.MODEL_ID,
    ]


async def test_model_not_installed_is_refused_and_whisper_never_runs(setup: Setup, tmp_path: Path) -> None:
    before = set(tmp_path.iterdir())
    response = await setup.transcribe(route_header("local:asr-small", process="transcription"))
    assert response.status_code == 409 and response.json() == {"detail": "model_not_installed"}
    assert setup.models_used() == []
    assert set(tmp_path.iterdir()) == before


async def test_model_changed_after_install_is_refused(setup: Setup) -> None:
    install_model(setup.models, SMALLER, SMALL).write_bytes(SMALL + b"changed")
    response = await setup.transcribe(route_header("local:asr-small", process="transcription"))
    assert response.status_code == 409 and response.json() == {"detail": "model_not_verified"}
    assert setup.models_used() == []


async def test_default_model_without_manifest_uses_the_engine_file(setup: Setup) -> None:
    # The installed default predates the catalog: no manifest, but it is the engine's own verified file.
    response = await setup.transcribe(route_header("local:asr-big", process="transcription"))
    assert response.status_code == 200
    assert setup.models_used() == [str(setup.legacy)]
    assert response.json()["engine"]["model"] == "asr-big"


@pytest.mark.parametrize(
    ("route", "code"),
    [
        ("not-a-route", "route_malformed"),
        (route_header("local:missing", process="transcription"), "unknown_model"),
        (route_header("whisper-1", process="transcription", kind="openai"), "route_not_supported"),
        (route_header("local:asr-big", process="summary"), "route_capability_mismatch"),
    ],
)
async def test_invalid_routes_are_refused_before_whisper_runs(setup: Setup, route: str, code: str) -> None:
    response = await setup.transcribe(route)
    assert response.status_code == 422 and response.json() == {"detail": code}
    assert setup.models_used() == []


async def test_route_needs_the_engine_token_and_the_recording_capability(setup: Setup) -> None:
    route = route_header("local:asr-big", process="transcription")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native.app), base_url="http://test") as client:
        body = {"audio_ref": "synthetic/recording.wav"}
        assert (await client.post("/transcribe", json=body, headers={"X-Sauri-Route": route})).status_code == 401
        unauthorized = {"Authorization": "Bearer synthetic-token", "X-Sauri-Route": route}
        assert (await client.post("/transcribe", json=body, headers=unauthorized)).status_code == 403
    assert setup.models_used() == []
