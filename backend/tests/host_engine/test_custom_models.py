"""Custom models from Hugging Face ("Other"): source parsing, resolution, verified install, registry and removal.

Nothing here reaches the Internet: a loopback server plays the Hugging Face API (``/api/models/...``) and the
download host (``/{repo}/resolve/{sha}/{path}``) with synthetic files whose LFS metadata it declares.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import hf_custom
import local_models
import pytest
from conftest import MANAGEMENT_TOKEN
from fastapi.testclient import TestClient
from sauri_engine_common.recommend import parse_catalog

AUTH = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}
SHA = "c" * 40
GGUF = random.Random(11).randbytes(300_000)
GGML = random.Random(12).randbytes(200_000)
REPO = "someone/tiny-gguf"
ASR_REPO = "someone/tiny-whisper"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lfs_file(path: str, data: bytes) -> dict[str, Any]:
    return {"type": "file", "path": path, "size": len(data), "oid": "1" * 40,
            "lfs": {"oid": sha256(data), "size": len(data), "pointerSize": 134}}  # fmt: skip


CATALOG = parse_catalog({
    "catalog_version": 1,
    "models": [{
        "id": "catalog-llm", "process": "summary", "kind": "model", "engine": "llama.cpp", "repo": "test/repo",
        "revision": "a" * 40, "file": "llm.gguf", "size": 10, "sha256": "0" * 64, "min_ram_gib": 4,
        "requires": [], "rank": 1, "status": "measured", "default": True,
    }],
})  # fmt: skip


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionError):  # a client closing its kept-alive connection
            super().handle_error(request, client_address)


class FakeHub:
    """Hugging Face API and download host on loopback; each repository's answers are scriptable."""

    def __init__(self) -> None:
        self.info: dict[str, tuple[int, dict[str, str], Any]] = {
            REPO: (200, {}, {"sha": SHA, "gated": False, "cardData": {"license": "apache-2.0"}}),
            ASR_REPO: (200, {}, {"sha": SHA, "gated": False, "tags": ["license:mit"]}),
        }
        self.trees: dict[str, list[Any]] = {
            REPO: [
                lfs_file("model-Q4_K_M.gguf", GGUF),
                lfs_file("sub/model-Q8_0.gguf", GGUF[:1000]),
                lfs_file("big-00001-of-00002.gguf", GGUF),
                lfs_file("mmproj-f16.gguf", GGUF),
                lfs_file("ggml-tiny.bin", GGML),
                lfs_file("huge.gguf", GGUF) | {"lfs": {"oid": "2" * 64, "size": (20 << 30) + 1}},
                {"type": "file", "path": "plain.gguf", "size": 10, "oid": "3" * 40},  # no LFS metadata
                {"type": "file", "path": "../escape.gguf", "size": 10, "lfs": {"oid": "4" * 64, "size": 10}},
                {"type": "directory", "path": "sub", "oid": "5" * 40},
                {"type": "file", "path": "README.md", "size": 10, "oid": "6" * 40},
            ],
            ASR_REPO: [lfs_file("ggml-tiny.bin", GGML), lfs_file("model.bin", GGML)],
        }
        self.blobs = {"model-Q4_K_M.gguf": GGUF, "ggml-tiny.bin": GGML, "sub/model-Q8_0.gguf": GGUF[:1000]}
        self.page_size: int | None = None
        self.tampered = False
        self.requests: list[dict[str, str | None]] = []
        self.lock = threading.Lock()
        hub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                hub.handle(self)

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def handle(self, handler: BaseHTTPRequestHandler) -> None:
        with self.lock:
            self.requests.append({"path": handler.path, "auth": handler.headers.get("Authorization")})
        parts = urlsplit(handler.path)
        path = parts.path
        if path.startswith("/api/models/"):
            rest = path[len("/api/models/") :]
            repo = "/".join(rest.split("/")[:2])
            if "/revision/" in rest:
                status, headers, body = self.info.get(repo, (404, {}, {"error": "nope"}))
                self.send_json(handler, status, body, headers)
                return
            if "/tree/" in rest:
                self.send_tree(handler, repo, parts.query)
                return
        for repo in (REPO, ASR_REPO):
            prefix = f"/{repo}/resolve/{SHA}/"
            if path.startswith(prefix) and path[len(prefix) :] in self.blobs:
                data = self.blobs[path[len(prefix) :]]
                if self.tampered:
                    data = bytes(b ^ 1 for b in data[:50]) + data[50:]
                self.send(handler, 200, data)
                return
        self.send(handler, 404, b"missing")

    def send_tree(self, handler: BaseHTTPRequestHandler, repo: str, query: str) -> None:
        entries = self.trees.get(repo)
        if entries is None:
            self.send_json(handler, 404, {"error": "nope"})
            return
        if self.page_size is None:
            self.send_json(handler, 200, entries)
            return
        start = int(query.split("cursor=")[1]) if "cursor=" in query else 0
        page = entries[start : start + self.page_size]
        headers = {}
        if start + self.page_size < len(entries):
            next_url = f"{self.base}/api/models/{repo}/tree/{SHA}?recursive=1&cursor={start + self.page_size}"
            headers["Link"] = f'<{next_url}>; rel="next"'
        self.send_json(handler, 200, page, headers)

    def send_json(
        self, handler: BaseHTTPRequestHandler, status: int, body: Any, headers: dict[str, str] | None = None
    ) -> None:
        data = json.dumps(body).encode()
        handler.send_response(status)
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def send(self, handler: BaseHTTPRequestHandler, status: int, body: bytes) -> None:
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def downloads(self) -> list[dict[str, str | None]]:
        return [request for request in self.requests if "/resolve/" in (request["path"] or "")]


