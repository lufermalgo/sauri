"""#880 / P-R8: synthetic HTTP diarization failure/cancellation cleanup.

No ffmpeg process or model is run. CancelledError is injected at synchronous
boundaries, not produced by a real client disconnect. RED leftovers are removed
by fixture teardown only after the production-cleanup assertion has run.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib.util
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "native_diar_failure_cleanup", Path(__file__).resolve().parents[2] / "diar-engine/native_main.py"
)
assert SPEC is not None and SPEC.loader is not None
native = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)

AUDIO_REF = "synthetic/private-object-sentinel.webm"
TOKEN = "synthetic-engine-token-sentinel"
KEY = b"synthetic-capability-key-sentinel"
PAYLOAD = "synthetic-private-annotation-sentinel"
SIGNED_URL = "https://synthetic.invalid/audio?signature=private-url-sentinel"
FAILURE_DETAIL = f"{TOKEN} {KEY.decode()} {AUDIO_REF} {PAYLOAD} {SIGNED_URL}"


@dataclass
class Harness:
    audio_dir: Path
    headers: dict[str, str]
    calls: list[str]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Harness]:
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

    class Annotation:
        def itertracks(self, yield_label: bool = False) -> Iterator[Any]:
            assert yield_label
            calls.append("annotation")
            return iter(())

    def pipeline(path: str) -> Annotation:
        assert Path(path).is_file() and path.endswith(".webm.wav")
        calls.append("inference")
        return Annotation()

    def convert(command: list[str], **options: Any) -> None:
        assert options == {"check": True, "capture_output": True, "timeout": native.FFMPEG_TIMEOUT_SECONDS}
        assert Path(command[5]).is_file()
        calls.append("conversion")
        Path(command[-1]).write_bytes(b"synthetic-converted-not-real-audio")

    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token_path)
    monkeypatch.setattr(native, "RECORDING_CAPABILITY_KEY_PATH", key_path)
    monkeypatch.setattr(native, "MINIO_AUDIO_PREFIX", "synthetic/")
    monkeypatch.setattr(native, "MINIO_BUCKET", "synthetic-bucket")
    monkeypatch.setattr(native.tempfile, "NamedTemporaryFile", temporary_file)
    monkeypatch.setattr(native, "s3_client", SyntheticS3())
    monkeypatch.setattr(native, "diarization_pipeline", pipeline)
    monkeypatch.setattr(native.shutil, "which", lambda _: "synthetic-ffmpeg")
    monkeypatch.setattr(native.subprocess, "run", convert)
    try:
        yield Harness(audio_dir, headers, calls)
    finally:
        for path in audio_dir.iterdir():
            path.unlink()


async def post(harness: Harness) -> httpx.Response:
    transport = httpx.ASGITransport(app=native.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://synthetic") as client:
        return await client.post("/diarize", json={"audio_ref": AUDIO_REF}, headers=harness.headers)


def assert_private(caplog: pytest.LogCaptureFixture, harness: Harness, response: httpx.Response | None) -> None:
    visible = caplog.text + (response.text if response is not None else "")
    for sentinel in (TOKEN, KEY.decode(), AUDIO_REF, PAYLOAD, SIGNED_URL,
                     harness.headers["X-Sauri-Recording-Capability"]):
        assert sentinel not in visible


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["download", "conversion", "inference", "annotation"])
@pytest.mark.parametrize("cancelled", [False, True], ids=["exception", "cancelled"])
async def test_failure_cleans_original_and_wav_without_leaking_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    harness: Harness,
    stage: str,
    cancelled: bool,
) -> None:
    injected: list[str] = []
    if cancelled:
        failure: BaseException = asyncio.CancelledError(FAILURE_DETAIL)
    elif stage == "conversion":
        failure = subprocess.TimeoutExpired("synthetic-ffmpeg", 60, output=FAILURE_DETAIL, stderr=FAILURE_DETAIL)
    else:
        failure = RuntimeError(FAILURE_DETAIL)

    def fail(*args: Any, **_kwargs: Any) -> Any:
        injected.append(stage)
        if stage == "download":
            Path(args[2]).write_bytes(b"synthetic-partial-download")
        elif stage == "conversion":
            Path(args[0][-1]).write_bytes(b"synthetic-partial-conversion")
        else:
            assert len(list(harness.audio_dir.iterdir())) == 2
        raise failure

    if stage == "download":
        monkeypatch.setattr(native.s3_client, "download_file", fail)
    elif stage == "conversion":
        monkeypatch.setattr(native.subprocess, "run", fail)
    elif stage == "inference":
        monkeypatch.setattr(native, "diarization_pipeline", fail)
    else:
        class BrokenAnnotation:
            itertracks = staticmethod(fail)

        monkeypatch.setattr(native, "diarization_pipeline", lambda _: BrokenAnnotation())

    response = None
    if cancelled:
        with pytest.raises(asyncio.CancelledError) as caught:
            await post(harness)
        assert caught.value is failure
    else:
        response = await post(harness)
        assert response.status_code == 500
        detail = {"download": "Audio download failed", "conversion": "Audio conversion failed"}.get(
            stage, "Diarization failed"
        )
        assert response.json() == {"detail": detail}
    assert injected == [stage]
    assert_private(caplog, harness, response)
    assert list(harness.audio_dir.iterdir()) == [], f"temporary audio retained after {stage}"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_kind", ["exit", "oserror"])
async def test_other_ffmpeg_failures_clean_partial_wav_and_original(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    harness: Harness,
    error_kind: str,
) -> None:
    def fail(command: list[str], **_kwargs: Any) -> None:
        Path(command[-1]).write_bytes(b"synthetic-partial-conversion")
        if error_kind == "exit":
            raise subprocess.CalledProcessError(1, command, output=FAILURE_DETAIL, stderr=FAILURE_DETAIL)
        raise OSError(FAILURE_DETAIL)

    monkeypatch.setattr(native.subprocess, "run", fail)
    response = await post(harness)
    assert response.status_code == 500
    assert response.json() == {"detail": "Audio conversion failed"}
    assert_private(caplog, harness, response)
    assert harness.calls == ["download"]
    assert list(harness.audio_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_success_control_cleans_both_files_without_logging_auxiliaries(
    caplog: pytest.LogCaptureFixture, harness: Harness
) -> None:
    response = await post(harness)
    assert response.status_code == 200
    assert response.json() == {"segments": [], "num_speakers": 0}
    assert harness.calls == ["download", "conversion", "inference", "annotation"]
    assert_private(caplog, harness, response)
    assert list(harness.audio_dir.iterdir()) == []
