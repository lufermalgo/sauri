"""Synthetic catalog and installed-model files shared by the gateway tests (no real model, no download)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine-common"))

from sauri_engine_common.local_model_use import MANIFEST_SUFFIX  # noqa: E402
from sauri_engine_common.recommend import Process  # noqa: E402
from sauri_engine_common.route import Route, encode_route  # noqa: E402

REVISION = "a" * 40
BIG = b"big-synthetic-model" * 50
SMALL = b"small-synthetic-model" * 20


def catalog_entry(model_id: str, process: str, file: str, data: bytes, **extra: Any) -> dict[str, Any]:
    return {
        "id": model_id, "process": process, "kind": "model", "engine": "synthetic", "repo": "test/repo",
        "revision": REVISION, "file": file, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "min_ram_gib": 4, "requires": [], "rank": 1, "status": "measured", "default": False, **extra,
    }  # fmt: skip


def write_catalog(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps({"catalog_version": 1, "models": entries}), encoding="utf-8")
    return path


def install_model(models_dir: Path, entry: dict[str, Any], data: bytes, *, status: str = "installed") -> Path:
    """Write the model file and a manifest like the one ``host-engine`` writes after a verified install."""
    models_dir.mkdir(parents=True, exist_ok=True)
    final = models_dir / entry["file"]
    final.write_bytes(data)
    info = final.stat()
    record = {
        "id": entry["id"], "file": entry["file"], "revision": entry["revision"], "sha256": entry["sha256"],
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "installed_at": "2026-01-01T00:00:00+00:00",
        "status": status,
    }  # fmt: skip
    final.with_name(final.name + MANIFEST_SUFFIX).write_text(json.dumps(record), encoding="utf-8")
    return final


def route_header(model: str, *, process: Process = "summary", kind: str = "local") -> str:
    capability = "transcription" if process == "transcription" else "summary"
    return encode_route(Route(
        version=1, capability=capability, kind=kind, transport=None if kind == "local" else "openai-chat",
        base_url=None if kind == "local" else "https://api.example.com", model=model, secret_ref=None,
        consent_version=None,
    ))  # fmt: skip


__all__ = ["BIG", "SMALL", "catalog_entry", "install_model", "route_header", "write_catalog"]
