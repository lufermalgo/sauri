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


def adopt_legacy(
    models_dir: Path, entry: dict[str, Any], legacy: Path, *, status: str = "installed", location: str = "legacy"
) -> Path:
    """Write the manifest ``host-engine`` writes when it adopts a file that stays at its legacy location."""
    models_dir.mkdir(parents=True, exist_ok=True)
    info = legacy.stat()
    record = {
        "id": entry["id"], "file": entry["file"], "revision": entry["revision"], "sha256": entry["sha256"],
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "installed_at": "2026-01-01T00:00:00+00:00",
        "status": status, "location": location,
    }  # fmt: skip
    manifest = models_dir / (entry["file"] + MANIFEST_SUFFIX)
    manifest.write_text(json.dumps(record), encoding="utf-8")
    return manifest


def install_custom(
    models_dir: Path, process: str, data: bytes, repo_path: str, *, manifest: bool = True
) -> tuple[str, Path]:
    """Register a custom model and write its file (and, by default, the manifest ``host-engine`` writes)."""
    digest = hashlib.sha256(data).hexdigest()
    record = {"process": process, "repo": "someone/custom", "revision": "c" * 40, "path": repo_path,
              "size": len(data), "sha256": digest, "license": None, "installed_at": None}  # fmt: skip
    registry = models_dir / "custom_models.json"
    existing = json.loads(registry.read_text())["models"] if registry.exists() else []
    models_dir.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"version": 1, "models": [*existing, record]}), encoding="utf-8")
    final = models_dir / "custom" / f"{digest[:16]}-{repo_path.rsplit('/', 1)[-1]}"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(data)
    if manifest:
        info = final.stat()
        entry = {"id": f"custom-{digest[:16]}", "file": f"custom/{final.name}", "revision": "c" * 40,
                 "sha256": digest, "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                 "installed_at": "2026-01-01T00:00:00+00:00", "status": "installed",
                 "location": "models_dir"}  # fmt: skip
        final.with_name(final.name + MANIFEST_SUFFIX).write_text(json.dumps(entry), encoding="utf-8")
    return f"custom-{digest[:16]}", final


def route_header(model: str, *, process: Process = "summary", kind: str = "local") -> str:
    capability = "transcription" if process == "transcription" else "summary"
    return encode_route(Route(
        version=1, capability=capability, kind=kind, transport=None if kind == "local" else "openai-chat",
        base_url=None if kind == "local" else "https://api.example.com", model=model, secret_ref=None,
        consent_version=None,
    ))  # fmt: skip


__all__ = [
    "BIG", "SMALL", "adopt_legacy", "catalog_entry", "install_custom", "install_model", "route_header", "write_catalog",
]  # fmt: skip