@pytest.fixture
def hub() -> Iterator[FakeHub]:
    fake = FakeHub()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


def make_service(tmp_path: Path, hub: FakeHub) -> local_models.LocalModelService:
    # The token host is the fake hub itself: a custom download must still never carry the token.
    policy = local_models.DownloadPolicy(
        base_url=hub.base, scheme="http", host_suffixes=("127.0.0.1",), ports=None, token_hosts=("127.0.0.1",)
    )
    token = tmp_path / "hf_token"
    token.write_text("hf_synthetictokenvalue123456")
    return local_models.LocalModelService(
        models_dir=tmp_path / "models", catalog=CATALOG, policy=policy, token_path=token
    )


@pytest.fixture
def service(tmp_path: Path, hub: FakeHub, monkeypatch: pytest.MonkeyPatch) -> local_models.LocalModelService:
    monkeypatch.setattr(local_models, "RETRY_DELAY_S", 0.0)
    svc = make_service(tmp_path, hub)
    monkeypatch.setattr(local_models, "_service", svc)
    return svc


@pytest.fixture
def client(host: ModuleType, service: local_models.LocalModelService) -> Iterator[TestClient]:
    with TestClient(host.app, base_url="http://127.0.0.1:8005", raise_server_exceptions=False) as test_client:
        yield test_client


def resolve(client: TestClient, source: str, process: str = "summary") -> Any:
    return client.post("/v1/local/custom/resolve", headers=AUTH, json={"process": process, "source": source})


def start_install(client: TestClient, file: str = "model-Q4_K_M.gguf", **overrides: Any) -> Any:
    body = {"process": "summary", "repo": REPO, "revision": SHA, "file": file, **overrides}
    return client.post("/v1/local/custom/install", headers=AUTH, json=body)


