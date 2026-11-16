"""The versioned local model catalog: schema, pinned revisions and coherence with engine-hashes.json."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sauri_engine_common.recommend import DEFAULT_CATALOG_PATH, CatalogError, load_catalog, parse_catalog

ROOT = Path(__file__).resolve().parents[3]
RAW: dict[str, Any] = json.loads((ROOT / "scripts/engines/model-catalog.json").read_text())
HASHES: dict[str, Any] = json.loads((ROOT / "scripts/engines/engine-hashes.json").read_text())


def test_default_catalog_path_is_the_repository_file() -> None:
    assert DEFAULT_CATALOG_PATH == ROOT / "scripts/engines/model-catalog.json"
    assert len(load_catalog().models) == len(RAW["models"])


def test_every_downloadable_entry_is_pinned_to_a_commit_with_size_and_hash() -> None:
    for model in load_catalog().models:
        assert len(model.revision) == 40 and model.revision not in {"main", "master"}
        if model.downloadable:
            assert model.size and model.size > 0 and model.sha256 and len(model.sha256) == 64


def test_senko_is_a_managed_engine_without_a_download() -> None:
    senko = load_catalog().get("senko-coreml")
    assert senko is not None and not senko.downloadable
    assert senko.managed_by == "scripts/engines/install-diar-engine.sh"
    assert senko.revision == HASHES["senko"]["commit"]


def test_the_catalog_matches_engine_hashes_for_every_default_model() -> None:
    """Property 16: name, revision and SHA-256 of the defaults equal engine-hashes.json."""
    catalog = load_catalog()
    asr, llm, vad = HASHES["asr"], HASHES["llm"], HASHES["asr"]["vad"]
    expected = {
        "whisper-large-v3-turbo-q5_0": (
            asr["model_repo"],
            asr["model_revision"],
            asr["model_file"],
            asr["model_sha256"],
        ),
        "qwen3.5-9b-q4_k_m": (llm["model_repo"], llm["model_revision"], llm["model_file"], llm["model_sha256"]),
        "silero-vad-v6.2.0": (
            "ggml-org/whisper-vad",
            vad["model_url"].split("/resolve/")[1].split("/")[0],
            vad["model_file"],
            vad["model_sha256"],
        ),
    }
    for model_id, (repo, revision, file, sha256) in expected.items():
        model = catalog.get(model_id)
        assert model is not None and model.default
        assert (model.repo, model.revision, model.file, model.sha256) == (repo, revision, file, sha256)
    assert catalog.get("whisper-large-v3-turbo-q5_0").size == asr["model_size"]  # type: ignore[union-attr]
    assert catalog.get("silero-vad-v6.2.0").size == vad["model_size"]  # type: ignore[union-attr]
    defaults = {model.id for model in catalog.models if model.default}
    assert defaults == {*expected, "senko-coreml"}


def test_the_unmeasured_4b_stays_a_proposal() -> None:
    four = load_catalog().get("qwen3.5-4b-q4_k_m")
    assert four is not None and four.status == "proposal" and not four.default


def mutated(change: Any) -> dict[str, Any]:
    raw = copy.deepcopy(RAW)
    change(raw)
    return raw


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(catalog_version=2),
        lambda r: r["models"][0].update(revision="main"),
        lambda r: r["models"][0].update(sha256="ABC"),
        lambda r: r["models"][0].update(size=0),
        lambda r: r["models"][0].update(file="../evil.bin"),
        lambda r: r["models"][0].update(file="a/b.bin"),
        lambda r: r["models"][0].update(repo="evil"),
        lambda r: r["models"][0].update(process="chat"),
        lambda r: r["models"][0].update(status="maybe"),
        lambda r: r["models"][0].update(requires=["cuda"]),
        lambda r: r["models"][1].update(id=r["models"][0]["id"]),
        lambda r: r["models"][1].update(file=r["models"][0]["file"]),
        lambda r: r["models"][-1].update(sha256="0" * 64, file="x.bin", size=1),
        lambda r: r["models"][1].update(default=True),
        lambda r: r.update(models=[]),
    ],
)
def test_a_malformed_catalog_is_rejected(change: Any) -> None:
    with pytest.raises(CatalogError):
        parse_catalog(mutated(change))


def test_an_unreadable_file_is_a_catalog_error(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{")
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "bad.json")
    with pytest.raises(CatalogError):
        load_catalog(tmp_path / "missing.json")
