"""Opt-in real Senko/CoreML inference; only storage and credentials are synthetic."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SAURI_RUN_NATIVE_TESTS") != "1", reason="Set SAURI_RUN_NATIVE_TESTS=1 for CoreML inference",
)


def test_synthetic_diarization_v2(tmp_path: Path) -> None:
    backend = Path(__file__).resolve().parents[2]
    python = Path(os.environ.get(
        "SAURI_DIAR_ENGINE_PYTHON", "~/.local/share/sauri/native-engines/diar-venv/bin/python",
    )).expanduser()
    if not python.is_file():
        pytest.skip("Senko installer venv not provisioned; run install-diar-engine.sh")
    provisioned = subprocess.run(
        [str(python), "-c", "import importlib.util; import sys; "
         "sys.exit(not all(importlib.util.find_spec(name) for name in "
         "('senko', 'fastapi', 'boto3', 'uvicorn', 'pydantic')))"],
        capture_output=True, timeout=30,
    )
    if provisioned.returncode:
        pytest.skip("Configured diarization venv is missing Senko or native service dependencies")
    work = tmp_path / "job"
    work.mkdir()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(work),
           "SAURI_ENGINE_TOKEN_FILE": str(work / "token"),
           "SAURI_RECORDING_CAPABILITY_KEY_FILE": str(work / "capability"),
           "MPLCONFIGDIR": str(work / "mpl"), "XDG_CACHE_HOME": str(work / "cache")}
    script = r'''
import sys
from pathlib import Path
backend, work = map(Path, sys.argv[1:])
sys.path[:0] = [str(backend / "engine-common"), str(backend / "diar-engine")]
import hashlib
import hmac
import shutil
import subprocess
import time
import asyncio
import http.client
import json
import socket
import uvicorn
import native_main as native

source = work / "tone.wav"
subprocess.run([
    "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
    "sine=frequency=440:duration=15", "-af", "apad=pad_dur=15",
    "-ac", "2", "-ar", "44100", str(source),
], check=True)
native.ENGINE_TOKEN_PATH.write_text("synthetic-token")
secret = b"synthetic-capability-key"
native.RECORDING_CAPABILITY_KEY_PATH.write_bytes(secret)
paths = []
class SyntheticStore:
    def download_file(self, bucket, key, filename):
        assert key == "recordings/synthetic.wav"
        paths.extend([Path(filename), Path(filename + ".wav")])
        shutil.copyfile(source, filename)

def request(port):
    expiry = int(time.time()) + 60
    signature = hmac.new(secret, f"recordings/synthetic.wav\n{expiry}".encode(), hashlib.sha256).hexdigest()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        connection.request("POST", "/diarize",
            body=json.dumps({"audio_ref": "recordings/synthetic.wav", "contract_version": 2}),
            headers={"Content-Type": "application/json", "Authorization": "Bearer synthetic-token",
                     "X-Sauri-Recording-Capability": f"{expiry}.{signature}"})
        response = connection.getresponse()
        body = response.read()
        assert response.status == 200, body
        return json.loads(body)
    finally:
        connection.close()

async def check():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(native.app, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        while not server.started:
            if task.done():
                await task
                raise AssertionError("Native service failed to start")
            await asyncio.sleep(0.05)
        native.s3_client = SyntheticStore()
        data = await asyncio.to_thread(request, listener.getsockname()[1])
        assert data["contract_version"] == 2
        assert data["engine"] == {"name": "senko", "model": "senko-coreml", "device": "coreml"}
        assert abs(data["diagnostics"]["audio_ms"] - 30000) <= 100
        assert data["speaker_count"] == len({s["speaker"] for s in data["segments"]})
        for segment in data["segments"]:
            assert 0 <= segment["start_ms"] <= segment["end_ms"] <= 30100
        assert paths and all(not path.exists() for path in paths)
        assert source.exists()
    finally:
        server.should_exit = True
        await task
        listener.close()
asyncio.run(check())
'''
    try:
        result = subprocess.run(
            [str(python), "-c", script, str(backend), str(work)],
            env=env, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        import shutil

        shutil.rmtree(work)
    assert not work.exists()