def wait_job(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/v1/local/jobs/{job_id}", headers=AUTH).json()
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def install(client: TestClient, file: str = "model-Q4_K_M.gguf", **overrides: Any) -> dict[str, Any]:
    response = start_install(client, file, **overrides)
    assert response.status_code == 202, response.text
    return wait_job(client, response.json()["id"])


def custom_views(client: TestClient) -> list[dict[str, Any]]:
    models = client.get("/v1/local/models", headers=AUTH).json()["models"]
    return [model for model in models if model.get("custom")]


def error(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


CUSTOM_ID = "custom-" + sha256(GGUF)[:16]


# --- source parsing ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("someone/tiny-gguf", hf_custom.Source(REPO)),
        ("  someone/tiny-gguf  ", hf_custom.Source(REPO)),
        ("https://huggingface.co/someone/tiny-gguf", hf_custom.Source(REPO)),
        ("https://hf.co/someone/tiny-gguf/", hf_custom.Source(REPO)),
        ("huggingface.co/someone/tiny-gguf", hf_custom.Source(REPO)),
        ("https://huggingface.co/someone/tiny-gguf/tree/main", hf_custom.Source(REPO, "main")),
        (
            "https://huggingface.co/someone/tiny-gguf/blob/main/model-Q4_K_M.gguf",
            hf_custom.Source(REPO, "main", "model-Q4_K_M.gguf"),
        ),
        (
            f"https://huggingface.co/someone/tiny-gguf/resolve/{SHA}/sub/model-Q8_0.gguf?download=true",
            hf_custom.Source(REPO, SHA, "sub/model-Q8_0.gguf"),
        ),
    ],
)
def test_sources_that_name_a_hugging_face_repository(source: str, expected: hf_custom.Source) -> None:
    assert hf_custom.parse_source(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "https://evil.example/someone/tiny-gguf",
        "evil.example/someone/tiny-gguf",
        "https://huggingface.co.evil.example/someone/tiny-gguf",
        "https://user:pass@huggingface.co/someone/tiny-gguf",
        "https://huggingface.co:8443/someone/tiny-gguf",
    ],
)
def test_other_hosts_are_refused(source: str) -> None:
    with pytest.raises(hf_custom.CustomModelError) as refused:
        hf_custom.parse_source(source)
    assert refused.value.code == "host_not_allowed"


@pytest.mark.parametrize(
    "source",
    [
        "",
        "someone",
        "someone/tiny gguf",
        "../tiny-gguf",
        "someone/..",
        "https://huggingface.co/someone/tiny-gguf/blob/main/../../etc/passwd",
        "https://huggingface.co/someone/tiny-gguf/blob/main/%2e%2e/x.gguf",
        "https://huggingface.co/someone/tiny-gguf/discussions",
        "https://huggingface.co/datasets/someone/tiny-gguf",
        "ftp://huggingface.co/someone/tiny-gguf",
        "x" * 600,
    ],
)
def test_malformed_sources_are_refused(source: str) -> None:
    with pytest.raises(hf_custom.CustomModelError) as refused:
        hf_custom.parse_source(source)
    assert refused.value.code == "invalid_source"


def test_compatible_files_depend_on_the_process() -> None:
    assert hf_custom.compatible("summary", "model-Q4_K_M.gguf")
    assert hf_custom.compatible("summary", "sub/Model.GGUF")
    assert not hf_custom.compatible("summary", "big-00001-of-00002.gguf")
    assert not hf_custom.compatible("summary", "mmproj-f16.gguf")
    assert not hf_custom.compatible("summary", "ggml-tiny.bin")
    assert hf_custom.compatible("transcription", "ggml-tiny.bin")
    assert hf_custom.compatible("transcription", "models/ggml-large-v3-turbo-q5_0.bin")
    assert not hf_custom.compatible("transcription", "model.bin")
    assert not hf_custom.compatible("transcription", "ggml-silero-v5.1.2.bin")
    assert not hf_custom.compatible("transcription", "model-Q4_K_M.gguf")


# --- resolution -------------------------------------------------------------------------------------


def test_resolve_pins_the_commit_and_lists_lfs_files_for_summary(client: TestClient, hub: FakeHub) -> None:
    response = resolve(client, "https://huggingface.co/someone/tiny-gguf")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "repo": REPO,
        "revision": SHA,
        "license": "apache-2.0",
        "files": [
            {"path": "model-Q4_K_M.gguf", "size": len(GGUF), "sha256": sha256(GGUF)},
            {"path": "sub/model-Q8_0.gguf", "size": 1000, "sha256": sha256(GGUF[:1000])},
        ],
    }
    assert all(request["auth"] is None for request in hub.requests)  # no account, no token
    assert any(request["path"] == f"/api/models/{REPO}/tree/{SHA}?recursive=1" for request in hub.requests)


