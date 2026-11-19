"""Downloadable components (design D9): the speaker runtime as a release archive.

A loopback server plays the configured repository's GitHub Releases with a small synthetic component. Nothing
here reaches GitHub. Covered: the host allow-list (only that repository's release path and GitHub's release-asset
host; loopback only with the test switch), the listing when no download place exists yet, a verified install that
unpacks atomically, and every refusal leaving no partial file, staging folder or half component behind.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import random
import socket
import tarfile
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import local_models
import pytest
from conftest import MANAGEMENT_TOKEN
from fastapi.testclient import TestClient
from sauri_engine_common.recommend import RELEASE_URL_TEMPLATE, parse_catalog

AUTH = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}
REPO = "owner/sauri-releases"
REVISION = "a" * 40
COMPONENT_ID, ENGINE_ID = "test-diar-runtime", "test-senko"
VERSION = "1.2.3"
ARCHIVE = f"diar-{VERSION}-mac-arm64.tar.gz"
TAG = f"diar-{VERSION}"
CONTENT = {
    "diar/pkg/__init__.py": b"VALUE = 1\n",
    "diar/pkg/weights.bin": random.Random(3).randbytes(400_000),
    "diar/tool": b"#!/bin/sh\necho ok\n",
}


def tar_gz(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return raw.getvalue()


def file_member(name: str, data: bytes, mode: int = 0o644) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(data), mode
    return info, data


def dir_member(name: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type, info.mode = tarfile.DIRTYPE, 0o755
    return info, None


def link_member(name: str, target: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type, info.linkname = tarfile.SYMTYPE, target
    return info, None


def good_members() -> list[tuple[tarfile.TarInfo, bytes | None]]:
    members: list[tuple[tarfile.TarInfo, bytes | None]] = [dir_member("diar"), dir_member("diar/pkg")]
    for name, data in CONTENT.items():
        members.append(file_member(name, data, 0o755 if name.endswith("tool") else 0o644))
    return members


def tree_of(tmp: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> tuple[str, int]:
    """The tree digest and size of what an archive unpacks to, computed the way host-engine checks it."""
    archive = tmp / "probe.tar.gz"
    archive.write_bytes(tar_gz(members))
    out = tmp / "probe"
    with tarfile.open(archive) as tar:
        tar.extractall(out, filter="data")
    digest, _count, size = local_models.tree_sha256(out / "diar")
    return digest, size


GOOD = tar_gz(good_members())


def catalog_raw(archive: bytes, tree: str, unpacked: int) -> dict[str, Any]:
    return {
        "catalog_version": 1,
        "models": [
            {
                "id": ENGINE_ID, "process": "diarization", "kind": "managed_engine", "engine": "senko",
                "repo": "test/senko", "revision": REVISION, "managed_by": "scripts/engines/install-diar-engine.sh",
                "min_ram_gib": 0, "requires": [], "rank": 1, "status": "measured", "default": True,
            },
            {
                "id": COMPONENT_ID, "process": "diarization", "kind": "component", "engine": "senko",
                "component": "diar", "replaces": ENGINE_ID, "repo": "test/senko", "revision": REVISION,
                "version": VERSION, "release_tag": TAG, "url_template": RELEASE_URL_TEMPLATE, "file": ARCHIVE,
                "size": len(archive), "sha256": hashlib.sha256(archive).hexdigest(), "tree_sha256": tree,
                "unpacked_size": unpacked, "min_ram_gib": 0, "requires": [], "rank": 1, "status": "measured",
                "default": True,
            },
        ],
    }  # fmt: skip


class FakeReleases:
    """Serves ``/<repo>/releases/download/<tag>/<file>`` from 127.0.0.1, with scriptable failures."""

    def __init__(self) -> None:
        self.archive = GOOD
        self.mode = "normal"
        self.cut_once = True
        self.requests: list[dict[str, str | None]] = []
        self.lock = threading.Lock()
        releases = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                releases.handle(self)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def handle(self, handler: BaseHTTPRequestHandler) -> None:
        with self.lock:
            headers = handler.headers
            seen = {"path": handler.path, "range": headers.get("Range"), "auth": headers.get("Authorization")}
            self.requests.append(seen)
        if handler.path != f"/{REPO}/releases/download/{TAG}/{ARCHIVE}":
            self.reply(handler, 404, b"missing")
            return
        if self.mode == "redirect_elsewhere":
            handler.send_response(302)
            handler.send_header("Location", f"http://localhost:{self.port}/cdn/{ARCHIVE}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        data = self.archive
        if self.mode == "tampered":
            data = bytes(b ^ 1 for b in data[:50]) + data[50:]
        start, status = 0, 200
        if (value := handler.headers.get("Range")) is not None:
            start, status = int(value.split("=")[1].rstrip("-")), 206
        body = data[start:]
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        handler.end_headers()
        if self.mode == "cut" and self.cut_once:
            self.cut_once = False
            handler.wfile.write(body[: len(body) // 2])
            handler.wfile.flush()
            handler.close_connection = True
            handler.connection.shutdown(socket.SHUT_RDWR)
            return
        handler.wfile.write(body)

    def reply(self, handler: BaseHTTPRequestHandler, status: int, body: bytes) -> None:
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


@pytest.fixture
def releases() -> Iterator[FakeReleases]:
    fake = FakeReleases()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


ServiceFactory = Callable[..., local_models.LocalModelService]


@pytest.fixture
def make_service(
    tmp_path: Path, releases: FakeReleases, monkeypatch: pytest.MonkeyPatch
) -> ServiceFactory:
    monkeypatch.setattr(local_models, "RETRY_DELAY_S", 0.0)
    tree, unpacked = tree_of(tmp_path, good_members())

    def build(archive: bytes = GOOD, *, repo: str = REPO, components: bool = True, tree_digest: str = tree,
              unpacked_size: int = unpacked) -> local_models.LocalModelService:  # fmt: skip
        releases.archive = archive
        service = local_models.LocalModelService(
            models_dir=tmp_path / "models",
            catalog=parse_catalog(catalog_raw(archive, tree_digest, unpacked_size)),
            token_path=tmp_path / "hf_token",
            managed_dirs={},
            components_dir=(tmp_path / "components") if components else None,
            release_policy=local_models.ReleasePolicy(repo=repo, loopback_base=releases.base),
        )
        monkeypatch.setattr(local_models, "_service", service)
        return service

    return build


@pytest.fixture
def client(host: Any) -> Iterator[TestClient]:
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


def install(client: TestClient) -> dict[str, Any]:
    response = post(client, f"/v1/local/models/{COMPONENT_ID}/install")
    assert response.status_code == 202, response.text
    return wait_job(client, response.json()["id"])


def listing(client: TestClient) -> dict[str, Any]:
    body: dict[str, Any] = client.get("/v1/local/models", headers=AUTH).json()
    return body


def view(client: TestClient, model_id: str = COMPONENT_ID) -> dict[str, Any]:
    return next(model for model in listing(client)["models"] if model["id"] == model_id)


def leftovers(service: local_models.LocalModelService) -> list[str]:
    root = service.components_dir
    assert root is not None
    return sorted(path.name for path in root.iterdir()) if root.exists() else []


# --- allow-list -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        (f"https://github.com/{REPO}/releases/download/{TAG}/{ARCHIVE}", True),
        ("https://release-assets.githubusercontent.com/github-production-release-asset/1/abc?sig=x", True),
        (f"https://github.com:443/{REPO}/releases/download/{TAG}/{ARCHIVE}", True),
        (f"https://github.com/other/repo/releases/download/{TAG}/{ARCHIVE}", False),
        (f"https://github.com/{REPO}/archive/refs/heads/main.zip", False),
        (f"https://github.com/{REPO}/releases/download/../../../evil", False),
        ("https://github.com/login", False),
        ("https://objects.githubusercontent.com/github-production-release-asset-2e65be/1/abc", False),
        ("https://raw.githubusercontent.com/owner/sauri-releases/main/x", False),
        ("https://huggingface.co/test/repo/resolve/main/x", False),
        (f"http://github.com/{REPO}/releases/download/{TAG}/{ARCHIVE}", False),
        (f"https://github.com:8443/{REPO}/releases/download/{TAG}/{ARCHIVE}", False),
        (f"https://user:pw@github.com/{REPO}/releases/download/{TAG}/{ARCHIVE}", False),
        (f"https://github.com.evil.example/{REPO}/releases/download/{TAG}/{ARCHIVE}", False),
        ("https://evil.release-assets.githubusercontent.com/x", False),
        (f"http://127.0.0.1:9/{REPO}/releases/download/{TAG}/{ARCHIVE}", False),
        (f"http://localhost:9/{REPO}/releases/download/{TAG}/{ARCHIVE}", False),
    ],
)
def test_only_the_configured_release_path_and_githubs_asset_host_are_allowed(url: str, allowed: bool) -> None:
    assert local_models.ReleasePolicy(repo=REPO).allows(url) is allowed


def test_loopback_needs_the_switch_the_exact_port_and_the_release_path() -> None:
    policy = local_models.ReleasePolicy(repo=REPO, loopback_base="http://127.0.0.1:9000")
    assert policy.allows(f"http://127.0.0.1:9000/{REPO}/releases/download/{TAG}/{ARCHIVE}")
    assert not policy.allows(f"http://127.0.0.1:9001/{REPO}/releases/download/{TAG}/{ARCHIVE}")
    assert not policy.allows("http://127.0.0.1:9000/cdn/x")
    assert not policy.allows(f"http://localhost:9000/{REPO}/releases/download/{TAG}/{ARCHIVE}")
    assert not local_models.ReleasePolicy(repo="").allows(f"https://github.com/{REPO}/releases/download/{TAG}/x")
    assert not policy.sends_token(f"http://127.0.0.1:9000/{REPO}/releases/download/{TAG}/{ARCHIVE}")


def test_the_policy_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SAURI_RELEASES_REPO", "SAURI_ALLOW_LOOPBACK_DOWNLOADS", "SAURI_RELEASES_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    assert local_models.release_policy_from_env() == local_models.ReleasePolicy(repo="", loopback_base=None)
    monkeypatch.setenv("SAURI_RELEASES_REPO", "not a repo/../x")
    assert local_models.release_policy_from_env().repo == ""
    monkeypatch.setenv("SAURI_RELEASES_REPO", REPO)
    monkeypatch.setenv("SAURI_RELEASES_BASE_URL", "http://127.0.0.1:9000")
    assert local_models.release_policy_from_env().loopback_base is None  # no switch, no loopback
    monkeypatch.setenv("SAURI_ALLOW_LOOPBACK_DOWNLOADS", "1")
    assert local_models.release_policy_from_env() == local_models.ReleasePolicy(REPO, "http://127.0.0.1:9000")
    for other in ("http://localhost:9000", "https://evil.example", "http://10.0.0.1:80", "http://127.0.0.1:9000/x"):
        monkeypatch.setenv("SAURI_RELEASES_BASE_URL", other)
        assert local_models.release_policy_from_env().loopback_base is None


# --- listing ------------------------------------------------------------------------------------------


def test_outside_the_desktop_app_the_component_is_hidden(make_service: ServiceFactory, client: TestClient) -> None:
    make_service(components=False)
    ids = [model["id"] for model in listing(client)["models"]]
    assert ids == [ENGINE_ID]
    assert post(client, f"/v1/local/models/{COMPONENT_ID}/install").status_code == 404


def test_in_the_desktop_app_the_component_replaces_the_managed_engine(
    make_service: ServiceFactory, client: TestClient
) -> None:
    make_service()
    body = listing(client)
    assert [model["id"] for model in body["models"]] == [COMPONENT_ID]
    component = body["models"][0]
    assert component["kind"] == "component" and component["version"] == VERSION
    assert component["state"] == "not_installed" and component["availability"] == "available"
    assert component["install"]["method"] == "download" and component["install"]["source_available"] is True
    assert component["install"]["disk_required_bytes"] >= component["size"]
    assert component["recommended"] and body["recommendations"]["diarization"]["model_id"] == COMPONENT_ID
    # The first run downloads the component on its own: it is in the setup plan.
    assert body["setup_plan"] == [COMPONENT_ID]


def test_without_a_download_place_the_listing_says_so_and_install_is_refused(
    make_service: ServiceFactory, client: TestClient, releases: FakeReleases
) -> None:
    service = make_service(repo="")
    assert view(client)["install"]["source_available"] is False
    response = post(client, f"/v1/local/models/{COMPONENT_ID}/install")
    assert response.status_code == 409 and response.json()["error"]["code"] == "component_not_published"
    assert releases.requests == [] and leftovers(service) == []


# --- install --------------------------------------------------------------------------------------------


def test_install_downloads_checks_and_unpacks_atomically(
    make_service: ServiceFactory, client: TestClient, releases: FakeReleases
) -> None:
    service = make_service()
    job = install(client)
    assert job["state"] == "done" and job["result"] == "installed", job
    root = service.components_dir
    assert root is not None
    assert leftovers(service) == ["diar", "diar.component.json"]
    for name, data in CONTENT.items():
        assert (root / name).read_bytes() == data
    assert (root / "diar/tool").stat().st_mode & 0o100
    manifest = json.loads((root / "diar.component.json").read_text())
    assert manifest["status"] == "installed" and manifest["version"] == VERSION
    installed = view(client)
    assert installed["state"] == "installed" and installed["availability"] == "installed" and installed["active"]
    assert [request["auth"] for request in releases.requests] == [None]
    assert post(client, f"/v1/local/models/{COMPONENT_ID}/install").json()["error"]["code"] == "already_installed"


def test_a_cut_download_resumes_with_a_range_request(
    make_service: ServiceFactory, client: TestClient, releases: FakeReleases
) -> None:
    make_service()
    releases.mode = "cut"
    assert install(client)["state"] == "done"
    ranges = [request["range"] for request in releases.requests]
    assert ranges[0] is None and ranges[1] is not None and ranges[1].startswith("bytes=")


def test_a_tampered_archive_is_refused_and_leaves_nothing(
    make_service: ServiceFactory, client: TestClient, releases: FakeReleases
) -> None:
    service = make_service()
    releases.mode = "tampered"
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "hash_mismatch"
    assert leftovers(service) == [] and view(client)["state"] == "not_installed"


def test_a_redirect_off_the_allow_list_is_refused(
    make_service: ServiceFactory, client: TestClient, releases: FakeReleases
) -> None:
    service = make_service()
    releases.mode = "redirect_elsewhere"
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "redirect_not_allowed"
    assert [request["path"] for request in releases.requests if "/cdn/" in (request["path"] or "")] == []
    assert leftovers(service) == []


@pytest.mark.parametrize(
    "members",
    [
        [dir_member("diar"), file_member("diar/../escape.txt", b"x")],
        [dir_member("diar"), file_member("other/file.txt", b"x")],
        [dir_member("diar"), file_member("/abs/file.txt", b"x")],
        [dir_member("diar"), link_member("diar/link", "/etc/passwd")],
        [file_member("diar", b"not a folder")],
    ],
    ids=["dotdot", "outside", "absolute", "symlink", "not-a-folder"],
)
def test_an_archive_that_would_write_outside_its_folder_is_refused(
    make_service: ServiceFactory,
    client: TestClient,
    tmp_path: Path,
    members: list[tuple[tarfile.TarInfo, bytes | None]],
) -> None:
    archive = tar_gz(members)
    service = make_service(archive)  # the catalog vouches for this very archive: only the unpacking can refuse it
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "archive_invalid", job
    assert leftovers(service) == []
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "components" / "escape.txt").exists()


def test_an_archive_bigger_than_the_catalog_says_is_refused(make_service: ServiceFactory, client: TestClient) -> None:
    service = make_service(unpacked_size=1000)
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "archive_too_large"
    assert leftovers(service) == []


def test_an_unpacked_tree_that_differs_from_the_catalog_is_refused(
    make_service: ServiceFactory, client: TestClient
) -> None:
    service = make_service(tree_digest="0" * 64)
    job = install(client)
    assert job["state"] == "failed" and job["error"] == "tree_mismatch"
    assert leftovers(service) == []


def test_verify_rehashes_the_tree_and_removal_follows_the_in_use_rule(
    make_service: ServiceFactory, client: TestClient
) -> None:
    service = make_service()
    assert install(client)["state"] == "done"
    verified = wait_job(client, post(client, f"/v1/local/models/{COMPONENT_ID}/verify").json()["id"])
    assert verified["result"] == "verified"
    root = service.components_dir
    assert root is not None
    (root / "diar/pkg/__init__.py").write_bytes(b"VALUE = 2\n")
    corrupt = wait_job(client, post(client, f"/v1/local/models/{COMPONENT_ID}/verify").json()["id"])
    assert corrupt["result"] == "corrupt" and view(client)["state"] == "corrupt"
    # The default diarization option runs the process: it cannot be removed from under it.
    removed = client.delete(f"/v1/local/models/{COMPONENT_ID}", headers=AUTH)
    assert removed.status_code == 409 and removed.json()["error"]["code"] == "model_in_use"
    # A corrupt one can be installed again over itself.
    assert install(client)["state"] == "done" and view(client)["state"] == "installed"


def test_an_older_version_on_disk_can_be_replaced(make_service: ServiceFactory, client: TestClient) -> None:
    service = make_service()
    assert install(client)["state"] == "done"
    root = service.components_dir
    assert root is not None
    record = json.loads((root / "diar.component.json").read_text())
    record.update(version="0.0.1", sha256="1" * 64)
    (root / "diar.component.json").write_text(json.dumps(record))
    outdated = view(client)
    assert outdated["state"] == "unverified" and outdated["reason"] == "outdated"
    assert install(client)["state"] == "done" and view(client)["state"] == "installed"


def test_a_component_the_runtime_carries_counts_as_installed_and_is_not_ours_to_remove(
    make_service: ServiceFactory, client: TestClient, tmp_path: Path
) -> None:
    service = make_service()
    bundled = tmp_path / "runtime-components"
    (bundled / "diar").mkdir(parents=True)
    service.bundled_components_dir = bundled
    carried = view(client)
    assert carried["state"] == "installed" and carried["location"] == "legacy"
    assert post(client, f"/v1/local/models/{COMPONENT_ID}/install").json()["error"]["code"] == "already_installed"
