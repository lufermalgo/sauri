"""How the engine gateways pick the local model a request asks for (``X-Sauri-Route``: ``local:<id>``).

A gateway calls ``select_local_model`` once per request, before it touches any engine:

* No header, or a local route whose model is ``local:default``: returns ``None`` and the gateway keeps
  using its built-in model exactly as before this contract existed.
* ``local:<id>``: the id must be a ``model`` entry of the catalog for the gateway's process. The file
  is ``<models dir>/<catalog file>``, accepted only when its manifest (written by ``host-engine`` after
  a hash-verified install) says ``installed`` and the catalog SHA-256, the catalog size, the size on
  disk and ``mtime_ns`` all agree. The hash is never recomputed per request (a 5.7 GiB file would
  take far too long); a file replaced after the install changes ``mtime_ns`` and is refused.
* Legacy location: the process default model may predate the catalog and sit outside the models
  directory without a manifest (the 9B summary model lives in ``native-engines/llm/models``). When the
  catalog entry is missing or unverified there, ``select_local_model`` accepts the gateway's own
  built-in path for that default model if it is a regular file of the catalog size. Its hash was
  verified by the engine installer; no file is moved or deleted. Any other model never falls back.
* Adopted files: ``host-engine`` can recognize a model installed by hand (``adopt``). For a file in the
  models directory the manifest is the usual one. For a file still at the legacy location the manifest
  in the models directory carries ``"location": "legacy"`` and the legacy file's size and ``mtime_ns``;
  the gateway never reads a path from it, it only compares it with the gateway's own legacy path. A
  legacy file whose manifest is not ``installed`` or no longer matches (replaced or judged different
  from the catalog) is refused; without any manifest the size-only fallback above applies. A manifest
  without ``location`` (written before adoption existed) means the models directory.

Errors are ``LocalModelError`` with an HTTP status and a stable code, never a path or a value.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sauri_engine_common.recommend import Catalog, CatalogError, CatalogModel, Process, load_catalog
from sauri_engine_common.route import LOCAL_KIND, RouteError, decode_route

MANIFEST_SUFFIX: Final = ".manifest.json"
LOCATION_MODELS_DIR: Final = "models_dir"
LOCATION_LEGACY: Final = "legacy"
DEFAULT_MODEL: Final = "default"
LOCAL_PREFIX: Final = "local:"
# Route capabilities each gateway process serves.
_CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    "transcription": frozenset({"transcription"}),
    "summary": frozenset({"summary", "chat"}),
}


def default_models_dir() -> Path:
    return Path(os.getenv("SAURI_MODELS_DIR", Path.home() / ".local" / "share" / "sauri" / "models"))


def legacy_install_dir() -> Path:
    """Where the summary engine installer keeps its model (the gateway's own, fixed location)."""
    return Path.home() / ".local" / "share" / "sauri" / "native-engines" / "llm"


def legacy_path_for(entry: CatalogModel) -> Path | None:
    """The legacy file of a process default model, or None when the process has no such location.

    Mirrors the built-in paths of the gateways: ``SAURI_LLM_MODEL_FILE`` or ``<llm install>/models/<file>``
    for the summary default, an explicit ``ASR_MODEL_PATH`` for the transcription default. Only the
    default model of a process can live there.
    """
    if entry.kind != "model" or not entry.default or entry.file is None:
        return None
    if entry.process == "summary":
        override = os.getenv("SAURI_LLM_MODEL_FILE")
        return Path(override).expanduser() if override else legacy_install_dir() / "models" / entry.file
    if entry.process == "transcription":
        override = os.getenv("ASR_MODEL_PATH")
        return Path(override).expanduser() if override else None
    return None


class LocalModelError(Exception):
    """A request the gateway refuses: HTTP ``status`` and a stable ``code`` (the response detail)."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


@dataclass(frozen=True)
class LocalSelection:
    """A catalog model chosen by the route: its catalog id and the verified file to load."""

    model_id: str
    path: Path


def load_runtime_catalog() -> Catalog:
    path = os.getenv("SAURI_MODEL_CATALOG")
    try:
        return load_catalog(Path(path)) if path else load_catalog()
    except CatalogError:
        raise LocalModelError(503, "catalog_unavailable") from None


def _regular(path: Path) -> os.stat_result | None:
    """``lstat`` of a regular file (never a symlink), or None."""
    try:
        info = path.lstat()
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def read_manifest(manifest: Path) -> dict[str, Any] | None:
    try:
        record: Any = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def manifest_location(record: dict[str, Any]) -> str:
    """Where the manifest says the file is; manifests written before adoption existed have no field."""
    return LOCATION_LEGACY if record.get("location") == LOCATION_LEGACY else LOCATION_MODELS_DIR


def manifest_matches(record: dict[str, Any] | None, info: os.stat_result, entry: CatalogModel, location: str) -> bool:
    """The manifest vouches for exactly this file: installed, catalog hash and size, same ``mtime_ns``."""
    return (
        record is not None
        and manifest_location(record) == location
        and record.get("status") == "installed"
        and record.get("sha256") == entry.sha256
        and record.get("size") == info.st_size == entry.size
        and record.get("mtime_ns") == info.st_mtime_ns
    )


def _locate(entry: CatalogModel, models_dir: Path, legacy_default: Path | None) -> Path:
    assert entry.file is not None
    final = models_dir / entry.file
    info = _regular(final)
    record = read_manifest(final.with_name(final.name + MANIFEST_SUFFIX))
    if info is not None and manifest_matches(record, info, entry, LOCATION_MODELS_DIR):
        return final
    if entry.default and legacy_default is not None:
        legacy = _regular(legacy_default)
        if legacy is not None and legacy.st_size == entry.size:
            if record is None or manifest_location(record) != LOCATION_LEGACY:
                return legacy_default
            if manifest_matches(record, legacy, entry, LOCATION_LEGACY):
                return legacy_default
            # Adopted, then replaced or judged different from the catalog: the user must verify it again.
            raise LocalModelError(409, "model_not_verified")
    # A file without a valid manifest was never verified (or changed since): the user must verify it.
    raise LocalModelError(409, "model_not_installed" if info is None else "model_not_verified")


def select_local_model(
    header: str | None,
    *,
    process: Process,
    legacy_default: Path | None = None,
    models_dir: Path | None = None,
    catalog: Catalog | None = None,
) -> LocalSelection | None:
    """Resolve ``X-Sauri-Route`` for a gateway of ``process``; ``None`` keeps the built-in model."""
    try:
        route = decode_route(header)
    except RouteError as error:
        raise LocalModelError(422, error.reason or "route_malformed") from None
    if route is None:
        return None
    if route.capability not in _CAPABILITIES[process]:
        raise LocalModelError(422, "route_capability_mismatch")
    if route.kind != LOCAL_KIND:
        # External providers are served by their own adapters; this gateway path is local only.
        raise LocalModelError(422, "route_not_supported")
    if not route.model.startswith(LOCAL_PREFIX):
        raise LocalModelError(422, "route_malformed")
    model_id = route.model[len(LOCAL_PREFIX) :]
    if model_id == DEFAULT_MODEL:
        return None
    entry = (catalog or load_runtime_catalog()).get(model_id)
    if entry is None or entry.process != process or entry.kind != "model":
        raise LocalModelError(422, "unknown_model")
    return LocalSelection(entry.id, _locate(entry, models_dir or default_models_dir(), legacy_default))