def test_resolve_for_transcription_offers_only_ggml_bins(client: TestClient) -> None:
    response = resolve(client, ASR_REPO, process="transcription")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["license"] == "mit"
    assert body["files"] == [{"path": "ggml-tiny.bin", "size": len(GGML), "sha256": sha256(GGML)}]


def test_a_file_url_resolves_only_that_file(client: TestClient) -> None:
    response = resolve(client, "https://hf.co/someone/tiny-gguf/blob/main/sub/model-Q8_0.gguf")
    assert response.status_code == 200, response.text
    assert [item["path"] for item in response.json()["files"]] == ["sub/model-Q8_0.gguf"]
    listed_but_wrong = resolve(client, "https://hf.co/someone/tiny-gguf/blob/main/ggml-tiny.bin")
    assert listed_but_wrong.status_code == 422 and error(listed_but_wrong) == "no_compatible_files"
    absent = resolve(client, "https://hf.co/someone/tiny-gguf/blob/main/absent.gguf")
    assert absent.status_code == 404 and error(absent) == "not_found"


def test_the_tree_is_followed_across_pages(client: TestClient, hub: FakeHub) -> None:
    hub.page_size = 2
    response = resolve(client, REPO)
    assert response.status_code == 200, response.text
    assert len(response.json()["files"]) == 2
    assert sum("/tree/" in (request["path"] or "") for request in hub.requests) == 5


def test_other_hosts_are_refused_by_the_route(client: TestClient, hub: FakeHub) -> None:
    response = resolve(client, "https://example.com/someone/tiny-gguf")
    assert response.status_code == 422 and error(response) == "host_not_allowed"
    assert hub.requests == []


@pytest.mark.parametrize(
    ("answer", "status", "code"),
    [
        ((200, {}, {"sha": SHA, "gated": "manual"}), 403, "gated"),
        ((200, {}, {"sha": SHA, "gated": "auto"}), 403, "gated"),
        ((401, {}, {"error": "Access restricted"}), 403, "gated"),
        ((403, {}, {"error": "Access restricted"}), 403, "gated"),
        ((401, {"X-Error-Code": "RepoNotFound"}, {"error": "Repository not found"}), 404, "not_found"),
        ((404, {}, {"error": "Revision not found"}), 404, "not_found"),
        ((500, {}, {"error": "boom"}), 503, "unreachable"),
        ((200, {}, {"sha": "not-a-commit"}), 503, "unreachable"),
    ],
)
def test_resolution_refusals(
    client: TestClient, hub: FakeHub, answer: tuple[int, dict[str, str], Any], status: int, code: str
) -> None:
    hub.info[REPO] = answer
    response = resolve(client, REPO)
    assert response.status_code == status and error(response) == code


def test_a_repository_without_compatible_files_is_refused(client: TestClient, hub: FakeHub) -> None:
    hub.trees[REPO] = [lfs_file("ggml-tiny.bin", GGML), {"type": "file", "path": "plain.gguf", "size": 3}]
    response = resolve(client, REPO)
    assert response.status_code == 422 and error(response) == "no_compatible_files"


def test_an_unreachable_hub_is_reported(client: TestClient, service: local_models.LocalModelService) -> None:
    object.__setattr__(service.policy, "base_url", "http://127.0.0.1:9")  # nothing listens on the discard port
    response = resolve(client, REPO)
    assert response.status_code == 503 and error(response) == "unreachable"


