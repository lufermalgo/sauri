"""#880 / P-R8: synthetic HTTP failures must not retain audio or leak payloads.

CancelledError is injected at synchronous boundaries; this is not a socket
 disconnect test, real inference, or proof of managed-memory zeroization.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_asr_failure_cleanup", Path(__file__).resolve().parents[2] / "asr-engine/native_main.py"
)
assert SPEC is not None and SPEC.loader is not None
native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)

AUDIO_REF = "synthetic/private-object-sentinel.webm"
TOKEN = "synthetic-engine-token-sentinel"
KEY = b"synthetic-capability-key-sentinel"
PAYLOAD = "synthetic-private-transcript-sentinel"
SIGNED_URL = "https://synthetic.invalid/audio?signature=private-url-sentinel"
FAILURE_DETAIL = f"{TOKEN} {KEY.decode()} {AUDIO_REF} {PAYLOAD} {SIGNED_URL}"


@dataclass
class Harness:
    audio_dir: Path
    headers: dict[str, str]
    calls: list[str]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Harness]:
    """Use real auth and download cleanup, but never access a store or model."""
    token_path = tmp_path / "token"
    token_path.write_text(TOKEN, encoding="utf-8")
    key_path = tmp_path / "key"
    key_path.write_bytes(KEY)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    expires = int(time.time()) + 60
    signature = hmac.new(KEY, f"{AUDIO_REF}\n{expires}".encode(), hashlib.sha256).hexdigest()
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "X-Sauri-Recording-Capability": f"{expires}.{signature}",
    }
    calls: list[str] = []
    original_temporary_file = native.tempfile.NamedTemporaryFile

    def temporary_file(*args: Any, **kwargs: Any) -> Any:
        return original_temporary_file(*args, **{**kwargs, "dir": audio_dir})

    class SyntheticS3:
        def download_file(self, bucket: str, audio_ref: str, path: str) -> None:
            assert bucket == "synthetic-bucket" and audio_ref == AUDIO_REF
            calls.append("download")
            Path(path).write_bytes(b"synthetic-source-not-real-audio")

    def detect_speech(path: str) -> tuple[str, list[tuple[int, int]], int]:
        assert Path(path).is_file()
        calls.append("vad")
        return PAYLOAD, [(0, 1000)], 1000

    def transcribe_audio(audio: Any, **_kwargs: Any) -> dict[str, Any]:
        assert audio == PAYLOAD
        calls.append("inference")
        return {"segments": [{"text": PAYLOAD, "start": 0.0, "end": 1.0}], "language": "es"}

    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", temporary_file)
    monkeypatch.setattr(native, "s3_client", SyntheticS3())
    monkeypatch.setattr(native, "ACOUSTIC_VALIDATION_ENABLED", True)
    monkeypatch.setattr(native, "_detect_speech", detect_speech)
    monkeypatch.setattr(native, "transcribe_audio", transcribe_audio)
    try:
        yield Harness(audio_dir, headers, calls)
    finally:
        # Contain RED tests: assertions run before removal of our own leftovers.
        for path in audio_dir.iterdir():
            path.unlink()


async def post(harness: Harness) -> httpx.Response:
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://synthetic") as client:
        return await client.post("/transcribe", json={"audio_ref": AUDIO_REF}, headers=harness.headers)


def assert_private(caplog: pytest.LogCaptureFixture, harness: Harness, response: httpx.Response | None) -> None:
    visible = caplog.text + (response.text if response is not None else "")
    for sentinel in (TOKEN, KEY.decode(), AUDIO_REF, PAYLOAD, SIGNED_URL,
                     harness.headers["X-Sauri-Recording-Capability"]):
        assert sentinel not in visible


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["download", "vad", "inference", "admission"])
@pytest.mark.parametrize("cancelled", [False, True], ids=["exception", "cancelled"])
async def test_failure_cleans_audio_and_keeps_errors_private(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    harness: Harness,
    stage: str,
    cancelled: bool,
) -> None:
    """Exercise the HTTP handler, including partial writes and BaseException."""
    injected: list[str] = []
    failure: BaseException = asyncio.CancelledError(FAILURE_DETAIL) if cancelled else RuntimeError(FAILURE_DETAIL)

    def fail(*args: Any, **_kwargs: Any) -> Any:
        injected.append(stage)
        if stage == "download":
            Path(args[2]).write_bytes(b"synthetic-partial-download")
        else:
            assert any(harness.audio_dir.iterdir())
        raise failure

    if stage == "download":
        monkeypatch.setattr(native.s3_client, "download_file", fail)
    else:
        target = {"vad": "_detect_speech", "inference": "transcribe_audio", "admission": "_admit_segments"}[stage]
        monkeypatch.setattr(native, target, fail)

    response = None
    if cancelled:
        with pytest.raises(asyncio.CancelledError) as caught:
            await post(harness)
        assert caught.value is failure
    else:
        response = await post(harness)
        assert response.status_code == 500
        detail = "Audio download failed" if stage == "download" else "Transcription failed"
        assert response.json() == {"detail": detail}
    assert injected == [stage]
    assert_private(caplog, harness, response)
    assert list(harness.audio_dir.iterdir()) == [], f"temporary audio retained after {stage}"


@pytest.mark.asyncio
async def test_success_control_cleans_audio_without_logging_auxiliaries(
    caplog: pytest.LogCaptureFixture, harness: Harness
) -> None:
    response = await post(harness)
    assert response.status_code == 200
    assert response.json() == {
        "segments": [{"text": PAYLOAD, "start_ms": 0, "end_ms": 1000}], "language": "es"
    }
    assert harness.calls == ["download", "vad", "inference"]
    # Transcript in the successful ASR envelope is allowed; not in logs.
    assert_private(caplog, harness, None)
    assert list(harness.audio_dir.iterdir()) == []
