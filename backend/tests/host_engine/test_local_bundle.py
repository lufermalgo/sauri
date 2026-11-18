"""Models made of several files (the Parakeet CoreML bundle): install, verify, adopt, seed, remove and defaults.

Everything is synthetic: a loopback server serves three small files whose hashes the test catalog declares.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import local_models
import pytest
from sauri_engine_common.local_model_use import LocalModelError, select_local_model, select_preferred
from sauri_engine_common.model_bundle import BundleFile, bundle_digest, bundle_size
from sauri_engine_common.recommend import CatalogError, parse_catalog
from test_local_models import REVISION, FakeHub, loopback_policy

FILES = {
    "model/a.bin": random.Random(1).randbytes(400_000),
    "model/weights/b.bin": random.Random(2).randbytes(300_000),
    "c.json": b'{"synthetic": true}',
}
BASENAMES = {path.rsplit("/", 1)[-1]: data for path, data in FILES.items()}
BUNDLE = [BundleFile(path, len(data), hashlib.sha256(data).hexdigest()) for path, data in sorted(FILES.items())]
PARAKEET, WHISPER, ENGINE = "test-parakeet", "test-whisper", "test-fluid-cli"


def raw_catalog(**parakeet_extra: Any) -> dict[str, Any]:
    return {
        "catalog_version": 1,
        "models": [
            {
                "id": WHISPER, "process": "transcription", "kind": "model", "engine": "whisper.cpp",
                "repo": "test/whisper",
                "revision": REVISION, "file": "w.bin", "size": 5, "sha256": hashlib.sha256(b"hello").hexdigest(),
                "min_ram_gib": 4, "requires": [], "rank": 2, "status": "measured", "default": True,
            },
            {
                "id": PARAKEET, "process": "transcription", "kind": "model", "engine": "fluidaudio",
                "repo": "test/repo", "revision": REVISION, "file": "parakeet-dir", "size": bundle_size(BUNDLE),
                "sha256": bundle_digest(BUNDLE),
                "files": [{"path": f.path, "size": f.size, "sha256": f.sha256} for f in BUNDLE], "min_ram_gib": 4,
                "requires": [], "rank": 3, "status": "measured", "default": False, "preferred": True, "needs": ENGINE,
                **parakeet_extra,
            },
            {
                "id": ENGINE, "process": "transcription", "kind": "managed_engine", "engine": "fluidaudio",
                "repo": "test/fluid", "revision": REVISION, "managed_by": "scripts/engines/install-parakeet-engine.sh",
                "min_ram_gib": 0, "requires": [], "rank": 0, "status": "measured", "default": False,
            },
        ],
    }  # fmt: skip


@pytest.fixture
def hub() -> Iterator[FakeHub]:
    fake = FakeHub()
    fake.payloads = dict(BASENAMES)
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


@pytest.fixture
def service(tmp_path: Path, hub: FakeHub, monkeypatch: pytest.MonkeyPatch) -> local_models.LocalModelService:
    monkeypatch.setattr(local_models, "RETRY_DELAY_S", 0.0)
    return local_models.LocalModelService(
        models_dir=tmp_path / "models",
        catalog=parse_catalog(raw_catalog()),
        policy=loopback_policy(hub),
        token_path=tmp_path / "hf_token",
        legacy_locator=lambda _model: None,
        managed_dirs={"fluidaudio": tmp_path / "parakeet"},
    )


def install_engine(service: local_models.LocalModelService, *, commit: str = REVISION) -> None:
    home = service.managed_dirs["fluidaudio"]
    (home / "bin").mkdir(parents=True)
    binary = home / "bin" / "fluidaudiocli"
    binary.write_bytes(b"#!/bin/sh\n")
    binary.chmod(0o755)
    (home / "provenance.json").write_text(json.dumps({"source_commit": commit, "binary_sha256": "a" * 64}))


async def run_job(service: local_models.LocalModelService, job: local_models.Job) -> local_models.Job:
    assert job.task is not None
    await asyncio.wait({job.task})
    return job


def write_bundle(directory: Path, files: dict[str, bytes] = FILES) -> None:
    for path, data in files.items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def view(service: local_models.LocalModelService, model_id: str) -> dict[str, Any]:
    return next(item for item in service.list_models()["models"] if item["id"] == model_id)


# --- catalog ------------------------------------------------------------------------------------------


def test_the_catalog_rejects_a_bundle_whose_digest_or_size_does_not_match_its_files() -> None:
    parse_catalog(raw_catalog())
    for change in ({"sha256": "0" * 64}, {"size": 1}, {"files": []}):
        with pytest.raises(CatalogError):
            parse_catalog(raw_catalog(**change))
    tampered = raw_catalog()
    tampered["models"][1]["files"][0]["sha256"] = "1" * 64
    with pytest.raises(CatalogError):
        parse_catalog(tampered)
    unsafe = raw_catalog()
    unsafe["models"][1]["files"][0]["path"] = "../escape.bin"
    with pytest.raises(CatalogError):
        parse_catalog(unsafe)


def test_a_model_may_only_need_a_managed_engine_and_only_one_model_may_be_preferred() -> None:
    with pytest.raises(CatalogError):
        parse_catalog(raw_catalog(needs=WHISPER))
    with pytest.raises(CatalogError):
        parse_catalog(raw_catalog(needs="nothing"))
    twice = raw_catalog()
    twice["models"][0]["preferred"] = True
    with pytest.raises(CatalogError):
        parse_catalog(twice)


# --- install ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_downloads_every_file_into_a_directory_and_writes_a_per_file_manifest(
    service: local_models.LocalModelService, hub: FakeHub
) -> None:
    job = await run_job(service, service.install(PARAKEET))
    assert (
        job.state == "done" and job.result == "installed" and job.bytes_done == job.bytes_total == bundle_size(BUNDLE)
    )
    final = service.models_dir / "parakeet-dir"
    for path, data in FILES.items():
        assert (final / path).read_bytes() == data
    assert sorted(p.name for p in service.models_dir.iterdir()) == ["parakeet-dir", "parakeet-dir.manifest.json"]
    manifest = json.loads((service.models_dir / "parakeet-dir.manifest.json").read_text())
    assert manifest["status"] == "installed" and manifest["sha256"] == bundle_digest(BUNDLE)
    assert set(manifest["files"]) == set(FILES) and all(
        set(v) == {"size", "mtime_ns"} for v in manifest["files"].values()
    )
    assert view(service, PARAKEET)["state"] == "installed"
    assert all(request["auth"] is None for request in hub.requests)  # no token configured: none sent


@pytest.mark.asyncio
async def test_a_tampered_file_fails_the_install_and_leaves_no_directory_behind(
    service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.mode = "tampered"
    job = await run_job(service, service.install(PARAKEET))
    assert job.state == "failed" and job.error == "hash_mismatch"
    assert list(service.models_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_an_interrupted_install_keeps_verified_files_and_resumes_without_downloading_them_again(
    service: local_models.LocalModelService, hub: FakeHub
) -> None:
    # Pre-seed the staging directory as an earlier attempt would have left it.
    staging = service.models_dir / "parakeet-dir.part"
    write_bundle(staging, {"model/a.bin": FILES["model/a.bin"]})
    job = await run_job(service, service.install(PARAKEET))
    assert job.state == "done"
    fetched = {str(request["path"]).rsplit("/", 1)[-1] for request in hub.requests}
    assert "a.bin" not in fetched and {"b.bin", "c.json"} <= fetched
    assert not staging.exists()


@pytest.mark.asyncio
async def test_a_cancelled_install_removes_the_staging_directory(
    service: local_models.LocalModelService, hub: FakeHub
) -> None:
    hub.mode = "slow"
    job = service.install(PARAKEET)
    await asyncio.sleep(0.3)
    await service.cancel(job.id)
    assert job.state == "cancelled" and list(service.models_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_an_incomplete_directory_can_be_reinstalled_over(service: local_models.LocalModelService) -> None:
    write_bundle(service.models_dir / "parakeet-dir", {"model/a.bin": b"short"})
    assert view(service, PARAKEET)["state"] == "unverified"
    job = await run_job(service, service.install(PARAKEET))
    assert job.state == "done" and view(service, PARAKEET)["state"] == "installed"
    assert not (service.models_dir / "parakeet-dir.old").exists()


# --- state, verify, adopt, remove ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_file_replaced_after_the_install_is_no_longer_installed_until_verified(
    service: local_models.LocalModelService,
) -> None:
    await run_job(service, service.install(PARAKEET))
    target = service.models_dir / "parakeet-dir" / "c.json"
    original = target.stat()
    target.write_bytes(b'{"synthetic": false}')  # same size, new mtime
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns + 5_000_000))
    assert view(service, PARAKEET)["state"] == "unverified"
    with pytest.raises(LocalModelError):
        select_local_model(
            _header(PARAKEET),
            process="transcription",
            models_dir=service.models_dir,
            catalog=service.catalog,
        )
    job = await run_job(service, service.verify(PARAKEET))
    assert job.result == "corrupt" and view(service, PARAKEET)["state"] == "corrupt"
    target.write_bytes(FILES["c.json"])
    job = await run_job(service, service.verify(PARAKEET))
    assert job.result == "verified" and view(service, PARAKEET)["state"] == "installed"


@pytest.mark.asyncio
async def test_adoption_recognizes_a_complete_bundle_and_refuses_a_different_one(
    service: local_models.LocalModelService,
) -> None:
    write_bundle(service.models_dir / "parakeet-dir")
    job = await run_job(service, service.adopt())
    assert job.outcomes[PARAKEET] == "adopted" and view(service, PARAKEET)["state"] == "installed"
    (service.models_dir / "parakeet-dir.manifest.json").unlink()
    other = service.models_dir / "parakeet-dir" / "c.json"
    other.write_bytes(b'{"synthetic": fals}')  # same size, different bytes
    job = await run_job(service, service.adopt())
    assert job.outcomes[PARAKEET] == "present_unverified"
    assert view(service, PARAKEET)["state"] == "unverified" and view(service, PARAKEET)["reason"] == "hash_mismatch"
    again = await run_job(service, service.adopt())
    assert PARAKEET not in again.outcomes  # judged once; not hashed again until a file changes


def test_the_bundle_in_use_blocks_removal_and_removal_deletes_directory_and_manifest(
    service: local_models.LocalModelService, tmp_path: Path
) -> None:
    write_bundle(service.models_dir / "parakeet-dir")
    asyncio.run(_adopt(service))
    (service.models_dir / "selection.json").write_text(json.dumps({"transcription": WHISPER}))
    service.remove(PARAKEET)
    assert not (service.models_dir / "parakeet-dir").exists()
    assert not (service.models_dir / "parakeet-dir.manifest.json").exists()


def test_a_symlinked_bundle_directory_is_never_followed(
    service: local_models.LocalModelService, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    write_bundle(elsewhere)
    service.models_dir.mkdir()
    (service.models_dir / "parakeet-dir").symlink_to(elsewhere)
    assert view(service, PARAKEET)["state"] == "not_installed"


async def _adopt(service: local_models.LocalModelService) -> None:
    await run_job(service, service.adopt())


# --- active model and the preferred default -----------------------------------------------------------


@pytest.mark.asyncio
async def test_local_default_is_parakeet_only_when_it_is_installed_and_its_engine_is_ready(
    service: local_models.LocalModelService,
) -> None:
    (service.models_dir).mkdir(parents=True)
    (service.models_dir / "w.bin").write_bytes(b"hello")
    await _adopt(service)
    assert service.list_models()["active"]["transcription"] == WHISPER
    write_bundle(service.models_dir / "parakeet-dir")
    await _adopt(service)
    parakeet = view(service, PARAKEET)
    assert parakeet["state"] == "installed" and parakeet["needs_ready"] is False
    assert service.list_models()["active"]["transcription"] == WHISPER  # model without its engine: Whisper
    install_engine(service)
    listing = service.list_models()
    assert listing["active"]["transcription"] == PARAKEET and view(service, PARAKEET)["active"] is True
    assert view(service, WHISPER)["active"] is False and view(service, WHISPER)["in_use"] is True  # the safety net
    assert view(service, ENGINE)["state"] == "managed" and view(service, ENGINE)["location"] == "managed"
    (service.models_dir / "selection.json").write_text(json.dumps({"transcription": WHISPER}))
    assert service.list_models()["active"]["transcription"] == WHISPER  # the person pinned Whisper
    (service.models_dir / "selection.json").write_text(json.dumps({"transcription": PARAKEET}))
    assert service.list_models()["active"]["transcription"] == PARAKEET


def test_an_engine_whose_provenance_names_another_commit_is_not_ready(service: local_models.LocalModelService) -> None:
    install_engine(service, commit="b" * 40)
    assert view(service, ENGINE)["state"] == "managed" and view(service, ENGINE)["location"] is None


def test_the_desktop_app_cli_lives_in_its_runtime_and_its_provenance_in_the_engine_home(
    service: local_models.LocalModelService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_engine(service)
    runtime_cli = tmp_path / "runtime" / "bin" / "fluidaudiocli"
    runtime_cli.parent.mkdir(parents=True)
    (service.managed_dirs["fluidaudio"] / "bin" / "fluidaudiocli").rename(runtime_cli)
    assert view(service, ENGINE)["location"] is None
    monkeypatch.setenv("SAURI_PARAKEET_CLI", str(runtime_cli))
    assert view(service, ENGINE)["location"] == "managed"
    (service.managed_dirs["fluidaudio"] / "provenance.json").unlink()
    assert view(service, ENGINE)["location"] is None


def test_the_gateway_helpers_pick_the_preferred_model_only_when_ready(service: local_models.LocalModelService) -> None:
    write_bundle(service.models_dir / "parakeet-dir")
    asyncio.run(_adopt(service))
    kwargs: dict[str, Any] = {"process": "transcription", "models_dir": service.models_dir, "catalog": service.catalog}
    selected = select_preferred(**kwargs)
    assert selected is not None and selected.model_id == PARAKEET and selected.engine == "fluidaudio"
    assert selected.path == service.models_dir / "parakeet-dir"
    assert select_preferred(ready=lambda _entry: False, **kwargs) is None
    explicit = select_local_model(_header(PARAKEET), **kwargs)
    assert explicit is not None and explicit.path == selected.path
    assert select_local_model(_header("default"), **kwargs) is None  # local:default is resolved by the gateway


def _header(model: str) -> str:
    from sauri_engine_common.route import Route, encode_route

    return encode_route(
        Route(
            version=1,
            capability="transcription",
            kind="local",
            transport=None,
            base_url=None,
            model=f"local:{model}",
            secret_ref=None,
            consent_version=None,
        )
    )


# --- seed (adoption of an existing copy) --------------------------------------------------------------


def test_seed_copies_a_verified_bundle_and_leaves_the_source_untouched(
    service: local_models.LocalModelService, tmp_path: Path
) -> None:
    source = tmp_path / "bench"
    write_bundle(source)
    before = {p: p.stat().st_mtime_ns for p in source.rglob("*") if p.is_file()}
    assert local_models.seed_bundle(service, PARAKEET, source) == "installed"
    assert view(service, PARAKEET)["state"] == "installed"
    assert before == {p: p.stat().st_mtime_ns for p in source.rglob("*") if p.is_file()}
    copied = service.models_dir / "parakeet-dir" / "c.json"
    assert copied.read_bytes() == FILES["c.json"] and not stat.S_ISLNK(copied.lstat().st_mode)
    assert local_models.seed_bundle(service, PARAKEET, source) == "installed"  # idempotent


def test_seed_refuses_a_source_that_differs_and_leaves_nothing(
    service: local_models.LocalModelService, tmp_path: Path
) -> None:
    source = tmp_path / "bench"
    write_bundle(source)
    (source / "c.json").write_bytes(b'{"synthetic": fals}')
    with pytest.raises(local_models.LocalModelError) as error:
        local_models.seed_bundle(service, PARAKEET, source)
    assert error.value.code == "source_hash_mismatch"
    assert not service.models_dir.exists() or list(service.models_dir.iterdir()) == []
    (source / "c.json").unlink()
    with pytest.raises(local_models.LocalModelError) as missing:
        local_models.seed_bundle(service, PARAKEET, source)
    assert missing.value.code == "source_file_missing_or_resized"
