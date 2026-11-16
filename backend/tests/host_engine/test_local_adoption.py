"""Adoption of models installed by hand: recognized as installed, never moved, copied, deleted or downloaded.

Everything runs on small synthetic files in temp directories (a fake models directory and a fake legacy
directory); the owner's real ``~/.local/share/sauri`` is never read and no multi-GB file is hashed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import local_models
import pytest
from conftest import MANAGEMENT_TOKEN
from fastapi.testclient import TestClient
from sauri_engine_common.local_model_use import LocalModelError, select_local_model
from sauri_engine_common.recommend import CatalogModel, HardwareProfile, parse_catalog

from tests.local_models_support import route_header

AUTH = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}
REVISION = "b" * 40
ASR = b"asr-default-model" * 40
ASR_SMALL = b"asr-small-model" * 30
VAD = b"vad-aux" * 20
LLM = b"llm-default-model" * 60
LLM_SMALL = b"llm-small-model" * 25
ASR_ID, ASR_SMALL_ID, VAD_ID, LLM_ID, LLM_SMALL_ID, SENKO_ID = (
    "t-asr", "t-asr-small", "t-vad", "t-llm", "t-llm-small", "t-senko",
)  # fmt: skip


def entry(model_id: str, process: str, file: str, data: bytes, **extra: Any) -> dict[str, Any]:
    return {
        "id": model_id, "process": process, "kind": "model", "engine": "synthetic", "repo": "test/repo",
        "revision": REVISION, "file": file, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "min_ram_gib": 4, "requires": [], "rank": 1, "status": "measured", "default": False, **extra,
    }  # fmt: skip


CATALOG_RAW = {
    "catalog_version": 1,
    "models": [
        entry(ASR_ID, "transcription", "asr.bin", ASR, default=True, rank=2),
        entry(ASR_SMALL_ID, "transcription", "asr-small.bin", ASR_SMALL),
        entry(VAD_ID, "transcription", "vad.bin", VAD, kind="auxiliary", default=True, rank=0),
        entry(LLM_ID, "summary", "llm.gguf", LLM, default=True, rank=2),
        entry(LLM_SMALL_ID, "summary", "llm-small.gguf", LLM_SMALL),
        {
            "id": SENKO_ID, "process": "diarization", "kind": "managed_engine", "engine": "senko",
            "repo": "test/senko", "revision": REVISION, "managed_by": "scripts/engines/install-diar-engine.sh",
            "min_ram_gib": 0, "requires": [], "rank": 1, "status": "measured", "default": True,
        },
    ],
}  # fmt: skip


class Env:
    """A fake models directory, a fake legacy directory and a fake diarization virtual environment."""

    def __init__(self, root: Path, service: local_models.LocalModelService, client: TestClient) -> None:
        self.root, self.service, self.client = root, service, client
        self.models, self.legacy, self.venv = service.models_dir, root / "legacy", root / "diar-venv"

    def put(self, directory: Path, name: str, data: bytes) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_bytes(data)
        return path

    def adopt(self) -> dict[str, Any]:
        response = self.client.post("/v1/local/adopt", headers=AUTH)
        assert response.status_code == 202, response.text
        return self.wait(response.json()["id"])

    def wait(self, job_id: str, timeout: float = 20.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job: dict[str, Any] = self.client.get(f"/v1/local/jobs/{job_id}", headers=AUTH).json()
            if job["state"] != "running":
                return job
            time.sleep(0.01)
        raise AssertionError("adoption did not finish")

    def listing(self) -> dict[str, Any]:
        body: dict[str, Any] = self.client.get("/v1/local/models", headers=AUTH).json()
        return body

    def view(self, model_id: str) -> dict[str, Any]:
        return next(model for model in self.listing()["models"] if model["id"] == model_id)

    def manifest(self, file: str) -> dict[str, Any]:
        record: dict[str, Any] = json.loads((self.models / (file + ".manifest.json")).read_text())
        return record

    def install_senko(self) -> None:
        (self.venv / "bin").mkdir(parents=True, exist_ok=True)
        (self.venv / "bin" / "python").write_text("#!/bin/sh\n")
        (self.venv / "lib" / "python3.11" / "site-packages" / "senko").mkdir(parents=True, exist_ok=True)


def fingerprint(path: Path) -> tuple[int, int, int, bytes]:
    info = path.stat()
    return info.st_ino, info.st_mtime_ns, info.st_size, path.read_bytes()


@pytest.fixture
def env(host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    legacy = tmp_path / "legacy"

    def locator(model: CatalogModel) -> Path | None:
        return legacy / model.file if model.id == LLM_ID and model.file else None

    service = local_models.LocalModelService(
        models_dir=tmp_path / "models",
        catalog=parse_catalog(CATALOG_RAW),
        policy=local_models.DownloadPolicy(base_url="http://127.0.0.1:9", scheme="http", ports=None),
        token_path=tmp_path / "hf_token",
        legacy_locator=locator,
        managed_dirs={"senko": tmp_path / "diar-venv"},
    )
    monkeypatch.setattr(local_models, "_service", service)
    profile = HardwareProfile("arm64", 16.0, 8, True, 10**12, "Darwin")
    monkeypatch.setattr(local_models, "detect_hardware", lambda _dir: profile)
    with TestClient(host.app, base_url="http://127.0.0.1:8005", raise_server_exceptions=False) as client:
        yield Env(tmp_path, service, client)


# --- adoption ---------------------------------------------------------------------------------------


def test_a_file_in_the_models_directory_is_adopted_with_the_manifest_an_install_writes(env: Env) -> None:
    final = env.put(env.models, "asr.bin", ASR)
    before = fingerprint(final)
    assert env.view(ASR_ID)["state"] == "unverified" and env.view(ASR_ID)["availability"] == "present_unverified"
    job = env.adopt()
    assert job["type"] == "adopt" and job["state"] == "done" and job["result"] == "adopted"
    assert job["bytes_done"] == job["bytes_total"] == len(ASR) and job["outcomes"] == {ASR_ID: "adopted"}
    record = env.manifest("asr.bin")
    assert record["status"] == "installed" and record["sha256"] == hashlib.sha256(ASR).hexdigest()
    assert record["size"] == len(ASR) and record["mtime_ns"] == before[1] and record["location"] == "models_dir"
    assert record["installed_at"] and record["revision"] == REVISION
    view = env.view(ASR_ID)
    assert (view["state"], view["availability"], view["location"], view["installed_size"]) == (
        "installed", "installed", "models_dir", len(ASR),
    )  # fmt: skip
    assert fingerprint(final) == before  # same inode, mtime and bytes: the file was only read
    assert sorted(path.name for path in env.models.iterdir()) == ["asr.bin", "asr.bin.manifest.json"]


def test_a_legacy_file_is_adopted_in_place_and_stays_resolvable_by_the_gateway(env: Env) -> None:
    legacy = env.put(env.legacy, "llm.gguf", LLM)
    before = fingerprint(legacy)
    job = env.adopt()
    assert job["outcomes"] == {LLM_ID: "adopted"}
    record = env.manifest("llm.gguf")
    assert record["status"] == "installed" and record["location"] == "legacy" and record["mtime_ns"] == before[1]
    assert "path" not in record  # the gateways never read a path from a manifest
    assert sorted(path.name for path in env.models.iterdir()) == ["llm.gguf.manifest.json"]  # nothing copied here
    assert fingerprint(legacy) == before and sorted(path.name for path in env.legacy.iterdir()) == ["llm.gguf"]
    view = env.view(LLM_ID)
    assert (view["state"], view["availability"], view["location"], view["installed_size"]) == (
        "installed", "installed", "legacy", len(LLM),
    )  # fmt: skip
    chosen = select_local_model(
        route_header(f"local:{LLM_ID}"), process="summary", legacy_default=legacy,
        models_dir=env.models, catalog=env.service.catalog,
    )  # fmt: skip
    assert chosen is not None and chosen.path == legacy


def test_a_legacy_file_replaced_after_adoption_is_not_served_until_adopted_again(env: Env) -> None:
    legacy = env.put(env.legacy, "llm.gguf", LLM)
    env.adopt()
    info = legacy.stat()
    os.utime(legacy, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000))
    assert env.view(LLM_ID)["availability"] == "present_unverified"
    with pytest.raises(LocalModelError) as refused:
        select_local_model(
            route_header(f"local:{LLM_ID}"), process="summary", legacy_default=legacy,
            models_dir=env.models, catalog=env.service.catalog,
        )  # fmt: skip
    assert refused.value.code == "model_not_verified"
    assert env.adopt()["outcomes"] == {LLM_ID: "adopted"}  # the hash still matches: recognized again
    assert env.view(LLM_ID)["availability"] == "installed"


def test_a_hash_mismatch_is_never_claimed_as_installed(env: Env) -> None:
    wrong = bytes(b ^ 1 for b in ASR[:5]) + ASR[5:]  # same size, different content
    final = env.put(env.models, "asr.bin", wrong)
    before = fingerprint(final)
    job = env.adopt()
    assert job["state"] == "done" and job["result"] == "nothing_adopted"
    assert job["outcomes"] == {ASR_ID: "present_unverified"}
    view = env.view(ASR_ID)
    assert view["availability"] == "present_unverified" and view["reason"] == "hash_mismatch"
    assert view["state"] == "unverified" and view["active"] is False  # existing vocabulary, never "installed"
    record = env.manifest("asr.bin")
    assert record["status"] == "present_unverified" and record["reason"] == "hash_mismatch"
    assert fingerprint(final) == before
    # The gateway does not serve it either.
    with pytest.raises(LocalModelError) as refused:
        select_local_model(
            route_header(f"local:{ASR_ID}", process="transcription"), process="transcription",
            models_dir=env.models, catalog=env.service.catalog,
        )  # fmt: skip
    assert refused.value.code == "model_not_verified"


def test_a_file_of_the_wrong_size_is_reported_without_hashing_it(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    env.put(env.legacy, "llm.gguf", LLM + b"x")
    hashed: list[Path] = []
    original = env.service._hash_into

    async def spy(path: Path, sha: Any, job: Any) -> None:
        hashed.append(path)
        await original(path, sha, job)

    monkeypatch.setattr(env.service, "_hash_into", spy)
    job = env.adopt()
    assert hashed == [] and job["bytes_total"] == 0 and job["outcomes"] == {LLM_ID: "present_unverified"}
    view = env.view(LLM_ID)
    assert (view["availability"], view["reason"], view["location"]) == ("present_unverified", "size_mismatch", "legacy")
    assert env.manifest("llm.gguf")["location"] == "legacy"


def test_running_adoption_again_is_idempotent_and_does_not_hash_again(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.put(env.models, "asr.bin", ASR)
    env.put(env.legacy, "llm.gguf", LLM)
    env.put(env.models, "asr-small.bin", bytes(len(ASR_SMALL)))  # wrong content, right size
    first = env.adopt()
    assert first["outcomes"] == {ASR_ID: "adopted", LLM_ID: "adopted", ASR_SMALL_ID: "present_unverified"}
    manifests = {path.name: path.stat().st_mtime_ns for path in env.models.glob("*.manifest.json")}
    hashed: list[Path] = []
    original = env.service._hash_into

    async def spy(path: Path, sha: Any, job: Any) -> None:
        hashed.append(path)
        await original(path, sha, job)

    monkeypatch.setattr(env.service, "_hash_into", spy)
    second = env.adopt()
    assert hashed == [] and second["bytes_total"] == 0 and second["outcomes"] == {}
    assert {path.name: path.stat().st_mtime_ns for path in env.models.glob("*.manifest.json")} == manifests
    # A file that changed since it was judged is judged again.
    env.put(env.models, "asr-small.bin", ASR_SMALL)
    os.utime(env.models / "asr-small.bin", ns=(1, time.time_ns()))
    assert env.adopt()["outcomes"] == {ASR_SMALL_ID: "adopted"}


def test_a_second_request_during_a_run_returns_the_same_job_and_an_install_is_refused(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.put(env.models, "asr.bin", ASR)
    release = {"go": False}
    original = env.service._hash_into

    async def slow(path: Path, sha: Any, job: Any) -> None:
        while not release["go"]:
            await local_models.asyncio.sleep(0.01)
        await original(path, sha, job)

    monkeypatch.setattr(env.service, "_hash_into", slow)
    first = env.client.post("/v1/local/adopt", headers=AUTH).json()
    second = env.client.post("/v1/local/adopt", headers=AUTH).json()
    assert first["id"] == second["id"] and first["state"] == "running"
    mid = env.view(ASR_ID)
    assert mid["verifying"] is True and mid["availability"] == "present_unverified"  # not installed until verified
    assert env.listing()["active_job"] == first["id"]
    refused = env.client.post(f"/v1/local/models/{ASR_SMALL_ID}/install", headers=AUTH)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "job_active"
    release["go"] = True
    assert env.wait(first["id"])["result"] == "adopted"
    assert env.view(ASR_ID)["verifying"] is False
    assert env.listing()["adoption"] == {"job_id": first["id"], "outcomes": {ASR_ID: "adopted"}}


def test_an_install_in_progress_refuses_adoption(env: Env) -> None:
    env.service._active = local_models.Job(id="f" * 32, model_id=ASR_ID, type="install", bytes_total=1)
    response = env.client.post("/v1/local/adopt", headers=AUTH)
    assert response.status_code == 409 and response.json()["error"]["code"] == "job_active"
    env.service._active = None


def test_a_file_modified_while_it_is_read_is_not_adopted(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    final = env.put(env.models, "asr.bin", ASR)
    original = env.service._hash_into

    async def touch_while_reading(path: Path, sha: Any, job: Any) -> None:
        await original(path, sha, job)
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 7_000_000))

    monkeypatch.setattr(env.service, "_hash_into", touch_while_reading)
    job = env.adopt()
    assert job["outcomes"] == {ASR_ID: "changed"} and not final.with_name("asr.bin.manifest.json").exists()
    assert env.view(ASR_ID)["availability"] == "present_unverified"


def test_an_unreadable_file_is_reported_and_the_run_continues(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    env.put(env.models, "asr.bin", ASR)
    env.put(env.legacy, "llm.gguf", LLM)
    original = env.service._hash_into

    async def failing(path: Path, sha: Any, job: Any) -> None:
        if path.name == "asr.bin":
            raise PermissionError("denied")
        await original(path, sha, job)

    monkeypatch.setattr(env.service, "_hash_into", failing)
    job = env.adopt()
    assert job["state"] == "done" and job["outcomes"] == {ASR_ID: "unreadable", LLM_ID: "adopted"}


def test_adoption_never_downloads_anything(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_a: Any, **_k: Any) -> None:
        raise AssertionError("adoption must not use the network")

    monkeypatch.setattr(local_models.httpx, "AsyncClient", forbidden)
    env.put(env.models, "asr.bin", ASR)
    assert env.adopt()["result"] == "adopted"
    # Models that are absent stay absent: no .part, no file.
    assert sorted(path.name for path in env.models.iterdir()) == ["asr.bin", "asr.bin.manifest.json"]
    assert env.view(ASR_SMALL_ID)["availability"] == "available"


def test_an_empty_machine_adopts_nothing_and_creates_no_directory(env: Env) -> None:
    job = env.adopt()
    assert job["state"] == "done" and job["result"] == "nothing_adopted" and job["outcomes"] == {}
    assert not env.models.exists() and not env.legacy.exists()


def test_the_adopt_route_needs_the_token_and_takes_no_query(env: Env) -> None:
    assert env.client.post("/v1/local/adopt").status_code == 401
    assert env.client.post("/v1/local/adopt", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert env.client.post("/v1/local/adopt?path=/etc", headers=AUTH).status_code == 422


def test_the_host_adopts_by_itself_when_it_starts(
    host: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = local_models.LocalModelService(
        models_dir=tmp_path / "models", catalog=parse_catalog(CATALOG_RAW), legacy_locator=lambda _m: None,
        managed_dirs={},
    )  # fmt: skip
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "asr.bin").write_bytes(ASR)
    monkeypatch.setattr(local_models, "_service", service)
    monkeypatch.setattr(host, "ADOPT_ON_START", True)
    with TestClient(host.app, base_url="http://127.0.0.1:8005", raise_server_exceptions=False) as client:
        deadline = time.monotonic() + 20
        while service._active is not None:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        body = client.get("/v1/local/models", headers=AUTH).json()
    assert next(m for m in body["models"] if m["id"] == ASR_ID)["availability"] == "installed"
    assert (tmp_path / "models" / "asr.bin.manifest.json").exists()


# --- verify, install and remove respect the legacy location -----------------------------------------


def test_a_legacy_model_is_not_installed_over_not_removed_and_can_be_verified(env: Env) -> None:
    legacy = env.put(env.legacy, "llm.gguf", LLM)
    env.adopt()
    installing = env.client.post(f"/v1/local/models/{LLM_ID}/install", headers=AUTH)
    assert installing.status_code == 409 and installing.json()["error"]["code"] == "already_installed"
    (env.models / "selection.json").write_text(json.dumps({"summary": LLM_SMALL_ID}))  # so the 9B is not in use
    removing = env.client.delete(f"/v1/local/models/{LLM_ID}", headers=AUTH)
    assert removing.status_code == 409 and removing.json()["error"]["code"] == "legacy_location"
    assert legacy.read_bytes() == LLM  # the user's file is never deleted
    verified = env.wait(env.client.post(f"/v1/local/models/{LLM_ID}/verify", headers=AUTH).json()["id"])
    assert verified["result"] == "verified" and env.manifest("llm.gguf")["location"] == "legacy"
    legacy.write_bytes(LLM[:-1] + b"?")
    corrupt = env.wait(env.client.post(f"/v1/local/models/{LLM_ID}/verify", headers=AUTH).json()["id"])
    assert corrupt["result"] == "corrupt" and env.view(LLM_ID)["availability"] == "present_unverified"


def test_a_model_judged_different_can_be_installed_again(env: Env) -> None:
    env.put(env.models, "asr-small.bin", bytes(len(ASR_SMALL)))
    env.adopt()
    assert env.view(ASR_SMALL_ID)["reason"] == "hash_mismatch"
    # Not "already_installed": the download starts (it fails here only because nothing listens on the port).
    response = env.client.post(f"/v1/local/models/{ASR_SMALL_ID}/install", headers=AUTH)
    assert response.status_code == 202
    env.client.post(f"/v1/local/jobs/{response.json()['id']}/cancel", headers=AUTH)


# --- the active marker ------------------------------------------------------------------------------


def active_ids(env: Env) -> dict[str, str | None]:
    listing = env.listing()
    flagged = {m["process"]: m["id"] for m in listing["models"] if m["active"]}
    assert listing["active"].get("diarization") == flagged.get("diarization")
    assert {p: i for p, i in listing["active"].items() if i is not None} == flagged  # exactly one per process
    return dict(listing["active"])


def test_nothing_is_active_when_nothing_is_installed(env: Env) -> None:
    assert active_ids(env) == {"transcription": None, "summary": None, "diarization": None}
    models = {m["id"]: m for m in env.listing()["models"]}
    assert all(m["availability"] == "available" for m in models.values())
    # "in use" is about removal: the defaults and the auxiliary file are claimed by their process even when absent.
    assert {model_id for model_id, m in models.items() if m["in_use"]} == {ASR_ID, VAD_ID, LLM_ID, SENKO_ID}


def test_the_installed_catalog_default_is_active_when_nothing_is_chosen(env: Env) -> None:
    env.put(env.models, "asr.bin", ASR)
    env.put(env.models, "asr-small.bin", ASR_SMALL)
    env.put(env.legacy, "llm.gguf", LLM)
    env.adopt()
    assert active_ids(env) == {"transcription": ASR_ID, "summary": LLM_ID, "diarization": None}
    assert env.view(ASR_SMALL_ID)["active"] is False and env.view(ASR_SMALL_ID)["in_use"] is False
    assert env.view(ASR_ID)["in_use_by"] == ["transcription"] and env.view(LLM_ID)["in_use"] is True


def test_the_model_in_selection_json_is_the_active_one_not_the_default(env: Env) -> None:
    env.put(env.models, "asr.bin", ASR)
    env.put(env.models, "asr-small.bin", ASR_SMALL)
    env.adopt()
    (env.models / "selection.json").write_text(json.dumps({"transcription": ASR_SMALL_ID}))
    assert active_ids(env)["transcription"] == ASR_SMALL_ID
    default, chosen = env.view(ASR_ID), env.view(ASR_SMALL_ID)
    assert (default["active"], default["in_use"]) == (False, False)
    assert (chosen["active"], chosen["in_use"], chosen["in_use_by"]) == (True, True, ["transcription"])


def test_a_choice_that_is_not_installed_leaves_the_process_without_an_active_model(env: Env) -> None:
    env.put(env.models, "asr.bin", ASR)
    env.adopt()
    (env.models / "selection.json").write_text(json.dumps({"transcription": ASR_SMALL_ID, "summary": "unknown-id"}))
    assert active_ids(env)["transcription"] is None  # local:<id> would be refused, so the default is not shown
    assert active_ids(env)["summary"] is None
    assert env.view(ASR_ID)["active"] is False


@pytest.mark.parametrize("content", ["{", "[1]", '{"transcription": null}'])
def test_an_unreadable_or_empty_choice_falls_back_to_the_default(env: Env, content: str) -> None:
    env.put(env.models, "asr.bin", ASR)
    env.adopt()
    (env.models / "selection.json").write_text(content)
    assert active_ids(env)["transcription"] == ASR_ID


def test_the_auxiliary_vad_is_in_use_but_never_the_active_model(env: Env) -> None:
    env.put(env.models, "vad.bin", VAD)
    env.put(env.models, "asr.bin", ASR)
    env.adopt()
    vad = env.view(VAD_ID)
    assert (vad["availability"], vad["active"], vad["in_use"]) == ("installed", False, True)
    assert active_ids(env)["transcription"] == ASR_ID


def test_a_model_present_but_unverified_is_not_active(env: Env) -> None:
    env.put(env.models, "asr.bin", ASR)  # present, adoption has not run
    assert active_ids(env)["transcription"] is None
    assert env.view(ASR_ID)["availability"] == "present_unverified" and env.view(ASR_ID)["active"] is False


def test_the_listing_says_what_the_rest_needs(env: Env) -> None:
    env.put(env.models, "asr.bin", ASR)
    env.adopt()
    installed, small, senko = env.view(ASR_ID), env.view(ASR_SMALL_ID), env.view(SENKO_ID)
    assert installed["install"] is None and installed["verified_by"] == "hash"
    assert small["install"] == {
        "method": "download", "managed_by": None, "download_bytes": len(ASR_SMALL),
        "disk_required_bytes": -(-len(ASR_SMALL) * 120 // 100), "fits_on_disk": True,
    }  # fmt: skip
    assert senko["install"]["method"] == "managed_command" and senko["install"]["managed_by"].endswith("diar-engine.sh")


# --- managed engine ---------------------------------------------------------------------------------


def test_the_managed_engine_is_installed_when_its_environment_holds_the_package(env: Env) -> None:
    absent = env.view(SENKO_ID)
    assert (absent["state"], absent["availability"], absent["location"], absent["active"]) == (
        "managed", "available", None, False,
    )  # fmt: skip
    (env.venv / "bin").mkdir(parents=True)
    (env.venv / "bin" / "python").write_text("")
    assert env.view(SENKO_ID)["availability"] == "available"  # an interpreter alone is not the engine
    env.install_senko()
    present = env.view(SENKO_ID)
    assert (present["state"], present["availability"], present["location"], present["verified_by"]) == (
        "managed", "installed", "managed", "presence",
    )  # fmt: skip
    assert present["install"] is None and present["active"] is True and active_ids(env)["diarization"] == SENKO_ID
    assert env.adopt()["outcomes"] == {}  # a managed engine is never hashed or adopted as a file


def test_the_default_managed_environment_follows_the_installer_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SAURI_DIAR_VENV", str(tmp_path / "custom"))
    assert local_models.default_managed_dirs() == {"senko": tmp_path / "custom"}
    monkeypatch.delenv("SAURI_DIAR_VENV")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert local_models.default_managed_dirs()["senko"] == tmp_path / ".local/share/sauri/native-engines/diar-venv"


# --- backward compatibility ---------------------------------------------------------------------------


def test_a_manifest_written_before_adoption_existed_is_still_installed(env: Env) -> None:
    final = env.put(env.models, "asr.bin", ASR)
    info = final.stat()
    old = {
        "id": ASR_ID, "file": "asr.bin", "revision": REVISION, "sha256": hashlib.sha256(ASR).hexdigest(),
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "installed_at": "2026-01-01T00:00:00+00:00",
        "status": "installed",
    }  # fmt: skip
    (env.models / "asr.bin.manifest.json").write_text(json.dumps(old))
    view = env.view(ASR_ID)
    assert (view["state"], view["availability"], view["location"], view["installed_at"]) == (
        "installed", "installed", "models_dir", "2026-01-01T00:00:00+00:00",
    )  # fmt: skip
    assert env.adopt()["outcomes"] == {}  # already verified: left alone
    assert json.loads((env.models / "asr.bin.manifest.json").read_text()) == old


def test_the_listing_keeps_every_field_the_portal_already_reads(env: Env) -> None:
    body = env.listing()
    assert {"catalog_version", "models", "recommendations", "active_job"} <= set(body)
    for model in body["models"]:
        assert {
            "id", "process", "kind", "engine", "size", "min_ram_gib", "requires", "status", "default", "managed_by",
            "recommended", "in_use_by", "state", "installed_size", "installed_at",
        } <= set(model)  # fmt: skip
        assert model["state"] in {"not_installed", "installing", "installed", "unverified", "corrupt", "managed"}
    assert "sha256" not in json.dumps(body) and "/" not in json.dumps(body["models"][0]["location"] or "")
