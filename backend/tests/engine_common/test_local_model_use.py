"""Gateway-side model selection: catalog lookup, manifest validation and the legacy default location."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest
from sauri_engine_common.local_model_use import (
    LocalModelError,
    LocalSelection,
    legacy_path_for,
    select_local_model,
)
from sauri_engine_common.recommend import Catalog, Process, parse_catalog

from tests.local_models_support import (
    BIG,
    SMALL,
    adopt_legacy,
    catalog_entry,
    install_custom,
    install_model,
    route_header,
)

DEFAULT = catalog_entry("llm-big", "summary", "big.gguf", BIG, default=True, rank=2)
SMALLER = catalog_entry("llm-small", "summary", "small.gguf", SMALL)
WHISPER = catalog_entry("asr-one", "transcription", "asr.bin", SMALL, default=True)
VAD = catalog_entry("asr-vad", "transcription", "vad.bin", SMALL, kind="auxiliary")
CATALOG: Catalog = parse_catalog({"catalog_version": 1, "models": [DEFAULT, SMALLER, WHISPER, VAD]})


def select(
    header: str | None, models_dir: Path, *, process: Process = "summary", legacy_default: Path | None = None
) -> LocalSelection | None:
    return select_local_model(
        header, process=process, legacy_default=legacy_default, models_dir=models_dir, catalog=CATALOG
    )


def refused(
    header: str | None, models_dir: Path, *, process: Process = "summary", legacy_default: Path | None = None
) -> LocalModelError:
    with pytest.raises(LocalModelError) as raised:
        select(header, models_dir, process=process, legacy_default=legacy_default)
    return raised.value


def test_no_header_and_default_keep_the_built_in_model(tmp_path: Path) -> None:
    assert select(None, tmp_path) is None
    assert select(route_header("local:default"), tmp_path) is None


def test_installed_model_resolves_to_its_catalog_file(tmp_path: Path) -> None:
    final = install_model(tmp_path, SMALLER, SMALL)
    chosen = select(route_header("local:llm-small"), tmp_path)
    assert chosen is not None and chosen.model_id == "llm-small" and chosen.path == final


def test_missing_file_is_model_not_installed(tmp_path: Path) -> None:
    error = refused(route_header("local:llm-small"), tmp_path)
    assert (error.status, error.code) == (409, "model_not_installed")


@pytest.mark.parametrize("status", ["corrupt", "unknown"])
def test_manifest_must_say_installed(tmp_path: Path, status: str) -> None:
    install_model(tmp_path, SMALLER, SMALL, status=status)
    assert refused(route_header("local:llm-small"), tmp_path).code == "model_not_verified"


def test_file_without_manifest_is_not_trusted(tmp_path: Path) -> None:
    (tmp_path / "small.gguf").write_bytes(SMALL)
    assert refused(route_header("local:llm-small"), tmp_path).code == "model_not_verified"


def test_changed_mtime_or_size_invalidates_the_manifest(tmp_path: Path) -> None:
    final = install_model(tmp_path, SMALLER, SMALL)
    info = final.stat()
    os.utime(final, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    assert refused(route_header("local:llm-small"), tmp_path).code == "model_not_verified"
    final = install_model(tmp_path, SMALLER, SMALL)
    final.write_bytes(SMALL + b"x")
    os.utime(final, ns=(info.st_atime_ns, final.stat().st_mtime_ns))
    assert refused(route_header("local:llm-small"), tmp_path).code == "model_not_verified"


def test_manifest_for_another_hash_is_refused(tmp_path: Path) -> None:
    install_model(tmp_path, {**SMALLER, "sha256": "f" * 64}, SMALL)
    assert refused(route_header("local:llm-small"), tmp_path).code == "model_not_verified"


def test_a_symlink_is_never_a_model(tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(SMALL)
    models = tmp_path / "models"
    install_model(models, SMALLER, SMALL)
    (models / "small.gguf").unlink()
    (models / "small.gguf").symlink_to(outside)
    assert refused(route_header("local:llm-small"), models).code == "model_not_installed"


@pytest.mark.parametrize("model", ["local:nope", "local:", "local:asr-one", "local:asr-vad"])
def test_unknown_wrong_process_or_auxiliary_ids_are_unknown_models(tmp_path: Path, model: str) -> None:
    error = refused(route_header(model), tmp_path)
    assert (error.status, error.code) == (422, "unknown_model")


def test_legacy_location_serves_only_the_process_default(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy" / "old-name.gguf"
    legacy.parent.mkdir()
    legacy.write_bytes(BIG)
    models = tmp_path / "models"
    models.mkdir()
    chosen = select(route_header("local:llm-big"), models, legacy_default=legacy)
    assert chosen is not None and chosen.path == legacy
    # Not the default: the legacy path is never offered for another model.
    assert refused(route_header("local:llm-small"), models, legacy_default=legacy).code == "model_not_installed"
    # A legacy file of another size is not the catalog model.
    legacy.write_bytes(BIG + b"x")
    assert refused(route_header("local:llm-big"), models, legacy_default=legacy).code == "model_not_installed"


def test_catalog_entry_wins_over_the_legacy_location(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.gguf"
    legacy.write_bytes(BIG)
    models = tmp_path / "models"
    final = install_model(models, DEFAULT, BIG)
    chosen = select(route_header("local:llm-big"), models, legacy_default=legacy)
    assert chosen is not None and chosen.path == final


@pytest.mark.parametrize(
    ("header", "code"),
    [
        ("not-base64-@@", "route_malformed"),
        (route_header("local:llm-small", process="transcription"), "route_capability_mismatch"),
        (route_header("gpt-x", kind="openai"), "route_not_supported"),
        (route_header("llm-small"), "route_malformed"),
    ],
)
def test_bad_routes_are_refused_with_a_code(tmp_path: Path, header: str, code: str) -> None:
    error = refused(header, tmp_path)
    assert (error.status, error.code) == (422, code)


def test_transcription_gateway_resolves_its_own_models(tmp_path: Path) -> None:
    final = install_model(tmp_path, WHISPER, SMALL)
    chosen = select(route_header("local:asr-one", process="transcription"), tmp_path, process="transcription")
    assert chosen is not None and chosen.path == final
    assert refused(route_header("local:llm-big", process="transcription"), tmp_path, process="transcription").code == (
        "unknown_model"
    )


# --- adopted files (models installed by hand, recognized by host-engine) ---------------------------


def test_an_adopted_legacy_file_resolves_through_its_manifest_and_stays_in_place(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy" / "old-name.gguf"
    legacy.parent.mkdir()
    legacy.write_bytes(BIG)
    models = tmp_path / "models"
    adopt_legacy(models, DEFAULT, legacy)
    chosen = select(route_header("local:llm-big"), models, legacy_default=legacy)
    assert chosen is not None and chosen.path == legacy
    assert [path.name for path in models.iterdir()] == ["big.gguf.manifest.json"]  # nothing was copied or moved


def test_an_adopted_legacy_file_replaced_afterwards_is_refused(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.gguf"
    legacy.write_bytes(BIG)
    models = tmp_path / "models"
    adopt_legacy(models, DEFAULT, legacy)
    info = legacy.stat()
    os.utime(legacy, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    error = refused(route_header("local:llm-big"), models, legacy_default=legacy)
    assert (error.status, error.code) == (409, "model_not_verified")


@pytest.mark.parametrize("status", ["present_unverified", "corrupt"])
def test_a_legacy_file_judged_different_from_the_catalog_is_not_served(tmp_path: Path, status: str) -> None:
    legacy = tmp_path / "legacy.gguf"
    legacy.write_bytes(BIG)
    models = tmp_path / "models"
    adopt_legacy(models, DEFAULT, legacy, status=status)
    assert refused(route_header("local:llm-big"), models, legacy_default=legacy).code == "model_not_verified"


def test_a_legacy_manifest_does_not_vouch_for_a_file_in_the_models_directory(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.gguf"
    legacy.write_bytes(BIG)
    models = tmp_path / "models"
    adopt_legacy(models, DEFAULT, legacy)
    (models / "big.gguf").write_bytes(BIG)  # a different file, same size, never verified
    error = refused(route_header("local:llm-big"), models)
    assert error.code == "model_not_verified"
    manifest_only = tmp_path / "other"
    adopt_legacy(manifest_only, DEFAULT, legacy)
    assert refused(route_header("local:llm-big"), manifest_only).code == "model_not_installed"


def test_a_manifest_written_before_adoption_existed_still_means_the_models_directory(tmp_path: Path) -> None:
    final = install_model(tmp_path, SMALLER, SMALL)
    manifest = final.with_name(final.name + ".manifest.json")
    record = json.loads(manifest.read_text())
    assert "location" not in record
    chosen = select(route_header("local:llm-small"), tmp_path)
    assert chosen is not None and chosen.path == final


def test_legacy_paths_follow_the_gateways_built_in_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SAURI_LLM_MODEL_FILE", raising=False)
    monkeypatch.delenv("ASR_MODEL_PATH", raising=False)
    parsed = {model.id: model for model in CATALOG.models}
    assert legacy_path_for(parsed["llm-big"]) == tmp_path / ".local/share/sauri/native-engines/llm/models/big.gguf"
    assert legacy_path_for(parsed["llm-small"]) is None  # only a process default can live there
    assert legacy_path_for(parsed["asr-one"]) is None and legacy_path_for(parsed["asr-vad"]) is None
    monkeypatch.setenv("SAURI_LLM_MODEL_FILE", str(tmp_path / "x.gguf"))
    monkeypatch.setenv("ASR_MODEL_PATH", str(tmp_path / "x.bin"))
    assert legacy_path_for(parsed["llm-big"]) == tmp_path / "x.gguf"
    assert legacy_path_for(parsed["asr-one"]) == tmp_path / "x.bin"


# --- custom models (local:custom-<16 hex>) ----------------------------------------------------------


def test_a_registered_and_verified_custom_model_is_selected_with_its_engine(tmp_path: Path) -> None:
    model_id, final = install_custom(tmp_path, "summary", SMALL, "sub/model-Q4_K_M.gguf")
    chosen = select(route_header(f"local:{model_id}"), tmp_path)
    assert chosen == LocalSelection(model_id, final, "llama.cpp")
    asr_id, asr_file = install_custom(tmp_path, "transcription", BIG, "ggml-tiny.bin")
    chosen = select(route_header(f"local:{asr_id}", process="transcription"), tmp_path, process="transcription")
    assert chosen == LocalSelection(asr_id, asr_file, "whisper.cpp")


def test_a_custom_model_that_cannot_be_used_falls_back_to_the_default_and_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_id, final = install_custom(tmp_path, "summary", SMALL, "model.gguf")
    unverified_id, _ = install_custom(tmp_path, "summary", BIG, "other.gguf", manifest=False)
    cases = {
        "custom-0123456789abcdef": "reason=not_registered",
        unverified_id: "reason=model_not_verified",
    }
    with caplog.at_level(logging.WARNING, logger="sauri.engine.local_model_use"):
        for missing, reason in cases.items():
            assert select(route_header(f"local:{missing}"), tmp_path) is None
            assert reason in caplog.text
        # Registered for another process: never served by this gateway.
        header = route_header(f"local:{model_id}", process="transcription")
        assert select(header, tmp_path, process="transcription") is None
        # Replaced after the install: the manifest no longer vouches for it.
        final.write_bytes(SMALL + b"changed")
        assert select(route_header(f"local:{model_id}"), tmp_path) is None
        final.unlink()
        assert select(route_header(f"local:{model_id}"), tmp_path) is None
    assert "model_not_installed" in caplog.text and str(tmp_path) not in caplog.text


def test_an_unreadable_or_tampered_registry_selects_nothing(tmp_path: Path) -> None:
    model_id, _final = install_custom(tmp_path, "summary", SMALL, "model.gguf")
    registry = tmp_path / "custom_models.json"
    record = json.loads(registry.read_text())["models"][0]
    registry.write_text(json.dumps({"version": 1, "models": [record | {"path": "../model.gguf"}]}))
    assert select(route_header(f"local:{model_id}"), tmp_path) is None
    registry.write_text("{not json")
    assert select(route_header(f"local:{model_id}"), tmp_path) is None
