"""Local model management: catalog listing, verified installation, verification and removal.

Every route is mounted by ``native_main`` behind the management token. Security properties:

* Download URLs are built only from catalog fields (repository, pinned revision, file); no request
  field ever reaches a URL. The install and verify routes take no body and reject any query string.
* The URL and every redirect hop must be https on an allow-listed Hugging Face host; redirects are
  followed by hand so a hop to any other host is refused. The optional ``hf_token`` is sent only to
  ``huggingface.co`` itself (never to a CDN hop), and is never logged or returned.
* A download is capped at the catalog size, written to ``<file>.part`` (resumable with ``Range``),
  hashed incrementally and moved to its final name with ``os.replace`` only when the SHA-256 equals
  the catalog value. A failed, cancelled or tampered download leaves no ``.part`` behind.
* One job (install or verify) is active at a time; a second request gets 409.

Adoption (``adopt``): a Mac whose models were installed by hand (the file is already in the models
directory or, for a process default, at its legacy location) is recognized as if it had been installed
from here. Each present catalog file is size-checked and hashed once, in a worker thread and under an
``adopt`` job that reports progress; only when the SHA-256 equals the catalog value is the usual manifest
written (``location`` says ``legacy`` when the file stays where it is). Nothing is moved, copied, renamed,
deleted or downloaded. A file that differs from the catalog is never claimed: it is recorded as
``present_unverified`` (with the reason) so the next run does not hash it again until it changes.
A model made of several files (a CoreML bundle, ``files`` in the catalog) is a directory under the models
directory: it is downloaded file by file into ``<dir>.part/`` (every file hash-verified, completed files
kept across retries) and moved to its final name only when all of them match; its manifest records the
bundle digest and the size and ``mtime_ns`` of each file. ``seed_bundle`` copies a verified bundle from a
directory the operator names (never a request field), which is how a Mac that already has the files gets
them without downloading.
A managed engine (Senko) has no file: it is "installed" when its virtual environment holds the package
(presence only, never hashed; ``scripts/engines/install-diar-engine.sh --check`` does the hash check).

A component (the speaker runtime of the desktop app, design D9) is a runtime folder shipped as a release
archive. It exists only when ``SAURI_COMPONENTS_DIR`` is set (the desktop app), and then it replaces the
managed engine it names in ``replaces``; elsewhere it is hidden. Its archive comes only from the Releases of
``SAURI_RELEASES_REPO`` on github.com (and GitHub's release-asset redirect host); with no repository
configured the listing says it is not available yet and install is refused. The archive is downloaded into
``<components>/<file>.part`` (resumable), its SHA-256 checked, extracted into a staging folder (regular
files and folders only, nothing outside the component's own folder), the extracted tree hashed against the
catalog ``tree_sha256`` and moved to ``<components>/<component>`` with ``os.replace``.

"In use" check (``in_use_processes``): the process settings layer records the chosen local model of
each process in ``<models>/selection.json`` (``{"transcription": "<id>", "summary": "<id>"}``). A
process without an entry runs its catalog default, because the gateways fall back to it; auxiliary
files (the VAD model) are in use by their process. An unreadable marker blocks removal (fail closed).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import stat
import tarfile
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from hardware import detect_hardware, disk_free_bytes
from sauri_engine_common.local_model_use import (
    LOCATION_LEGACY,
    LOCATION_MODELS_DIR,
    MANIFEST_SUFFIX,
    default_models_dir,
    legacy_path_for,
    manifest_location,
    read_manifest,
)
from sauri_engine_common.model_bundle import manifest_vouches, snapshot
from sauri_engine_common.recommend import (
    Catalog,
    CatalogError,
    CatalogModel,
    HardwareProfile,
    load_catalog,
    recommend,
)

_RELEASES_REPO: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_LOOPBACK_BASE: Final = re.compile(r"http://127\.0\.0\.1:\d{1,5}")
# Where github.com sends a release download today (checked 2026-11-18: a 302 to this host).
RELEASE_ASSET_HOSTS: Final = ("release-assets.githubusercontent.com",)
COMPONENT_MANIFEST_SUFFIX: Final = ".component.json"

logger = logging.getLogger("sauri.host_engine.local_models")

DISK_HEADROOM_PERCENT: Final = 120
HASH_CHUNK_BYTES: Final = 8 << 20
MAX_REDIRECTS: Final = 5
MAX_ATTEMPTS: Final = 4
RETRY_DELAY_S: Final = 1.0
MAX_FINISHED_JOBS: Final = 20
SELECTION_FILE: Final = "selection.json"
LOCATION_MANAGED: Final = "managed"
ADOPT_JOB_MODEL: Final = "-"
# Reasons recorded for a present file that differs from the catalog (never a path or a value).
UNVERIFIED_REASONS: Final = frozenset({"size_mismatch", "hash_mismatch"})
JOB_ID_PATTERN: Final = re.compile(r"[0-9a-f]{32}")
_TOKEN_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{8,256}")
_CONTENT_RANGE: Final = re.compile(r"bytes (\d+)-(\d+)/(\d+)")
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class DownloadPolicy:
    """Where a download may go: scheme, host suffixes and ports; tests swap in a loopback policy."""

    base_url: str = "https://huggingface.co"
    scheme: str = "https"
    host_suffixes: tuple[str, ...] = ("huggingface.co", "hf.co")
    ports: tuple[int, ...] | None = (443,)
    token_hosts: tuple[str, ...] = ("huggingface.co",)

    def allows(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        host = (parts.hostname or "").lower()
        if parts.scheme != self.scheme or parts.username is not None or parts.password is not None or not host:
            return False
        if self.ports is not None and (port or 443) not in self.ports:
            return False
        return any(host == suffix or host.endswith("." + suffix) for suffix in self.host_suffixes)

    def sends_token(self, url: str) -> bool:
        return self.allows(url) and (urlsplit(url).hostname or "").lower() in self.token_hosts

    def url_for(self, model: CatalogModel, path: str | None = None) -> str:
        return f"{self.base_url}/{model.repo}/resolve/{model.revision}/{path or model.file}"


@dataclass(frozen=True)
class ReleasePolicy:
    """Where a component archive may come from: the configured repository's Releases and nothing else.

    ``repo`` empty means no download place exists yet. ``loopback_base`` (tests only, with
    ``SAURI_ALLOW_LOOPBACK_DOWNLOADS=1``) serves the same paths from ``http://127.0.0.1:<port>``.
    No credential is ever sent.
    """

    repo: str = ""
    loopback_base: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.repo)

    def _release_path(self, path: str) -> bool:
        return self.configured and path.startswith(f"/{self.repo}/releases/download/") and ".." not in path

    def allows(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        host = (parts.hostname or "").lower()
        if parts.username is not None or parts.password is not None or not host:
            return False
        if parts.scheme == "https" and (port or 443) == 443:
            if host == "github.com":
                return self._release_path(parts.path)
            return host in RELEASE_ASSET_HOSTS
        if self.loopback_base is not None and parts.scheme == "http" and host == "127.0.0.1":
            return f"http://127.0.0.1:{port}" == self.loopback_base and self._release_path(parts.path)
        return False

    def sends_token(self, _url: str) -> bool:
        return False

    def url_for(self, model: CatalogModel) -> str:
        assert model.release_tag is not None and model.file is not None
        base = self.loopback_base or "https://github.com"
        return f"{base}/{self.repo}/releases/download/{model.release_tag}/{model.file}"


def release_policy_from_env() -> ReleasePolicy:
    """``SAURI_RELEASES_REPO`` (owner/repo, empty by default); loopback only with the explicit test switch."""
    repo = os.getenv("SAURI_RELEASES_REPO", "").strip()
    if repo and _RELEASES_REPO.fullmatch(repo) is None:
        logger.warning("releases_repo_invalid")
        repo = ""
    loopback = None
    if os.getenv("SAURI_ALLOW_LOOPBACK_DOWNLOADS") == "1":
        base = os.getenv("SAURI_RELEASES_BASE_URL", "").rstrip("/")
        loopback = base if _LOOPBACK_BASE.fullmatch(base) else None
    return ReleasePolicy(repo=repo, loopback_base=loopback)


def _env_dir(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value) if value else None


def tree_sha256(base: Path) -> tuple[str, int, int]:
    """Digest of a folder as ``build-runtime.sh`` writes ``tree_sha256``: sorted walk, ``path\0sha256`` lines."""
    lines: list[str] = []
    size = 0
    for dirpath, dirs, names in os.walk(base):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(dirpath, name)
            relative = os.path.relpath(path, base)
            if os.path.islink(path):
                lines.append(f"{relative}\0link:{os.readlink(path)}\n")
                continue
            with open(path, "rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            size += os.path.getsize(path)
            lines.append(f"{relative}\0{digest}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest(), len(lines), size


class LocalModelError(Exception):
    """A request refusal: HTTP status, a stable code and optional extra fields (never secrets)."""

    def __init__(self, status: int, code: str, **extra: Any) -> None:
        super().__init__(code)
        self.status, self.code, self.extra = status, code, extra

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status, content={"error": {"code": self.code, **self.extra}})


class JobError(Exception):
    """An install or verify job ended with a class code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Job:
    id: str
    model_id: str
    type: str  # "install" | "verify" | "adopt"
    bytes_total: int
    state: str = "running"  # running | done | failed | cancelled
    bytes_done: int = 0
    error: str | None = None
    result: str | None = None
    # Adoption only: model ids still waiting to be checked, and the outcome of each one checked so far.
    pending: set[str] = field(default_factory=set, repr=False)
    outcomes: dict[str, str] = field(default_factory=dict, repr=False)
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        view: dict[str, Any] = {
            "id": self.id,
            "model_id": self.model_id,
            "type": self.type,
            "state": self.state,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "error": self.error,
            "result": self.result,
        }
        if self.type == "adopt":
            view["outcomes"] = dict(self.outcomes)
        return view


