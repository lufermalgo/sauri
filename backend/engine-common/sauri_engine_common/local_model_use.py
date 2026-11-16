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
DEFAULT_MODEL: Final = "default"
LOCAL_PREFIX: Final = "local:"
# Route capabilities each gateway process serves.
_CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    "transcription": frozenset({"transcription"}),
    "summary": frozenset({"summary", "chat"}),
}


def default_models_dir() -> Path:
    return Path(os.getenv("SAURI_MODELS_DIR", Path.home() / ".local" / "share" / "sauri" / "models"))


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


def _manifest_matches(manifest: Path, info: os.stat_result, entry: CatalogModel) -> bool:
    try:
        record: Any = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(record, dict)
        and record.get("status") == "installed"
        and record.get("sha256") == entry.sha256
        and record.get("size") == info.st_size == entry.size
        and record.get("mtime_ns") == info.st_mtime_ns
    )


def _locate(entry: CatalogModel, models_dir: Path, legacy_default: Path | None) -> Path:
    assert entry.file is not None
    final = models_dir / entry.file
    info = _regular(final)
    if info is not None and _manifest_matches(final.with_name(final.name + MANIFEST_SUFFIX), info, entry):
        return final
    if entry.default and legacy_default is not None:
        legacy = _regular(legacy_default)
        if legacy is not None and legacy.st_size == entry.size:
            return legacy_default
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
