"""Local models: verified installation against a fake download server, security and in-use removal.

Nothing here downloads a real model: a loopback server serves a small synthetic "model" whose hash the
test catalog declares. Property 10: after any sequence of installs, cancellations and failures the final
file exists if and only if its SHA-256 is the catalog one, no ``.part`` remains and at most one job runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import random
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import hardware
import local_models
import pytest
from conftest import MANAGEMENT_TOKEN
from fastapi.testclient import TestClient
from hardware import detect_hardware
from sauri_engine_common.recommend import parse_catalog

AUTH = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}
PAYLOAD = random.Random(7).randbytes(700_000)
BIG_PAYLOAD = random.Random(8).randbytes(1_500_000)
HF_TOKEN = "hf_synthetictokenvalue123456"
REVISION = "a" * 40
NEEDED = len(PAYLOAD) * 12 // 10  # size x 1.2
MODEL_ID, OTHER_ID, VAD_ID, ENGINE_ID = "test-asr", "test-asr-small", "test-vad", "test-senko"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entry(model_id: str, process: str, file: str, data: bytes, **extra: Any) -> dict[str, Any]:
    return {
        "id": model_id, "process": process, "kind": "model", "engine": "whisper.cpp", "repo": "test/repo",
        "revision": REVISION, "file": file, "size": len(data), "sha256": sha(data), "min_ram_gib": 4,
        "requires": [], "rank": 1, "status": "measured", "default": False, **extra,
    }  # fmt: skip


CATALOG_RAW = {
    "catalog_version": 1,
    "models": [
        entry(MODEL_ID, "transcription", "model.bin", PAYLOAD, default=True, rank=2),
        entry(OTHER_ID, "transcription", "small.bin", BIG_PAYLOAD),
        entry(VAD_ID, "transcription", "vad.bin", b"v" * 1000, kind="auxiliary", default=True, rank=0),
        {
            "id": ENGINE_ID, "process": "diarization", "kind": "managed_engine", "engine": "senko",
            "repo": "test/senko", "revision": REVISION, "managed_by": "scripts/engines/install-diar-engine.sh",
            "min_ram_gib": 0, "requires": [], "rank": 1, "status": "measured", "default": True,
        },
    ],
}  # fmt: skip


class FakeHub:
    """A loopback download server with scriptable failures."""

    def __init__(self) -> None:
        self.payloads = {"model.bin": PAYLOAD, "small.bin": BIG_PAYLOAD, "vad.bin": b"v" * 1000}
        self.mode = "normal"
        self.cut_after = 200_000
        self.cut_once = True
        self.requests: list[dict[str, str | None]] = []
        self.lock = threading.Lock()
        hub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                hub.handle(self)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def seen(self, prefix: str) -> list[dict[str, str | None]]:
        return [request for request in self.requests if (request["path"] or "").startswith(prefix)]

    def handle(self, handler: BaseHTTPRequestHandler) -> None:
        path = handler.path
        with self.lock:
            self.requests.append(
                {"path": path, "range": handler.headers.get("Range"), "auth": handler.headers.get("Authorization")}
            )
        name = path.rsplit("/", 1)[-1]
        if self.mode == "not_found" or name not in self.payloads:
            self.send(handler, 404, b"missing")
            return
        data = self.payloads[name]
        if path.startswith(f"/test/repo/resolve/{REVISION}/") and self.mode in (
            "redirect_ok",
            "redirect_to_other_host",
        ):
            target = "/cdn/" + name
            if self.mode == "redirect_to_other_host":
                target = f"http://localhost:{self.port}/cdn/{name}"
            handler.send_response(302)
            handler.send_header("Location", target)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        if self.mode == "tampered":
            data = bytes(b ^ 1 for b in data[:100]) + data[100:]
        if self.mode == "too_big":
            data = data + b"x" * 10
        if self.mode == "cut_zero":
            handler.send_response(200)
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            self.cut(handler)
            return
        start, status = 0, 200
        range_header = handler.headers.get("Range")
        if range_header and self.mode != "ignore_range":
            start, status = int(range_header.split("=")[1].rstrip("-")), 206
        body = data[start:]
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        handler.end_headers()
        if self.mode == "slow":
            self.stream_slowly(handler, body)
        elif self.mode == "cut" and self.cut_once:
            self.cut_once = False
            handler.wfile.write(body[: self.cut_after])
            self.cut(handler)
        else:
            handler.wfile.write(body)

    def send(self, handler: BaseHTTPRequestHandler, status: int, body: bytes) -> None:
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def cut(self, handler: BaseHTTPRequestHandler) -> None:
        handler.wfile.flush()
        handler.close_connection = True
        handler.connection.shutdown(socket.SHUT_RDWR)

    def stream_slowly(self, handler: BaseHTTPRequestHandler, body: bytes) -> None:
        try:
            for offset in range(0, len(body), 16384):
                handler.wfile.write(body[offset : offset + 16384])
                handler.wfile.flush()
                time.sleep(0.03)
        except OSError:
            return


@pytest.fixture
def hub() -> Iterator[FakeHub]:
    fake = FakeHub()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


def loopback_policy(hub: FakeHub, token_hosts: tuple[str, ...] = ("127.0.0.1",)) -> local_models.DownloadPolicy:
    return local_models.DownloadPolicy(
        base_url=hub.base, scheme="http", host_suffixes=("127.0.0.1", "localhost"), ports=None, token_hosts=token_hosts
    )


@pytest.fixture
def service(tmp_path: Path, hub: FakeHub, monkeypatch: pytest.MonkeyPatch) -> Iterator[local_models.LocalModelService]:
    monkeypatch.setattr(local_models, "RETRY_DELAY_S", 0.0)
    svc = local_models.LocalModelService(
        models_dir=tmp_path / "models",
        catalog=parse_catalog(CATALOG_RAW),
        policy=loopback_policy(hub),
        token_path=tmp_path / "hf_token",
    )
    monkeypatch.setattr(local_models, "_service", svc)
    yield svc


@pytest.fixture
def client(host: ModuleType, service: local_models.LocalModelService) -> Iterator[TestClient]:
    with TestClient(host.app, base_url="http://127.0.0.1:8005", raise_server_exceptions=False) as test_client:
        yield test_client


def post(client: TestClient, path: str) -> Any:
    return client.post(path, headers=AUTH)


def wait_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/v1/local/jobs/{job_id}", headers=AUTH).json()
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def install(client: TestClient, model_id: str = MODEL_ID) -> dict[str, Any]:
    response = post(client, f"/v1/local/models/{model_id}/install")
    assert response.status_code == 202, response.text
    return wait_job(client, response.json()["id"])


def files(service: local_models.LocalModelService) -> list[str]:
    return sorted(path.name for path in service.models_dir.iterdir()) if service.models_dir.exists() else []


def model_view(client: TestClient, model_id: str) -> dict[str, Any]:
    models = client.get("/v1/local/models", headers=AUTH).json()["models"]
    return next(model for model in models if model["id"] == model_id)


# --- installation -----------------------------------------------------------------------------------


def test_install_writes_the_file_manifest_and_reports_progress(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    job = install(client)
    assert job["state"] == "done" and job["result"] == "installed" and job["error"] is None
    assert job["bytes_done"] == job["bytes_total"] == len(PAYLOAD)
    assert (service.models_dir / "model.bin").read_bytes() == PAYLOAD
    assert files(service) == ["model.bin", "model.bin.manifest.json"]
    manifest = json.loads((service.models_dir / "model.bin.manifest.json").read_text())
    info = (service.models_dir / "model.bin").stat()
    assert manifest["sha256"] == sha(PAYLOAD) and manifest["size"] == len(PAYLOAD)
    assert manifest["mtime_ns"] == info.st_mtime_ns and manifest["installed_at"] and manifest["revision"] == REVISION
    view = model_view(client, MODEL_ID)
    assert view["state"] == "installed" and view["installed_size"] == len(PAYLOAD)
    assert hub.seen(f"/test/repo/resolve/{REVISION}/model.bin")


def test_a_tampered_download_is_rejected_and_leaves_nothing(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.mode = "tampered"
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "hash_mismatch"
    assert files(service) == []
    assert model_view(client, MODEL_ID)["state"] == "not_installed"
    hub.mode = "normal"
    assert install(client)["state"] == "done"


def test_a_cut_connection_resumes_with_a_range_request(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.mode = "cut"
    job = install(client)
    assert job["state"] == "done"
    assert (service.models_dir / "model.bin").read_bytes() == PAYLOAD
    ranges = [request["range"] for request in hub.seen(f"/test/repo/resolve/{REVISION}/model.bin")]
    assert ranges[0] is None and ranges[1] == f"bytes={hub.cut_after}-"
    assert files(service) == ["model.bin", "model.bin.manifest.json"]


def test_a_connection_that_never_delivers_fails_and_removes_the_partial_file(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_models, "MAX_ATTEMPTS", 2)
    hub.mode = "cut_zero"
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "connection_lost"
    assert files(service) == []
    assert post(client, f"/v1/local/models/{MODEL_ID}/verify").status_code == 404


def test_a_preexisting_partial_file_is_resumed_and_hashed(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    service.models_dir.mkdir()
    (service.models_dir / "model.bin.part").write_bytes(PAYLOAD[:300_000])
    job = install(client)
    assert job["state"] == "done"
    assert hub.seen("/test/repo")[0]["range"] == "bytes=300000-"
    assert (service.models_dir / "model.bin").read_bytes() == PAYLOAD


def test_a_corrupt_partial_file_fails_the_hash_check_and_is_removed(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    service.models_dir.mkdir()
    (service.models_dir / "model.bin.part").write_bytes(b"\x00" * 300_000)
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "hash_mismatch"
    assert files(service) == []


def test_a_server_that_ignores_range_restarts_the_file(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.mode = "ignore_range"
    service.models_dir.mkdir()
    (service.models_dir / "model.bin.part").write_bytes(PAYLOAD[:300_000])
    assert install(client)["state"] == "done"
    assert (service.models_dir / "model.bin").read_bytes() == PAYLOAD


def test_cancel_removes_the_partial_file_and_frees_the_slot(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.mode = "slow"
    started = post(client, f"/v1/local/models/{OTHER_ID}/install").json()
    deadline = time.monotonic() + 10
    while client.get(f"/v1/local/jobs/{started['id']}", headers=AUTH).json()["bytes_done"] == 0:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert (service.models_dir / "small.bin.part").exists()
    cancelled = post(client, f"/v1/local/jobs/{started['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
    assert files(service) == []
    assert post(client, f"/v1/local/jobs/{started['id']}/cancel").status_code == 409
    hub.mode = "normal"
    assert install(client)["state"] == "done"


def test_a_second_install_while_one_runs_is_a_409(client: TestClient, hub: FakeHub) -> None:
    hub.mode = "slow"
    first = post(client, f"/v1/local/models/{OTHER_ID}/install").json()
    second = post(client, f"/v1/local/models/{MODEL_ID}/install")
    assert second.status_code == 409 and second.json()["error"] == {"code": "job_active", "job_id": first["id"]}
    assert post(client, f"/v1/local/models/{OTHER_ID}/verify").status_code == 409
    assert client.get("/v1/local/models", headers=AUTH).json()["active_job"] == first["id"]
    assert post(client, f"/v1/local/jobs/{first['id']}/cancel").json()["state"] == "cancelled"
    assert client.get("/v1/local/models", headers=AUTH).json()["active_job"] is None


def test_insufficient_disk_is_refused_before_any_download(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_models, "disk_free_bytes", lambda _path: NEEDED - 1)
    response = post(client, f"/v1/local/models/{MODEL_ID}/install")
    assert response.status_code == 507 and response.json()["error"]["code"] == "insufficient_disk"
    assert response.json()["error"]["needed_bytes"] == NEEDED
    assert files(service) == [] and hub.requests == []
    monkeypatch.setattr(local_models, "disk_free_bytes", lambda _path: NEEDED)
    assert install(client)["state"] == "done"


def test_installing_an_installed_model_is_a_409_and_a_managed_engine_cannot_be_installed(client: TestClient) -> None:
    assert install(client)["state"] == "done"
    again = post(client, f"/v1/local/models/{MODEL_ID}/install")
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_installed"
    engine = post(client, f"/v1/local/models/{ENGINE_ID}/install")
    assert engine.status_code == 409 and engine.json()["error"]["code"] == "managed_engine"
    assert engine.json()["error"]["managed_by"] == "scripts/engines/install-diar-engine.sh"


def test_http_errors_and_oversized_bodies_are_failures_without_residue(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.mode = "not_found"
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "download_not_found"
    hub.mode = "too_big"
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "size_mismatch"
    assert files(service) == []


# --- security ---------------------------------------------------------------------------------------


def test_a_redirect_to_another_host_is_refused(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    service.policy = local_models.DownloadPolicy(
        base_url=hub.base, scheme="http", host_suffixes=("127.0.0.1",), ports=None, token_hosts=("127.0.0.1",)
    )
    hub.mode = "redirect_to_other_host"
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "redirect_not_allowed"
    assert hub.seen("/cdn") == [] and files(service) == []


def test_an_allowed_redirect_works_and_the_token_never_follows_it(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    service.token_path.write_text(HF_TOKEN + "\n")
    hub.mode = "redirect_to_other_host"
    job = install(client)
    assert job["state"] == "done"
    first, cdn = hub.seen("/test/repo")[0], hub.seen("/cdn")[0]
    assert first["auth"] == f"Bearer {HF_TOKEN}" and cdn["auth"] is None
    assert HF_TOKEN not in caplog.text and HF_TOKEN not in json.dumps(job)
    assert HF_TOKEN not in client.get("/v1/local/models", headers=AUTH).text


def test_an_invalid_token_file_is_ignored(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    service.token_path.write_text("not a token\nwith lines")
    assert install(client)["state"] == "done"
    assert hub.seen("/test/repo")[0]["auth"] is None


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://huggingface.co/a/b/resolve/c/d.bin", True),
        ("https://cdn-lfs.huggingface.co/x?y=1", True),
        ("https://us.aws.cdn.hf.co/xet-bridge-us/abc", True),
        ("https://hf.co/x", True),
        ("http://huggingface.co/x", False),
        ("https://huggingface.co.evil.com/x", False),
        ("https://evilhuggingface.co/x", False),
        ("https://evil.com/huggingface.co", False),
        ("https://huggingface.co@evil.com/x", False),
        ("https://user:pw@huggingface.co/x", False),
        ("https://huggingface.co:8443/x", False),
        ("https://127.0.0.1/x", False),
        ("file:///etc/passwd", False),
        ("//huggingface.co/x", False),
        ("", False),
    ],
)
def test_the_default_policy_allows_only_https_hugging_face_hosts(url: str, allowed: bool) -> None:
    assert local_models.DownloadPolicy().allows(url) is allowed


def test_the_token_goes_only_to_the_hugging_face_origin() -> None:
    policy = local_models.DownloadPolicy()
    assert policy.sends_token("https://huggingface.co/x")
    assert not policy.sends_token("https://us.aws.cdn.hf.co/x")
    assert not policy.sends_token("http://huggingface.co/x")


def test_the_download_url_comes_only_from_the_catalog(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    model = service.catalog.get(MODEL_ID)
    assert model is not None
    assert service.policy.url_for(model).endswith(f"/test/repo/resolve/{REVISION}/model.bin")
    assert post(client, f"/v1/local/models/{MODEL_ID}/install?url=https://evil.example/x").status_code == 422
    for bad in ("unknown", "..%2F..%2Fetc%2Fpasswd", "%2e%2e"):
        assert post(client, f"/v1/local/models/{bad}/install").status_code == 404
    assert (
        client.post(
            f"/v1/local/models/{MODEL_ID}/install", headers=AUTH, json={"url": "https://evil.example/x"}
        ).status_code
        == 202
    )


def test_the_routes_require_the_management_token(client: TestClient) -> None:
    for method, path in [
        ("GET", "/v1/hardware"),
        ("GET", "/v1/local/models"),
        ("POST", f"/v1/local/models/{MODEL_ID}/install"),
        ("POST", f"/v1/local/models/{MODEL_ID}/verify"),
        ("DELETE", f"/v1/local/models/{MODEL_ID}"),
        ("GET", "/v1/local/jobs/" + "0" * 32),
        ("POST", "/v1/local/jobs/" + "0" * 32 + "/cancel"),
    ]:
        assert client.request(method, path).status_code == 401
        assert client.request(method, path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_a_symlinked_partial_file_is_refused(
    client: TestClient, service: local_models.LocalModelService, tmp_path: Path
) -> None:
    service.models_dir.mkdir()
    target = tmp_path / "elsewhere"
    target.write_bytes(b"keep")
    (service.models_dir / "model.bin.part").symlink_to(target)
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "unsafe_path"
    assert target.read_bytes() == b"keep"


# --- verification -----------------------------------------------------------------------------------


def test_verify_marks_a_modified_file_corrupt_and_a_good_one_verified(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client)["state"] == "done"
    final = service.models_dir / "model.bin"
    good = wait_job(client, post(client, f"/v1/local/models/{MODEL_ID}/verify").json()["id"])
    assert good["state"] == "done" and good["result"] == "verified" and good["bytes_done"] == len(PAYLOAD)
    data = bytearray(PAYLOAD)
    data[10] ^= 1
    final.write_bytes(bytes(data))
    assert model_view(client, MODEL_ID)["state"] == "unverified"  # mtime changed: gateways must not trust it
    bad = wait_job(client, post(client, f"/v1/local/models/{MODEL_ID}/verify").json()["id"])
    assert bad["result"] == "corrupt" and model_view(client, MODEL_ID)["state"] == "corrupt"
    assert install(client)["state"] == "done"  # a corrupt model can be reinstalled
    assert model_view(client, MODEL_ID)["state"] == "installed"


def test_verify_adopts_an_existing_file_without_a_manifest(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    service.models_dir.mkdir()
    (service.models_dir / "model.bin").write_bytes(PAYLOAD)
    assert model_view(client, MODEL_ID)["state"] == "unverified"
    assert post(client, f"/v1/local/models/{MODEL_ID}/install").status_code == 409
    assert wait_job(client, post(client, f"/v1/local/models/{MODEL_ID}/verify").json()["id"])["result"] == "verified"
    assert model_view(client, MODEL_ID)["state"] == "installed"


def test_verify_requires_an_installed_model(client: TestClient) -> None:
    assert post(client, f"/v1/local/models/{MODEL_ID}/verify").status_code == 404
    assert post(client, "/v1/local/models/nope/verify").status_code == 404
    assert client.get("/v1/local/jobs/not-a-job", headers=AUTH).status_code == 404


# --- removal and "in use" ---------------------------------------------------------------------------


def select(service: local_models.LocalModelService, content: str) -> None:
    service.models_dir.mkdir(exist_ok=True)
    (service.models_dir / local_models.SELECTION_FILE).write_text(content)


def test_the_default_model_in_use_cannot_be_removed(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client)["state"] == "done"
    refused = client.delete(f"/v1/local/models/{MODEL_ID}", headers=AUTH)
    assert refused.status_code == 409
    assert refused.json()["error"] == {"code": "model_in_use", "processes": ["transcription"]}
    assert (service.models_dir / "model.bin").exists()
    assert model_view(client, MODEL_ID)["in_use_by"] == ["transcription"]


def test_a_model_chosen_for_a_process_is_in_use_and_the_replaced_default_is_free(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client)["state"] == "done" and install(client, OTHER_ID)["state"] == "done"
    select(service, json.dumps({"transcription": OTHER_ID}))
    refused = client.delete(f"/v1/local/models/{OTHER_ID}", headers=AUTH)
    assert refused.status_code == 409 and refused.json()["error"]["processes"] == ["transcription"]
    removed = client.delete(f"/v1/local/models/{MODEL_ID}", headers=AUTH)
    assert removed.status_code == 204
    assert files(service) == ["selection.json", "small.bin", "small.bin.manifest.json"]
    assert client.delete(f"/v1/local/models/{MODEL_ID}", headers=AUTH).status_code == 404


def test_a_model_that_is_not_selected_and_not_default_can_be_removed(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client, OTHER_ID)["state"] == "done"
    assert client.delete(f"/v1/local/models/{OTHER_ID}", headers=AUTH).status_code == 204
    assert files(service) == []


def test_an_unreadable_selection_marker_blocks_removal(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client, OTHER_ID)["state"] == "done"
    for content in ("{", "[1]"):
        select(service, content)
        refused = client.delete(f"/v1/local/models/{OTHER_ID}", headers=AUTH)
        assert refused.status_code == 503 and refused.json()["error"]["code"] == "selection_unreadable"
    assert (service.models_dir / "small.bin").exists()
    assert model_view(client, OTHER_ID)["state"] == "installed"  # listing still works


def test_the_auxiliary_vad_and_managed_engines_are_not_removable(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client, VAD_ID)["state"] == "done"
    assert client.delete(f"/v1/local/models/{VAD_ID}", headers=AUTH).status_code == 409
    engine = client.delete(f"/v1/local/models/{ENGINE_ID}", headers=AUTH)
    assert engine.status_code == 409 and engine.json()["error"]["code"] == "managed_engine"


def test_a_model_with_an_active_job_cannot_be_removed(client: TestClient, hub: FakeHub) -> None:
    hub.mode = "slow"
    job = post(client, f"/v1/local/models/{OTHER_ID}/install").json()
    assert client.delete(f"/v1/local/models/{OTHER_ID}", headers=AUTH).json()["error"]["code"] == "job_active"
    post(client, f"/v1/local/jobs/{job['id']}/cancel")


# --- listing and hardware ---------------------------------------------------------------------------


def test_the_listing_carries_state_recommendation_and_the_managed_engine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sauri_engine_common.recommend import HardwareProfile

    profile = HardwareProfile("arm64", 16.0, 8, True, 10**12, "Darwin")
    monkeypatch.setattr(local_models, "detect_hardware", lambda _dir: profile)
    body = client.get("/v1/local/models", headers=AUTH).json()
    by_id = {model["id"]: model for model in body["models"]}
    assert by_id[ENGINE_ID]["state"] == "managed" and by_id[MODEL_ID]["state"] == "not_installed"
    assert by_id[MODEL_ID]["recommended"] is True and by_id[OTHER_ID]["recommended"] is False
    assert body["recommendations"]["transcription"]["model_id"] == MODEL_ID
    assert body["recommendations"]["transcription"]["reason_key"] == "fits"
    assert body["recommendations"]["diarization"]["model_id"] == ENGINE_ID
    # A managed engine is never downloaded, so the plan lists only the recommended file.
    assert ENGINE_ID not in body["setup_plan"] and MODEL_ID in body["setup_plan"]
    assert "url" not in json.dumps(body) and "sha256" not in json.dumps(body)


def test_the_hardware_route_reports_the_machine(client: TestClient) -> None:
    body = client.get("/v1/hardware", headers=AUTH).json()
    assert set(body) == {"arch", "system", "memory_gib", "cores", "metal", "macos_major", "disk_free_bytes"}
    assert body["cores"] >= 1 and body["disk_free_bytes"] > 0 and isinstance(body["metal"], bool)


def test_hardware_detection_on_apple_silicon_and_intel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(hardware, "memory_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(os, "cpu_count", lambda: 10)
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    arm = detect_hardware(tmp_path / "not" / "created" / "yet")
    assert (arm.arch, arm.memory_gib, arm.cores, arm.metal) == ("arm64", 16.0, 10, True)
    assert arm.disk_free_bytes > 0 and not (tmp_path / "not").exists()
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert detect_hardware(tmp_path).metal is False
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert detect_hardware(tmp_path).metal is False


def test_memory_bytes_reads_sysctl_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="25769803776\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert hardware.memory_bytes() == 24 * 1024**3
    assert calls == [["/usr/sbin/sysctl", "-n", "hw.memsize"]]
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    assert hardware.memory_bytes() == 0


def test_the_shipped_catalog_loads_through_the_service(host: ModuleType, tmp_path: Path) -> None:
    svc = local_models.LocalModelService(models_dir=tmp_path / "models")
    assert {model.id for model in svc.catalog.models} >= {"whisper-large-v3-turbo-q5_0", "senko-coreml"}