def test_an_api_redirect_to_another_host_is_not_followed(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = hub.send_json

    def redirect(
        handler: BaseHTTPRequestHandler, status: int, body: Any, headers: dict[str, str] | None = None
    ) -> None:
        if "/revision/" in handler.path:
            elsewhere = f"http://localhost:{hub.port}/api/models/x/y/revision/main"
            original(handler, 307, {}, {"Location": elsewhere})
        else:
            original(handler, status, body, headers)

    monkeypatch.setattr(hub, "send_json", redirect)
    response = resolve(client, REPO)
    assert response.status_code == 503 and error(response) == "unreachable"
    assert len(hub.requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"process": "summary"},
        {"process": "summary", "source": REPO, "extra": 1},
        {"process": "diarization", "source": REPO},
        {"process": "summary", "source": 5},
    ],
)
def test_resolve_rejects_bad_bodies(client: TestClient, body: dict[str, Any]) -> None:
    response = client.post("/v1/local/custom/resolve", headers=AUTH, json=body)
    assert response.status_code == 422


# --- installation -----------------------------------------------------------------------------------


def test_install_verifies_the_hash_and_lists_the_model_as_custom(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    job = install(client)
    assert job["state"] == "done" and job["result"] == "installed" and job["model_id"] == CUSTOM_ID, job
    assert job["bytes_done"] == job["bytes_total"] == len(GGUF)
    final = service.models_dir / "custom" / f"{sha256(GGUF)[:16]}-model-Q4_K_M.gguf"
    assert final.read_bytes() == GGUF
    assert not list(service.models_dir.rglob("*.part"))
    registry = json.loads((service.models_dir / "custom_models.json").read_text())
    assert registry["models"][0]["sha256"] == sha256(GGUF) and registry["models"][0]["revision"] == SHA
    [view] = custom_views(client)
    assert view["id"] == CUSTOM_ID and view["kind"] == "model" and view["engine"] == "llama.cpp"
    assert view["process"] == "summary" and view["recommended"] is False and view["state"] == "installed"
    assert view["availability"] == "installed" and view["license"] == "apache-2.0"
    assert view["origin"] == {"repo": REPO, "revision": SHA, "file": "model-Q4_K_M.gguf"}
    # Size and hash were read again from the hub, and no request carried the token.
    assert any("/revision/" in (request["path"] or "") for request in hub.requests)
    assert hub.downloads() and all(request["auth"] is None for request in hub.requests)


def test_a_transcription_model_gets_the_whisper_engine(client: TestClient) -> None:
    job = install(client, "ggml-tiny.bin", process="transcription", repo=ASR_REPO)
    assert job["state"] == "done", job
    [view] = custom_views(client)
    assert view["engine"] == "whisper.cpp" and view["process"] == "transcription"


def test_a_tampered_download_is_discarded(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.tampered = True
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "hash_mismatch"
    custom_dir = service.models_dir / "custom"
    assert not custom_dir.exists() or list(custom_dir.iterdir()) == []
    assert not (service.models_dir / "custom_models.json").exists()
    assert custom_views(client) == []


def test_install_does_not_start_without_enough_disk(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_models, "disk_free_bytes", lambda _path: 1000)
    response = start_install(client)
    assert response.status_code == 507 and error(response) == "insufficient_disk"
    assert response.json()["error"]["needed_bytes"] == -(-len(GGUF) * 12 // 10)
    assert hub.downloads() == []


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"revision": "main"}, "invalid_revision"),
        ({"file": "../model-Q4_K_M.gguf"}, "invalid_file"),
        ({"file": "/etc/model.gguf"}, "invalid_file"),
        ({"file": "ggml-tiny.bin"}, "no_compatible_files"),
        ({"repo": "someone"}, "invalid_source"),
        ({"process": "diarization"}, "invalid_process"),
    ],
)
def test_install_rejects_bad_fields(client: TestClient, hub: FakeHub, overrides: dict[str, Any], code: str) -> None:
    response = start_install(client, **overrides)
    assert response.status_code == 422 and error(response) == code
    assert hub.requests == []


def test_install_takes_no_size_or_hash_from_the_client(client: TestClient) -> None:
    body = {"process": "summary", "repo": REPO, "revision": SHA, "file": "model-Q4_K_M.gguf", "sha256": "0" * 64}
    response = client.post("/v1/local/custom/install", headers=AUTH, json=body)
    assert response.status_code == 422 and error(response) == "invalid_request"


