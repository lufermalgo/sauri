"""Local model catalog and the pure hardware-based recommendation.

``recommend(hardware, catalog)`` has no I/O and no clock: the same inputs always give the same answer.

Decision table (a candidate is *eligible* when ``min_ram_gib <= memory_gib`` and every item of its
``requires`` is satisfied by the hardware; ``metal`` means Apple silicon on macOS). Per process the
eligible candidate with the highest ``rank`` wins; ``auxiliary`` entries are never recommended.

=============  ==========================================  =====================================
process        rule                                        otherwise
=============  ==========================================  =====================================
transcription  Parakeet ultra (rank 3) if Metal, macOS 14+ turbo q5_0 (rank 2) if Metal and RAM
               and RAM >= 8                                >= 8; small q5_1 (rank 1) if RAM >= 4,
                                                           warning ``no_metal_slow`` without Metal
summary        9B (rank 2) if RAM >= 16;                   no local model below 8 GiB
               4B (rank 1) if RAM >= 8
diarization    Senko if Metal                              no local model
=============  ==========================================  =====================================

Examples (Apple silicon, Metal available):

* 8 GiB: transcription -> Parakeet ultra (fits); summary -> 4B (``reduced``; warnings
  ``unmeasured_proposal``, ``lower_quality_expected``, ``suggest_external_provider``);
  diarization -> Senko.
* 16 GiB: transcription -> Parakeet ultra; summary -> 9B (fits); diarization -> Senko.
* 24 GiB: same as 16 GiB (the catalog has nothing larger than the 9B).

Without Metal (for example an Intel Mac) transcription falls back to small q5_1 with the warning
``no_metal_slow`` and diarization has no local model. A ``preferred`` model that the hardware cannot run
(Parakeet on macOS 13) never makes the answer ``reduced``: it is the faster choice, not the better one.

Every result carries ``reason_key`` plus ``reason_params`` (a copy key and its parameters, never a
sentence) and ``status``, the catalog mark ``measured`` (the team measured it) or ``proposal``.
Because eligibility only grows with memory, the recommended rank never drops when memory grows
(Property 9), and a model whose ``min_ram_gib`` exceeds the detected memory is never recommended.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, cast

from sauri_engine_common.model_bundle import MAX_BUNDLE_FILES, BundleFile, bundle_digest, bundle_size, safe_relative

Process = Literal["transcription", "summary", "diarization"]
Kind = Literal["model", "auxiliary", "managed_engine"]
Status = Literal["measured", "proposal"]

PROCESSES: Final[tuple[Process, ...]] = ("transcription", "summary", "diarization")
KINDS: Final = frozenset({"model", "auxiliary", "managed_engine"})
STATUSES: Final = frozenset({"measured", "proposal"})
CAPABILITIES: Final = frozenset({"metal"})
CATALOG_VERSION: Final = 1
DEFAULT_CATALOG_PATH: Final = Path(__file__).resolve().parents[3] / "scripts" / "engines" / "model-catalog.json"

_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class CatalogError(ValueError):
    """The catalog file is malformed; the message names the field, never a value."""


@dataclass(frozen=True)
class HardwareProfile:
    arch: str
    memory_gib: float
    cores: int
    metal: bool
    disk_free_bytes: int = 0
    system: str = ""
    macos_major: int = 0  # 0 when unknown or not macOS

    def has(self, capability: str) -> bool:
        return capability == "metal" and self.metal


@dataclass(frozen=True)
class CatalogModel:
    id: str
    process: Process
    kind: Kind
    engine: str
    repo: str
    revision: str
    file: str | None
    size: int | None
    sha256: str | None
    min_ram_gib: int
    requires: tuple[str, ...]
    rank: int
    status: Status
    default: bool
    managed_by: str | None = None
    # Several files in a directory (``file`` names the directory; ``size`` and ``sha256`` describe the listing).
    files: tuple[BundleFile, ...] = ()
    # ``local:default`` resolves to this model when it is installed and healthy; the ``default`` model is the fallback.
    preferred: bool = False
    # Id of the managed engine this model cannot run without.
    needs: str | None = None
    min_macos: int | None = None
    license: str | None = None
    attribution: str | None = None

    @property
    def bundle(self) -> bool:
        return bool(self.files)

    @property
    def downloadable(self) -> bool:
        return self.kind != "managed_engine"


@dataclass(frozen=True)
class Catalog:
    version: int
    models: tuple[CatalogModel, ...]

    def get(self, model_id: str) -> CatalogModel | None:
        return next((model for model in self.models if model.id == model_id), None)


@dataclass(frozen=True)
class Recommendation:
    process: Process
    model_id: str | None
    status: Status | None
    reason_key: str
    reason_params: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "process": self.process,
            "model_id": self.model_id,
            "status": self.status,
            "reason_key": self.reason_key,
            "reason_params": dict(self.reason_params),
            "warnings": list(self.warnings),
        }


def _require(condition: bool, field_name: str) -> None:
    if not condition:
        raise CatalogError(f"invalid_catalog_{field_name}")


def _parse_bundle(raw: Any) -> tuple[BundleFile, ...]:
    if raw is None:
        return ()
    _require(isinstance(raw, list) and 0 < len(raw) <= MAX_BUNDLE_FILES, "files")
    files: list[BundleFile] = []
    for item in raw:
        _require(isinstance(item, dict), "files")
        path, size, sha256 = item.get("path"), item.get("size"), item.get("sha256")
        _require(isinstance(path, str) and safe_relative(path), "files")
        _require(type(size) is int and size > 0, "files")
        _require(isinstance(sha256, str) and _SHA256.fullmatch(sha256) is not None, "files")
        files.append(BundleFile(path, size, sha256))
    _require(len({f.path for f in files}) == len(files), "files")
    return tuple(files)


def _parse_model(raw: Any) -> CatalogModel:
    _require(isinstance(raw, dict), "entry")
    entry: dict[str, Any] = raw
    model_id: Any = entry.get("id")
    process: Any = entry.get("process")
    kind: Any = entry.get("kind")
    _require(isinstance(model_id, str) and _ID.fullmatch(model_id) is not None, "id")
    _require(process in PROCESSES, "process")
    _require(kind in KINDS, "kind")
    _require(isinstance(entry.get("engine"), str) and entry["engine"] != "", "engine")
    _require(isinstance(entry.get("repo"), str) and _REPO.fullmatch(entry["repo"]) is not None, "repo")
    _require(isinstance(entry.get("revision"), str) and _REVISION.fullmatch(entry["revision"]) is not None, "revision")
    min_ram: Any = entry.get("min_ram_gib")
    rank: Any = entry.get("rank")
    _require(type(min_ram) is int and min_ram >= 0, "min_ram_gib")
    _require(type(rank) is int and rank >= 0, "rank")
    requires: Any = entry.get("requires")
    _require(isinstance(requires, list) and set(requires) <= CAPABILITIES, "requires")
    _require(entry.get("status") in STATUSES, "status")
    _require(type(entry.get("default")) is bool, "default")
    file, size, sha256, managed_by = entry.get("file"), entry.get("size"), entry.get("sha256"), entry.get("managed_by")
    bundle = _parse_bundle(entry.get("files"))
    if kind == "managed_engine":
        _require(isinstance(managed_by, str) and managed_by != "", "managed_by")
        _require(file is None and size is None and sha256 is None and not bundle, "managed_files")
    else:
        _require(isinstance(file, str) and _FILE.fullmatch(file) is not None and ".." not in file, "file")
        _require(type(size) is int and size > 0, "size")
        _require(isinstance(sha256, str) and _SHA256.fullmatch(sha256) is not None, "sha256")
        if bundle:
            _require(kind == "model" and size == bundle_size(bundle) and sha256 == bundle_digest(bundle), "bundle")
    preferred, needs, min_macos = entry.get("preferred", False), entry.get("needs"), entry.get("min_macos")
    _require(type(preferred) is bool and (not preferred or kind == "model"), "preferred")
    _require(needs is None or (isinstance(needs, str) and _ID.fullmatch(needs) is not None), "needs")
    _require(min_macos is None or (type(min_macos) is int and min_macos > 0), "min_macos")
    licence, attribution = entry.get("license"), entry.get("attribution")
    _require(licence is None or (isinstance(licence, str) and 0 < len(licence) <= 64), "license")
    _require(attribution is None or (isinstance(attribution, str) and 0 < len(attribution) <= 1024), "attribution")
    return CatalogModel(
        id=cast(str, model_id),
        process=cast(Process, process),
        kind=cast(Kind, kind),
        engine=entry["engine"],
        repo=entry["repo"],
        revision=entry["revision"],
        file=file,
        size=size,
        sha256=sha256,
        min_ram_gib=cast(int, min_ram),
        requires=tuple(cast(list[str], requires)),
        rank=cast(int, rank),
        status=entry["status"],
        default=entry["default"],
        managed_by=managed_by,
        files=bundle,
        preferred=preferred,
        needs=needs,
        min_macos=min_macos,
        license=licence,
        attribution=attribution,
    )


def parse_catalog(raw: Any) -> Catalog:
    _require(isinstance(raw, dict) and raw.get("catalog_version") == CATALOG_VERSION, "version")
    entries = raw.get("models")
    _require(isinstance(entries, list) and entries != [], "models")
    models = tuple(_parse_model(entry) for entry in entries)
    _require(len({model.id for model in models}) == len(models), "duplicate_id")
    files = [(model.process, model.file) for model in models if model.file]
    _require(len({file for _, file in files}) == len(files), "duplicate_file")
    for process in PROCESSES:
        defaults = [model for model in models if model.process == process and model.kind == "model" and model.default]
        _require(len(defaults) <= 1, "default")
        preferred = [model for model in models if model.process == process and model.preferred]
        _require(len(preferred) <= 1, "preferred")
    ids = {model.id: model for model in models}
    for model in models:
        if model.needs is not None:
            dependency = ids.get(model.needs)
            _require(dependency is not None and dependency.kind == "managed_engine", "needs")
    return Catalog(version=CATALOG_VERSION, models=models)


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> Catalog:
    try:
        return parse_catalog(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise CatalogError("catalog_unreadable") from None


def _blocker(model: CatalogModel, hardware: HardwareProfile) -> str | None:
    if model.min_ram_gib > hardware.memory_gib:
        return "memory"
    if any(not hardware.has(capability) for capability in model.requires):
        return "metal"
    if model.min_macos is not None and hardware.macos_major < model.min_macos:
        return "macos"
    return None


def _recommend_process(process: Process, hardware: HardwareProfile, models: Iterable[CatalogModel]) -> Recommendation:
    models = list(models)
    dependencies = {model.needs for model in models if model.needs}
    candidates = sorted(
        (
            model for model in models
            if model.process == process and model.kind != "auxiliary" and model.id not in dependencies
        ),
        key=lambda model: (-model.rank, model.id),
    )
    params: dict[str, Any] = {"memory_gib": hardware.memory_gib}
    eligible = [model for model in candidates if _blocker(model, hardware) is None]
    if not eligible:
        if not candidates:
            return Recommendation(process, None, None, "no_local_model", params)
        blockers = {_blocker(model, hardware) for model in candidates}
        params["needs"] = next(iter(blockers)) if len(blockers) == 1 else "memory"
        params["min_ram_gib"] = min(model.min_ram_gib for model in candidates)
        advice = ("suggest_external_provider",) if process == "summary" else ()
        return Recommendation(process, None, None, "no_local_model", params, advice)
    chosen = eligible[0]
    params["min_ram_gib"] = chosen.min_ram_gib
    warnings: list[str] = []
    if chosen.status == "proposal":
        warnings.append("unmeasured_proposal")
    # A preferred model the hardware cannot run is the faster choice, not the better one: it never "reduces" the answer.
    top = next(model for model in candidates if not (model.preferred and _blocker(model, hardware) is not None))
    if chosen is top:
        reason = "fits"
    else:
        reason = "reduced"
        params["better_id"] = top.id
        params["limited_by"] = _blocker(top, hardware)
        warnings.append("lower_quality_expected")
        if process == "summary":
            warnings.append("suggest_external_provider")
    if process == "transcription" and not hardware.metal:
        warnings.append("no_metal_slow")
    return Recommendation(process, chosen.id, chosen.status, reason, params, tuple(warnings))


def recommend(hardware: HardwareProfile, catalog: Catalog) -> dict[Process, Recommendation]:
    """Pure recommendation for every process; see the module docstring for the decision table."""
    return {process: _recommend_process(process, hardware, catalog.models) for process in PROCESSES}