@dataclass(frozen=True)
class _Found:
    """A catalog file present on disk: where it is, which location and its ``lstat``."""

    path: Path
    location: str
    info: os.stat_result
    snap: dict[str, dict[str, int]] | None = None  # bundles only: size and mtime_ns of each file


class _Sink:
    """The open ``.part`` file with its incremental hash and byte count."""

    def __init__(self, out: Any, sha: Any, done: int, base: int = 0) -> None:
        self.out, self.sha, self.done = out, sha, done
        self.base = base  # bytes of the bundle's earlier files, so job progress covers the whole model

    def restart(self) -> None:
        self.out.seek(0)
        self.out.truncate(0)
        self.sha, self.done = hashlib.sha256(), 0


def default_token_path() -> Path:
    return Path(os.getenv("SAURI_HF_TOKEN_FILE", Path.home() / ".config" / "sauri" / "hf_token"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)


def default_managed_dirs() -> dict[str, Path]:
    """Install location of each managed engine, keyed by catalog ``engine``.

    Senko is a virtual environment; FluidAudio is a folder with ``bin/fluidaudiocli`` and ``provenance.json``.
    """
    root = Path.home() / ".local" / "share" / "sauri" / "native-engines"
    return {
        "senko": Path(os.getenv("SAURI_DIAR_VENV", root / "diar-venv")),
        "fluidaudio": Path(os.getenv("SAURI_PARAKEET_HOME", root / "parakeet")),
    }


def _regular(path: Path) -> os.stat_result | None:
    """``lstat`` of a regular file (never a symlink), or None."""
    try:
        info = path.lstat()
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def _directory(path: Path) -> os.stat_result | None:
    """``lstat`` of a real directory (never a symlink), or None."""
    try:
        info = path.lstat()
    except OSError:
        return None
    return info if stat.S_ISDIR(info.st_mode) else None


class LocalModelService:
    def __init__(
        self,
        models_dir: Path | None = None,
        catalog: Catalog | None = None,
        policy: DownloadPolicy | None = None,
        token_path: Path | None = None,
        legacy_locator: Callable[[CatalogModel], Path | None] | None = None,
        managed_dirs: dict[str, Path] | None = None,
        components_dir: Path | None = None,
        bundled_components_dir: Path | None = None,
        release_policy: ReleasePolicy | None = None,
    ) -> None:
        self.models_dir = models_dir or default_models_dir()
        # Components exist only in the desktop app, which sets SAURI_COMPONENTS_DIR.
        self.components_dir = components_dir or _env_dir("SAURI_COMPONENTS_DIR")
        self.bundled_components_dir = bundled_components_dir or _env_dir("SAURI_BUNDLED_COMPONENTS_DIR")
        self.release_policy = release_policy or release_policy_from_env()
        self._view: Catalog | None = None
        self._view_source: Catalog | None = None
        self._legacy_locator = legacy_locator or legacy_path_for
        self.managed_dirs = default_managed_dirs() if managed_dirs is None else managed_dirs
        self._last_adoption: dict[str, Any] | None = None
        self._catalog = catalog
        self.policy = policy or DownloadPolicy()
        self.token_path = token_path or default_token_path()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._active: Job | None = None

    # --- catalog and paths -------------------------------------------------------------------------

    @property
    def catalog(self) -> Catalog:
        """The catalog as this installation sees it: components replace their managed engine in the desktop
        app, and are hidden everywhere else."""
        if self._catalog is None:
            try:
                path = os.getenv("SAURI_MODEL_CATALOG")
                self._catalog = load_catalog(Path(path)) if path else load_catalog()
            except CatalogError:
                raise LocalModelError(503, "catalog_unavailable") from None
        if self._view is None or self._view_source is not self._catalog:
            self._view_source = self._catalog
            if self.components_dir is not None:
                replaced = {model.replaces for model in self._catalog.models if model.kind == "component"}
                models = tuple(model for model in self._catalog.models if model.id not in replaced)
            else:
                models = tuple(model for model in self._catalog.models if model.kind != "component")
            self._view = Catalog(version=self._catalog.version, models=models)
        return self._view

    def _model(self, model_id: str) -> CatalogModel:
        model = self.catalog.get(model_id)
        if model is None:
            raise LocalModelError(404, "unknown_model")
        return model

    def _paths(self, model: CatalogModel) -> tuple[Path, Path, Path]:
        assert model.file is not None
        if model.kind == "component":
            assert self.components_dir is not None and model.component is not None
            root = self.components_dir
            return (
                root / model.component,
                root / f"{model.file}.part",
                root / f"{model.component}{COMPONENT_MANIFEST_SUFFIX}",
            )
        final = self.models_dir / model.file
        return final, final.with_name(final.name + ".part"), final.with_name(final.name + MANIFEST_SUFFIX)

    def _downloadable(self, model_id: str) -> CatalogModel:
        model = self._model(model_id)
        if not model.downloadable:
            raise LocalModelError(409, "managed_engine", managed_by=model.managed_by)
        return model

    # --- state ------------------------------------------------------------------------------------

    def _read_manifest(self, manifest: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _legacy_path(self, model: CatalogModel) -> Path | None:
        return self._legacy_locator(model)

    def _locate_file(self, model: CatalogModel) -> _Found | None:
        """The catalog file where it is: the models directory first, then the legacy location."""
        final = self._paths(model)[0]
        if model.bundle:
            directory = _directory(final)
            if directory is None:
                return None
            return _Found(final, LOCATION_MODELS_DIR, directory, snapshot(final, model.files))
        info = _regular(final)
        if info is not None:
            return _Found(final, LOCATION_MODELS_DIR, info)
        legacy = self._legacy_path(model)
        legacy_info = _regular(legacy) if legacy is not None else None
        if legacy is not None and legacy_info is not None:
            return _Found(legacy, LOCATION_LEGACY, legacy_info)
        return None

    def managed_detected(self, model: CatalogModel) -> bool:
        """A managed engine is installed when its virtual environment holds an interpreter and the package.

        Presence only: nothing is hashed or imported (the installer's ``--check`` does the integrity check).
        """
        home = self.managed_dirs.get(model.engine)
        if home is None:
            return False
        if model.engine == "fluidaudio":
            return self._fluidaudio_detected(home, model)
        if not (home / "bin" / "python").is_file():
            return False
        return any(home.glob(f"lib/python*/site-packages/{model.engine}*"))

    @staticmethod
    def _fluidaudio_detected(home: Path, model: CatalogModel) -> bool:
        """The CLI is present and its provenance names the pinned source commit (presence only, no hashing)."""
        binary = home / "bin" / "fluidaudiocli"
        if not binary.is_file() or not os.access(binary, os.X_OK):
            return False
        record = read_manifest(home / "provenance.json")
        if record is None:
            return False
        return record.get("source_commit") == model.revision and bool(record.get("binary_sha256"))

    def needs_ready(self, model: CatalogModel) -> bool:
        """The managed engine this model cannot run without is installed (true for models that need none)."""
        if model.needs is None:
            return True
        dependency = self.catalog.get(model.needs)
        return dependency is not None and self.managed_detected(dependency)

    def _state(self, model: CatalogModel) -> dict[str, Any]:
        """Cheap state from stat and manifest only; the hash is recomputed by ``verify`` and ``adopt``.

        ``state`` keeps its original vocabulary. ``reason`` is set when a present file was already judged
        different from the catalog (``adopt``); ``location`` says where the file is.
        """
        if not model.downloadable:
            location = LOCATION_MANAGED if self.managed_detected(model) else None
            return {"state": "managed", "installed_size": None, "installed_at": None, "location": location,
                    "reason": None}  # fmt: skip
        absent = {"installed_size": None, "installed_at": None, "location": None, "reason": None}
        if self._active and self._active.type == "install" and self._active.model_id == model.id:
            return {"state": "installing", **absent}
        if model.kind == "component":
            return self._component_state(model, absent)
        found = self._locate_file(model)
        if found is None:
            return {"state": "not_installed", **absent}
        record = read_manifest(self._paths(model)[2])
        if record is not None and manifest_location(record) != found.location:
            record = None  # written for another location: says nothing about this file
        if model.bundle:
            return self._bundle_state(model, found, record)
        info = found.info
        state, reason, installed_at = "unverified", None, None
        if record is not None:
            installed_at = record.get("installed_at")
            same_file = (
                record.get("sha256") == model.sha256
                and record.get("size") == info.st_size == model.size
                and record.get("mtime_ns") == info.st_mtime_ns
            )
            if record.get("status") == "corrupt" and record.get("sha256") == model.sha256:
                state = "corrupt"
            elif same_file and record.get("status") == "installed":
                state = "installed"
            elif self._judged_different(record, info):
                reason = record.get("reason")
        return {
            "state": state,
            "installed_size": info.st_size,
            "installed_at": installed_at,
            "location": found.location,
            "reason": reason,
        }

    def _locate_component(self, model: CatalogModel) -> _Found | None:
        """The component folder: the installed one, else one the runtime carries (development)."""
        final = self._paths(model)[0]
        info = _directory(final)
        if info is not None:
            return _Found(final, LOCATION_MODELS_DIR, info)
        if self.bundled_components_dir is not None and model.component is not None:
            bundled = self.bundled_components_dir / model.component
            info = _directory(bundled)
            if info is not None:
                return _Found(bundled, LOCATION_LEGACY, info)
        return None

    def _component_state(self, model: CatalogModel, absent: dict[str, Any]) -> dict[str, Any]:
        """From the folder and its manifest only; a folder of another version is ``unverified``/``outdated``."""
        found = self._locate_component(model)
        if found is None:
            return {"state": "not_installed", **absent}
        if found.location == LOCATION_LEGACY:
            return {"state": "installed", "installed_size": model.unpacked_size, "installed_at": None,
                    "location": LOCATION_LEGACY, "reason": None}  # fmt: skip
        record = read_manifest(self._paths(model)[2]) or {}
        same = record.get("sha256") == model.sha256 and record.get("tree_sha256") == model.tree_sha256
        state, reason = "unverified", None
        if same and record.get("status") == "installed":
            state = "installed"
        elif same and record.get("status") == "corrupt":
            state = "corrupt"
        elif record.get("version") and record.get("version") != model.version:
            reason = "outdated"
        return {
            "state": state,
            "installed_size": record.get("unpacked_size") if same else None,
            "installed_at": record.get("installed_at"),
            "location": LOCATION_MODELS_DIR,
            "reason": reason,
        }

    @staticmethod
    def _bundle_state(model: CatalogModel, found: _Found, record: dict[str, Any] | None) -> dict[str, Any]:
        """State of a bundle from stat and manifest only; a missing or resized file is ``unverified``."""
        state, reason, installed_at = "unverified", None, None
        if record is not None:
            installed_at = record.get("installed_at")
            if record.get("status") == "corrupt" and record.get("sha256") == model.sha256:
                state = "corrupt"
            elif found.snap is not None and manifest_vouches(record, found.snap, model.sha256 or ""):
                state = "installed"
            elif record.get("status") == "present_unverified" and record.get("reason") in UNVERIFIED_REASONS:
                reason = record.get("reason") if found.snap is None or record.get("files") == found.snap else None
        return {
            "state": state,
            "installed_size": sum(item["size"] for item in found.snap.values()) if found.snap else None,
            "installed_at": installed_at,
            "location": found.location,
            "reason": reason,
        }

    @staticmethod
    def _judged_different(record: dict[str, Any], info: os.stat_result) -> bool:
        """The manifest says this very file (same size and ``mtime_ns``) was judged different from the catalog."""
        return (
            record.get("status") == "present_unverified"
            and record.get("reason") in UNVERIFIED_REASONS
            and record.get("size") == info.st_size
            and record.get("mtime_ns") == info.st_mtime_ns
        )

    def _read_selection(self) -> dict[str, Any]:
        try:
            raw = (self.models_dir / SELECTION_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError):
            raise LocalModelError(503, "selection_unreadable") from None
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise LocalModelError(503, "selection_unreadable") from None
        if not isinstance(parsed, dict):
            raise LocalModelError(503, "selection_unreadable")
        return parsed

    def in_use_processes(self, model: CatalogModel) -> list[str]:
        """Processes that currently run ``model``; see the module docstring for the marker contract."""
        if model.kind == "auxiliary":
            return [model.process]
        chosen = self._read_selection().get(model.process)
        if chosen is None:
            return [model.process] if model.default or model.preferred else []
        return [model.process] if chosen == model.id else []

    # --- views ------------------------------------------------------------------------------------

    def hardware(self) -> HardwareProfile:
        return detect_hardware(self.models_dir)

    def hardware_view(self) -> dict[str, Any]:
        profile = self.hardware()
        return {
            "arch": profile.arch,
            "system": profile.system,
            "memory_gib": profile.memory_gib,
            "cores": profile.cores,
            "metal": profile.metal,
            "macos_major": profile.macos_major,
            "disk_free_bytes": profile.disk_free_bytes,
        }

    @staticmethod
    def _availability(state: dict[str, Any]) -> str:
        """``installed`` (verified, or a managed engine that is present), ``present_unverified`` or ``available``."""
        if state["state"] == "managed":
            return "installed" if state["location"] else "available"
        if state["state"] == "installed":
            return "installed"
        if state["state"] in ("unverified", "corrupt"):
            return "present_unverified"
        return "available"

    def _active_models(self, availability: dict[str, str]) -> dict[str, str | None]:
        """The model serving each process: the chosen one, else the preferred or default one, only when ready.

        Mirrors the gateways: no choice means ``local:default``, which is the ``preferred`` model when it is
        installed and the engine it needs is present, and the catalog default otherwise; a choice means
        ``local:<id>``, which fails unless that model is ready, so no other model is shown as active.
        An unreadable marker is treated as no choice, as ``local:default`` never reads it.
        """
        try:
            selection = self._read_selection()
        except LocalModelError:
            selection = {}
        active: dict[str, str | None] = {}
        for process in dict.fromkeys(model.process for model in self.catalog.models):
            candidates = [m for m in self.catalog.models if m.process == process and m.kind != "auxiliary"]
            chosen = selection.get(process)
            def ready(model: CatalogModel) -> bool:
                return availability[model.id] == "installed" and self.needs_ready(model)

            if chosen is None:
                preferred = next((m for m in candidates if m.preferred and ready(m)), None)
                picked = preferred or next((m for m in candidates if m.default), None)
            else:
                picked = next((m for m in candidates if m.id == chosen), None)
            active[process] = picked.id if picked is not None and ready(picked) else None
        return active

    def _install_hint(self, model: CatalogModel, free_bytes: int) -> dict[str, Any]:
        """What installing a model still needs: a download with its disk headroom, or the managed command."""
        if not model.downloadable:
            return {"method": "managed_command", "managed_by": model.managed_by, "download_bytes": None,
                    "disk_required_bytes": None, "fits_on_disk": None}  # fmt: skip
        required = self._disk_required(model)
        hint: dict[str, Any] = {"method": "download", "managed_by": None, "download_bytes": model.size,
                "disk_required_bytes": required, "fits_on_disk": free_bytes >= required}  # fmt: skip
        if model.kind == "component":
            # No download place yet (design D13): the listing says so instead of offering a failing install.
            hint["source_available"] = self.release_policy.configured
        return hint

    @staticmethod
    def _disk_required(model: CatalogModel) -> int:
        """The download plus 20 %; a component also needs room for its unpacked folder (with the same margin)."""
        assert model.size is not None
        total = model.size + (model.unpacked_size or 0)
        return -(-total * DISK_HEADROOM_PERCENT // 100)

    def list_models(self) -> dict[str, Any]:
        profile = self.hardware()
        recommendations = recommend(profile, self.catalog)
        recommended = {rec.model_id for rec in recommendations.values() if rec.model_id}
        states = {model.id: self._state(model) for model in self.catalog.models}
        availability = {model_id: self._availability(state) for model_id, state in states.items()}
        active = self._active_models(availability)
        verifying = self._active.pending if self._active is not None and self._active.type == "adopt" else set()
        models = []
        for model in self.catalog.models:
            in_use_by = self._safe_in_use(model)
            state = states[model.id]
            view = {
                "id": model.id,
                "process": model.process,
                "kind": model.kind,
                "engine": model.engine,
                "size": model.size,
                "min_ram_gib": model.min_ram_gib,
                "requires": list(model.requires),
                "min_macos": model.min_macos,
                "status": model.status,
                "default": model.default,
                "preferred": model.preferred,
                "needs": model.needs,
                "needs_ready": self.needs_ready(model),
                "license": model.license,
                "attribution": model.attribution,
                "managed_by": model.managed_by,
                "version": model.version,
                "recommended": model.id in recommended,
                "in_use_by": in_use_by,
                **state,
                "availability": availability[model.id],
                "active": active.get(model.process) == model.id,
                "in_use": bool(in_use_by),
                "verifying": model.id in verifying,
                "verified_by": "presence" if not model.downloadable else "hash",
                "install": None
                if availability[model.id] == "installed"
                else self._install_hint(model, profile.disk_free_bytes),
            }
            models.append(view)
        return {
            "catalog_version": self.catalog.version,
            "models": models,
            "recommendations": {process: rec.as_dict() for process, rec in recommendations.items()},
            "active_job": self._active.id if self._active else None,
            "active": active,
            "adoption": self._last_adoption,
        }

    def _safe_in_use(self, model: CatalogModel) -> list[str]:
        try:
            return self.in_use_processes(model)
        except LocalModelError:
            return []

    # --- jobs -------------------------------------------------------------------------------------

    def get_job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id) if JOB_ID_PATTERN.fullmatch(job_id) else None
        if job is None:
            raise LocalModelError(404, "unknown_job")
        return job

    def _start(self, job: Job, work: Coroutine[Any, Any, None]) -> Job:
        self._active = job
        self._jobs[job.id] = job
        while len(self._jobs) > MAX_FINISHED_JOBS:
            oldest = next(iter(self._jobs))
            if self._jobs[oldest] is self._active:
                break
            del self._jobs[oldest]
        job.task = asyncio.create_task(work)
        return job

    def _require_idle(self) -> None:
        if self._active is not None:
            raise LocalModelError(409, "job_active", job_id=self._active.id)

    def install(self, model_id: str) -> Job:
        model = self._downloadable(model_id)
        assert model.size is not None
        self._require_idle()
        if model.kind == "component" and not self.release_policy.configured:
            raise LocalModelError(409, "component_not_published")
        current = self._state(model)
        incomplete = model.bundle and current["state"] == "unverified" and current["installed_size"] is None
        if model.kind == "component" and current["location"] == LOCATION_LEGACY:
            raise LocalModelError(409, "already_installed")
        if not incomplete and (
            current["state"] == "installed"
            or (current["state"] == "unverified" and current["reason"] is None and model.kind != "component")
        ):
            raise LocalModelError(409, "already_installed")
        final, part, _manifest = self._paths(model)
        target_dir = final.parent if model.kind == "component" else self.models_dir
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            part_info = None if model.bundle else _regular(part)
            needed = self._disk_required(model) - (part_info.st_size if part_info else 0)
            free = disk_free_bytes(target_dir)
        except OSError:
            raise LocalModelError(503, "models_dir_unavailable") from None
        if free < max(needed, 0):
            raise LocalModelError(507, "insufficient_disk", needed_bytes=needed, free_bytes=free)
        job = Job(id=uuid.uuid4().hex, model_id=model.id, type="install", bytes_total=model.size)
        logger.info("local_model_install_started model=%s", model.id)
        if model.kind == "component":
            body = self._install_component(job, model)
        else:
            body = self._install_bundle(job, model) if model.bundle else self._install(job, model)
        return self._start(job, self._run(job, body, part))

    def verify(self, model_id: str) -> Job:
        model = self._downloadable(model_id)
        assert model.size is not None
        self._require_idle()
        if model.kind == "component":
            found = self._locate_component(model)
            if found is None or found.location != LOCATION_MODELS_DIR:
                raise LocalModelError(404, "not_installed")
            job = Job(id=uuid.uuid4().hex, model_id=model.id, type="verify", bytes_total=model.unpacked_size or 0)
            return self._start(job, self._run(job, self._verify_component(job, model), None))
        found = self._locate_file(model)
        if found is None:
            raise LocalModelError(404, "not_installed")
        total = model.size if model.bundle else found.info.st_size
        job = Job(id=uuid.uuid4().hex, model_id=model.id, type="verify", bytes_total=total)
        body = self._verify_bundle(job, model) if model.bundle else self._verify(job, model)
        return self._start(job, self._run(job, body, None))

    async def cancel(self, job_id: str) -> Job:
        job = self.get_job(job_id)
        if job.state != "running" or job.task is None:
            raise LocalModelError(409, "job_not_running")
        job.task.cancel()
        await asyncio.wait({job.task})
        if job.state == "running":
            # Cancelled before the job body started: nothing ran its cleanup.
            job.state, self._active = "cancelled", None
            if job.type == "install":
                self._discard_part(self._paths(self._model(job.model_id))[1])
        return job

    def remove(self, model_id: str) -> None:
        model = self._downloadable(model_id)
        if self._active is not None and self._active.model_id == model.id:
            raise LocalModelError(409, "job_active", job_id=self._active.id)
        final, part, manifest = self._paths(model)
        found = self._locate_component(model) if model.kind == "component" else self._locate_file(model)
        if found is None:
            raise LocalModelError(404, "not_installed")
        if found.location == LOCATION_LEGACY:
            # The file is not ours to delete: it was installed by hand outside the models directory.
            raise LocalModelError(409, "legacy_location")
        processes = self.in_use_processes(model)
        if processes:
            raise LocalModelError(409, "model_in_use", processes=processes)
        if model.kind == "component":
            _unlink(manifest)
            _unlink(part)
            shutil.rmtree(final, ignore_errors=True)
        elif model.bundle:
            for directory in (final, part):
                shutil.rmtree(directory, ignore_errors=True)
            _unlink(manifest)
        else:
            for path in (manifest, final, part):
                _unlink(path)
        logger.info("local_model_removed model=%s", model.id)

    # --- job bodies -------------------------------------------------------------------------------

    async def _run(self, job: Job, body: Coroutine[Any, Any, None], part: Path | None) -> None:
        try:
            await body
            job.state = "done"
        except asyncio.CancelledError:
            job.state = "cancelled"
            self._discard_part(part)
            raise
        except JobError as failure:
            job.state, job.error = "failed", failure.code
            self._discard_part(part)
        except (OSError, httpx.HTTPError) as exc:
            # Only the class name is logged: exception text can carry a URL or a path.
            logger.warning("local_model_job_error type=%s", type(exc).__name__)
            job.state, job.error = "failed", "io_error" if isinstance(exc, OSError) else "download_failed"
            self._discard_part(part)
        finally:
            self._active = None
            logger.info("local_model_job_finished model=%s type=%s state=%s", job.model_id, job.type, job.state)

    @staticmethod
    def _discard_part(part: Path | None) -> None:
        """A failed or cancelled install leaves no ``.part`` file or staging directory behind."""
        if part is None:
            return
        if _directory(part) is not None:
            shutil.rmtree(part, ignore_errors=True)
        else:
            _unlink(part)

    def _token(self) -> str | None:
        try:
            value = self.token_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        return value if _TOKEN_PATTERN.fullmatch(value) else None

    async def _hash_into(self, path: Path, sha: Any, job: Job) -> None:
        with path.open("rb") as handle:
            while chunk := await asyncio.to_thread(handle.read, HASH_CHUNK_BYTES):
                sha.update(chunk)
                job.bytes_done += len(chunk)

    @staticmethod
    def _client() -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False, trust_env=False)

    async def _download_file(
        self,
        client: httpx.AsyncClient,
        job: Job,
        model: CatalogModel,
        relative: str | None,
        size: int,
        sha256: str,
        part: Path,
        base: int = 0,
        source: tuple[str, DownloadPolicy | ReleasePolicy] | None = None,
    ) -> None:
        """Download one catalog file into ``part`` (resumable) and check its SHA-256; ``part`` stays for the caller.

        ``relative`` is the path inside the repository (None for a single-file model). ``base`` is the number of
        bytes of the bundle's earlier files, so the job's progress covers the whole model.
        """
        sha = hashlib.sha256()
        info = _regular(part)
        if os.path.lexists(part) and info is None:
            raise JobError("unsafe_path")
        if info is not None and info.st_size > size:
            _unlink(part)
            info = None
        job.bytes_done = base
        if info is not None:
            await self._hash_into(part, sha, job)  # resume: re-hash what is already on disk
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "ab") as out:
            sink = _Sink(out, sha, job.bytes_done - base, base)
            url, policy = source or (self.policy.url_for(model, relative), self.policy)
            token = self._token() if isinstance(policy, DownloadPolicy) else None
            attempts = 0
            while sink.done < size:
                before = sink.done
                try:
                    await self._fetch(client, url, size, sink, job, token, policy)
                except httpx.TransportError as exc:
                    logger.warning("local_model_connection_lost type=%s", type(exc).__name__)
                if sink.done < size:
                    # A cut that made progress does not count against the retry budget.
                    attempts = 0 if sink.done > before else attempts + 1
                    if attempts >= MAX_ATTEMPTS:
                        raise JobError("connection_lost")
                    await asyncio.sleep(RETRY_DELAY_S)
            out.flush()
            os.fsync(out.fileno())
        if not hmac.compare_digest(sink.sha.hexdigest(), sha256):
            raise JobError("hash_mismatch")

    async def _install(self, job: Job, model: CatalogModel) -> None:
        assert model.size is not None and model.sha256 is not None
        final, part, manifest = self._paths(model)
        async with self._client() as client:
            await self._download_file(client, job, model, None, model.size, model.sha256, part)
        os.replace(part, final)
        self._write_manifest(model, final.stat(), manifest, "installed")
        job.result = "installed"

    async def _install_bundle(self, job: Job, model: CatalogModel) -> None:
        """Download every file of a bundle into ``<dir>.part/`` and move it into place when all of them match."""
        final, part, manifest = self._paths(model)
        if os.path.lexists(part) and _directory(part) is None:
            raise JobError("unsafe_path")
        base = 0
        async with self._client() as client:
            for item in model.files:
                target = part / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                done = _regular(target)
                if done is not None and done.st_size == item.size:
                    job.bytes_done = base
                    sink = hashlib.sha256()
                    await self._hash_into(target, sink, job)
                    if hmac.compare_digest(sink.hexdigest(), item.sha256):
                        base += item.size  # a file of an earlier attempt that is complete and verified
                        continue
                    _unlink(target)
                await self._download_file(
                    client, job, model, item.path, item.size, item.sha256,
                    target.with_name(target.name + ".part"), base,
                )
                os.replace(target.with_name(target.name + ".part"), target)
                base += item.size
        self._replace_directory(part, final)
        found = snapshot(final, model.files)
        if found is None:
            raise JobError("size_mismatch")
        self._write_manifest(model, final.stat(), manifest, "installed", files=found)
        job.result = "installed"

    async def _install_component(self, job: Job, model: CatalogModel) -> None:
        """Download the archive, check it, unpack it into staging, check the tree, then move it into place."""
        assert model.size is not None and model.sha256 is not None and model.component is not None
        final, part, manifest = self._paths(model)
        staging = final.with_name(f".{model.component}.extract")
        source = (self.release_policy.url_for(model), self.release_policy)
        async with self._client() as client:
            await self._download_file(client, job, model, None, model.size, model.sha256, part, source=source)
        stop = threading.Event()
        shutil.rmtree(staging, ignore_errors=True)
        work = asyncio.ensure_future(asyncio.to_thread(self._unpack_component, model, part, staging, stop))
        try:
            await asyncio.shield(work)
            self._replace_directory(staging / model.component, final)
        except asyncio.CancelledError:
            stop.set()  # the unpacking thread stops at the next entry; its files go with the staging folder
            await asyncio.wait({work})
            if not work.cancelled():
                work.exception()  # retrieved, so it is not reported as unhandled
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        _unlink(part)
        self._write_component_manifest(model, manifest, "installed")
        job.result = "installed"

    @staticmethod
    def _unpack_component(model: CatalogModel, archive: Path, staging: Path, stop: threading.Event) -> None:
        """Blocking: regular files and folders under ``<component>/`` only, never more than the catalog size."""
        assert model.component is not None and model.unpacked_size is not None
        prefix = model.component + "/"
        staging.mkdir(mode=0o700, parents=True)
        total = 0
        try:
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    if stop.is_set():
                        raise JobError("cancelled")
                    name = member.name.rstrip("/")
                    inside = (name == model.component or name.startswith(prefix)) and ".." not in name.split("/")
                    if not inside or not (member.isfile() or member.isdir()):
                        raise JobError("archive_invalid")
                    total += member.size
                    if total > model.unpacked_size:
                        raise JobError("archive_too_large")
                    tar.extract(member, staging, filter="data")
        except (tarfile.TarError, EOFError):
            raise JobError("archive_invalid") from None
        root = staging / model.component
        if _directory(root) is None:
            raise JobError("archive_invalid")
        digest, _count, size = tree_sha256(root)
        if not hmac.compare_digest(digest, model.tree_sha256 or "") or size != model.unpacked_size:
            raise JobError("tree_mismatch")

    async def _verify_component(self, job: Job, model: CatalogModel) -> None:
        final, _part, manifest = self._paths(model)
        if _directory(final) is None:
            raise JobError("not_installed")
        digest, _count, size = await asyncio.to_thread(tree_sha256, final)
        job.bytes_done = size
        matches = hmac.compare_digest(digest, model.tree_sha256 or "") and size == model.unpacked_size
        self._write_component_manifest(model, manifest, "installed" if matches else "corrupt")
        job.result = "verified" if matches else "corrupt"

    @staticmethod
    def _write_component_manifest(model: CatalogModel, manifest: Path, status: str) -> None:
        record = {
            "id": model.id,
            "component": model.component,
            "version": model.version,
            "file": model.file,
            "sha256": model.sha256,
            "tree_sha256": model.tree_sha256,
            "unpacked_size": model.unpacked_size,
            "installed_at": _now(),
            "status": status,
        }
        temporary = manifest.with_name(manifest.name + ".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, manifest)

    @staticmethod
    def _replace_directory(staging: Path, final: Path) -> None:
        """Move a complete staging directory to its final name; an older (incomplete or corrupt) one goes first."""
        if os.path.lexists(final):
            old = final.with_name(final.name + ".old")
            shutil.rmtree(old, ignore_errors=True)
            os.replace(final, old)
            os.replace(staging, final)
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.replace(staging, final)

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        size: int,
        sink: _Sink,
        job: Job,
        token: str | None,
        policy: DownloadPolicy | ReleasePolicy | None = None,
    ) -> None:
        policy = policy or self.policy
        headers = {"Accept-Encoding": "identity"}
        if sink.done:
            headers["Range"] = f"bytes={sink.done}-"
        if not policy.allows(url):
            raise JobError("url_not_allowed")
        for _hop in range(MAX_REDIRECTS + 1):
            hop_headers = dict(headers)
            if token and policy.sends_token(url):
                hop_headers["Authorization"] = f"Bearer {token}"
            async with client.stream("GET", url, headers=hop_headers) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    url = urljoin(url, location) if location else ""
                    if not url or not policy.allows(url):
                        raise JobError("redirect_not_allowed")
                    continue
                await self._consume(response, size, sink, job)
                return
        raise JobError("too_many_redirects")

    async def _consume(self, response: httpx.Response, size: int, sink: _Sink, job: Job) -> None:
        status = response.status_code
        if status == 206:
            match = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", ""))
            if match is None or int(match[1]) != sink.done or int(match[3]) != size:
                raise JobError("bad_range")
        elif status == 200:
            length = response.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) != size):
                raise JobError("size_mismatch")
            if sink.done:
                sink.restart()  # the server ignored Range: start over
                job.bytes_done = sink.base
        elif status in (401, 403):
            raise JobError("download_unauthorized")
        elif status == 404:
            raise JobError("download_not_found")
        else:
            raise JobError("download_http_error")
        async for chunk in response.aiter_raw():
            if sink.done + len(chunk) > size:
                raise JobError("size_exceeded")
            sink.out.write(chunk)
            sink.sha.update(chunk)
            sink.done += len(chunk)
            job.bytes_done = sink.base + sink.done

    async def _verify(self, job: Job, model: CatalogModel) -> None:
        assert model.sha256 is not None
        manifest = self._paths(model)[2]
        found = self._locate_file(model)
        if found is None:
            raise JobError("not_installed")
        sha = hashlib.sha256()
        await self._hash_into(found.path, sha, job)
        info = _regular(found.path)
        if info is None:
            raise JobError("not_installed")
        matches = hmac.compare_digest(sha.hexdigest(), model.sha256) and info.st_size == model.size
        self._write_manifest(model, info, manifest, "installed" if matches else "corrupt", found.location)
        job.result = "verified" if matches else "corrupt"

    async def _verify_bundle(self, job: Job, model: CatalogModel) -> None:
        manifest = self._paths(model)[2]
        found = self._locate_file(model)
        if found is None:
            raise JobError("not_installed")
        matches = found.snap is not None
        for item in model.files if matches else ():
            sha = hashlib.sha256()
            try:
                await self._hash_into(found.path / item.path, sha, job)
            except OSError:
                matches = False
                break
            if not hmac.compare_digest(sha.hexdigest(), item.sha256):
                matches = False
                break
        after = snapshot(found.path, model.files)
        if matches and after != found.snap:
            raise JobError("changed")
        files = after if matches and after is not None else {}
        status = "installed" if matches else "corrupt"
        self._write_manifest(model, found.info, manifest, status, found.location, files=files)
        job.result = "verified" if matches else "corrupt"

    def _write_manifest(
        self,
        model: CatalogModel,
        info: os.stat_result,
        manifest: Path,
        status: str,
        location: str = LOCATION_MODELS_DIR,
        reason: str | None = None,
        files: dict[str, dict[str, int]] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "id": model.id,
            "file": model.file,
            "revision": model.revision,
            "sha256": model.sha256,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "installed_at": _now(),
            "status": status,
            "location": location,
        }
        if reason is not None:
            record["reason"] = reason
        if files is not None:
            record["files"] = files
        manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest.with_name(manifest.name + ".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, manifest)

    # --- adoption ---------------------------------------------------------------------------------

    def adopt(self) -> Job:
        """Recognize catalog files that are already on disk; see the module docstring.

        Idempotent: a run already in progress is returned as is, and a model already verified (or already
        judged different at its current size and ``mtime_ns``) is not hashed again.
        """
        if self._active is not None and self._active.type == "adopt":
            return self._active
        self._require_idle()
        candidates = self._adoption_candidates()
        job = Job(
            id=uuid.uuid4().hex,
            model_id=ADOPT_JOB_MODEL,
            type="adopt",
            bytes_total=sum(self._adoption_bytes(model, found) for model, found in candidates),
            pending={model.id for model, _found in candidates},
        )
        logger.info("local_model_adoption_started candidates=%d", len(candidates))
        return self._start(job, self._run(job, self._adopt(job, candidates), None))

    @staticmethod
    def _adoption_bytes(model: CatalogModel, found: _Found) -> int:
        if model.bundle:
            return model.size or 0 if found.snap is not None else 0
        return found.info.st_size if found.info.st_size == model.size else 0

    def _adoption_candidates(self) -> list[tuple[CatalogModel, _Found]]:
        candidates = []
        for model in self.catalog.models:
            if not model.downloadable or model.kind == "component":
                continue
            found = self._locate_file(model)
            if found is None or self._state(model)["state"] == "installed":
                continue
            record = read_manifest(self._paths(model)[2])
            same_place = record is not None and manifest_location(record) == found.location
            if record is not None and same_place and self._already_judged(record, found):
                continue
            candidates.append((model, found))
        return candidates

    def _already_judged(self, record: dict[str, Any], found: _Found) -> bool:
        """This very file (same size and ``mtime_ns``) was already hashed and found different."""
        if found.snap is not None and "files" in record:  # a bundle: every file has the same size and mtime_ns
            return record.get("files") == found.snap and (
                record.get("status") == "corrupt" or record.get("status") == "present_unverified"
            )
        same = record.get("size") == found.info.st_size and record.get("mtime_ns") == found.info.st_mtime_ns
        return same and (record.get("status") == "corrupt" or self._judged_different(record, found.info))

    async def _adopt(self, job: Job, candidates: list[tuple[CatalogModel, _Found]]) -> None:
        try:
            for model, found in candidates:
                job.model_id = model.id
                job.outcomes[model.id] = await self._adopt_one(job, model, found)
                job.pending.discard(model.id)
        finally:
            job.model_id, job.pending = ADOPT_JOB_MODEL, set()
            self._last_adoption = {"job_id": job.id, "outcomes": dict(job.outcomes)}
        adopted = sum(1 for outcome in job.outcomes.values() if outcome == "adopted")
        job.result = "adopted" if adopted else "nothing_adopted"
        logger.info("local_model_adoption_finished outcomes=%s", sorted(job.outcomes.values()))

    async def _adopt_one(self, job: Job, model: CatalogModel, found: _Found) -> str:
        """Outcome of one file: ``adopted``, ``present_unverified``, ``changed``, ``unreadable``, ``write_failed``."""
        assert model.size is not None and model.sha256 is not None
        if model.bundle:
            return await self._adopt_bundle(job, model, found)
        before = found.info
        if before.st_size != model.size:
            return self._record_judgement(model, found, "present_unverified", "size_mismatch")
        sha = hashlib.sha256()
        try:
            await self._hash_into(found.path, sha, job)
        except OSError as exc:
            logger.warning("local_model_adoption_error type=%s", type(exc).__name__)
            return "unreadable"
        after = _regular(found.path)
        if after is None or (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            return "changed"  # modified while it was being read: judge nothing, try again next run
        if hmac.compare_digest(sha.hexdigest(), model.sha256):
            return self._record_judgement(model, found, "installed", None)
        return self._record_judgement(model, found, "present_unverified", "hash_mismatch")

    async def _adopt_bundle(self, job: Job, model: CatalogModel, found: _Found) -> str:
        if found.snap is None:
            return self._record_judgement(model, found, "present_unverified", "size_mismatch")
        for item in model.files:
            sha = hashlib.sha256()
            try:
                await self._hash_into(found.path / item.path, sha, job)
            except OSError as exc:
                logger.warning("local_model_adoption_error type=%s", type(exc).__name__)
                return "unreadable"
            if not hmac.compare_digest(sha.hexdigest(), item.sha256):
                return self._record_judgement(model, found, "present_unverified", "hash_mismatch")
        if snapshot(found.path, model.files) != found.snap:
            return "changed"  # modified while it was being read: judge nothing, try again next run
        return self._record_judgement(model, found, "installed", None)

    def _record_judgement(self, model: CatalogModel, found: _Found, status: str, reason: str | None) -> str:
        """Write the manifest for a judged file (never the file itself) and name the outcome."""
        try:
            files = found.snap if model.bundle else None
            self._write_manifest(model, found.info, self._paths(model)[2], status, found.location, reason, files)
        except OSError as exc:
            logger.warning("local_model_adoption_error type=%s", type(exc).__name__)
            return "write_failed"
        return "adopted" if status == "installed" else "present_unverified"


def seed_bundle(service: LocalModelService, model_id: str, source: Path) -> str:
    """Copy a bundle that is already on this Mac into the models directory, verifying every byte; blocking.

    For the operator (``seed_model.py``), never for a request: ``source`` is a path the operator typed. Every
    source file must match the catalog size and SHA-256 (hashed while it is copied, and the copy is what is
    stored), the directory appears under its final name only when all of them match, and the source is left
    untouched. Returns ``installed`` or raises ``LocalModelError`` with a stable code.
    """
    model = service._model(model_id)
    if not model.bundle or model.file is None or model.sha256 is None:
        raise LocalModelError(409, "not_a_bundle")
    if service._active is not None:
        raise LocalModelError(409, "job_active", job_id=service._active.id)
    final, part, manifest = service._paths(model)
    if snapshot(final, model.files) is not None:
        record = read_manifest(manifest)
        found = snapshot(final, model.files)
        if found is not None and manifest_vouches(record, found, model.sha256):
            return "installed"
    shutil.rmtree(part, ignore_errors=True)
    try:
        for item in model.files:
            origin = source / item.path
            info = _regular(origin)
            if info is None or info.st_size != item.size:
                raise LocalModelError(404, "source_file_missing_or_resized")
            target = part / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            sha = hashlib.sha256()
            with origin.open("rb") as reader, target.open("xb") as writer:
                while chunk := reader.read(HASH_CHUNK_BYTES):
                    sha.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if not hmac.compare_digest(sha.hexdigest(), item.sha256):
                raise LocalModelError(422, "source_hash_mismatch")
        service._replace_directory(part, final)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    found = snapshot(final, model.files)
    if found is None:
        raise LocalModelError(500, "seed_incomplete")
    service._write_manifest(model, final.stat(), manifest, "installed", files=found)
    return "installed"


# --- routes -----------------------------------------------------------------------------------------

router = APIRouter(prefix="/v1")
_service: LocalModelService | None = None


def get_service() -> LocalModelService:
    global _service
    if _service is None:
        _service = LocalModelService()
    return _service


def _no_query(request: Request) -> None:
    if request.url.query:
        raise LocalModelError(422, "invalid_request")


@router.get("/hardware")
async def hardware_route() -> dict[str, Any]:
    return await asyncio.to_thread(get_service().hardware_view)


@router.get("/local/models", response_model=None)
async def list_models_route() -> dict[str, Any] | Response:
    try:
        return await asyncio.to_thread(get_service().list_models)
    except LocalModelError as exc:
        return exc.response()


@router.post("/local/adopt", status_code=202, response_model=None)
async def adopt_route(request: Request) -> dict[str, Any] | Response:
    try:
        _no_query(request)
        return get_service().adopt().as_dict()
    except LocalModelError as exc:
        return exc.response()


@router.post("/local/models/{model_id}/install", status_code=202, response_model=None)
async def install_route(model_id: str, request: Request) -> dict[str, Any] | Response:
    try:
        _no_query(request)
        return get_service().install(model_id).as_dict()
    except LocalModelError as exc:
        return exc.response()


@router.post("/local/models/{model_id}/verify", status_code=202, response_model=None)
async def verify_route(model_id: str, request: Request) -> dict[str, Any] | Response:
    try:
        _no_query(request)
        return get_service().verify(model_id).as_dict()
    except LocalModelError as exc:
        return exc.response()


@router.delete("/local/models/{model_id}", status_code=204, response_model=None)
async def remove_route(model_id: str) -> Response:
    try:
        await asyncio.to_thread(get_service().remove, model_id)
    except LocalModelError as exc:
        return exc.response()
    return Response(status_code=204)


@router.get("/local/jobs/{job_id}", response_model=None)
async def job_route(job_id: str) -> dict[str, Any] | Response:
    try:
        return get_service().get_job(job_id).as_dict()
    except LocalModelError as exc:
        return exc.response()


@router.post("/local/jobs/{job_id}/cancel", response_model=None)
async def cancel_route(job_id: str) -> dict[str, Any] | Response:
    try:
        return (await get_service().cancel(job_id)).as_dict()
    except LocalModelError as exc:
        return exc.response()


async def adopt_on_startup() -> None:
    """Recognize models installed by hand when the host engine starts; a failure never stops the service."""
    try:
        get_service().adopt()
    except LocalModelError as exc:
        logger.warning("local_model_adoption_skipped code=%s", exc.code)