def test_install_refuses_a_file_the_hub_does_not_list(client: TestClient, hub: FakeHub) -> None:
    response = start_install(client, "absent.gguf")
    assert response.status_code == 404 and error(response) == "not_found"
    assert hub.downloads() == []


def test_install_respects_the_single_job_lock(
    client: TestClient, service: local_models.LocalModelService, hub: FakeHub
) -> None:
    service._active = local_models.Job(id="f" * 32, model_id="catalog-llm", type="install", bytes_total=1)
    response = start_install(client)
    assert response.status_code == 409 and error(response) == "job_active"
    assert hub.requests == []


def test_an_installed_custom_model_is_not_installed_twice(client: TestClient) -> None:
    assert install(client)["state"] == "done"
    again = start_install(client)
    assert again.status_code == 409 and error(again) == "already_installed"


# --- persistence, verification and removal ----------------------------------------------------------


def test_the_registry_survives_a_restart_and_verify_works(
    client: TestClient, tmp_path: Path, hub: FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert install(client)["state"] == "done"
    monkeypatch.setattr(local_models, "_service", make_service(tmp_path, hub))  # a new host process
    [view] = custom_views(client)
    assert view["id"] == CUSTOM_ID and view["state"] == "installed"
    verify = client.post(f"/v1/local/models/{CUSTOM_ID}/verify", headers=AUTH)
    assert verify.status_code == 202, verify.text
    assert wait_job(client, verify.json()["id"])["result"] == "verified"


def test_remove_deletes_the_file_and_its_registry_entry(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client)["state"] == "done"
    response = client.delete(f"/v1/local/models/{CUSTOM_ID}", headers=AUTH)
    assert response.status_code == 204, response.text
    assert list((service.models_dir / "custom").iterdir()) == []
    assert json.loads((service.models_dir / "custom_models.json").read_text())["models"] == []
    assert custom_views(client) == []
    again = client.delete(f"/v1/local/models/{CUSTOM_ID}", headers=AUTH)
    assert again.status_code == 404 and error(again) == "unknown_model"


def test_a_custom_model_in_use_is_not_removed_and_shows_active(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    assert install(client)["state"] == "done"
    (service.models_dir / "selection.json").write_text(json.dumps({"summary": CUSTOM_ID}))
    [view] = custom_views(client)
    assert view["active"] is True and view["in_use_by"] == ["summary"]
    response = client.delete(f"/v1/local/models/{CUSTOM_ID}", headers=AUTH)
    assert response.status_code == 409 and error(response) == "model_in_use"


def test_tampered_registry_entries_are_ignored(client: TestClient, service: local_models.LocalModelService) -> None:
    service.models_dir.mkdir(parents=True)
    good = {"process": "summary", "repo": REPO, "revision": SHA, "path": "model-Q4_K_M.gguf", "size": len(GGUF),
            "sha256": sha256(GGUF), "license": None, "installed_at": None}  # fmt: skip
    bad = [
        good | {"path": "../../escape.gguf"},
        good | {"path": "ok/../x.gguf"},
        good | {"revision": "main"},
        good | {"size": (20 << 30) + 1},
        good | {"process": "transcription"},  # a .gguf is not a transcription model
        good | {"repo": "a/b/c"},
    ]
    (service.models_dir / "custom_models.json").write_text(json.dumps({"version": 1, "models": [*bad, good]}))
    views = custom_views(client)
    assert [view["id"] for view in views] == [CUSTOM_ID]
    assert views[0]["state"] == "not_installed" and views[0]["install"]["method"] == "download"


def test_an_unreadable_registry_does_not_break_the_listing(
    client: TestClient, service: local_models.LocalModelService
) -> None:
    service.models_dir.mkdir(parents=True)
    (service.models_dir / "custom_models.json").write_text("{not json")
    response = client.get("/v1/local/models", headers=AUTH)
    assert response.status_code == 200 and custom_views(client) == []
    install_response = start_install(client)
    assert install_response.status_code == 503 and error(install_response) == "custom_registry_unreadable"
