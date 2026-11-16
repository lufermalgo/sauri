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
import stat
import uuid
from collections import OrderedDict
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from hardware import detect_hardware, disk_free_bytes
from sauri_engine_common.local_model_use import MANIFEST_SUFFIX, default_models_dir
from sauri_engine_common.recommend import (
    Catalog,
    CatalogError,
    CatalogModel,
    HardwareProfile,
    load_catalog,
    recommend,
)

logger = logging.getLogger("sauri.host_engine.local_models")

DISK_HEADROOM_PERCENT: Final = 120
HASH_CHUNK_BYTES: Final = 8 << 20
MAX_REDIRECTS: Final = 5
MAX_ATTEMPTS: Final = 4
RETRY_DELAY_S: Final = 1.0
MAX_FINISHED_JOBS: Final = 20
SELECTION_FILE: Final = "selection.json"
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

    def url_for(self, model: CatalogModel) -> str:
        return f"{self.base_url}/{model.repo}/resolve/{model.revision}/{model.file}"


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
    type: str  # "install" | "verify"
    bytes_total: int
    state: str = "running"  # running | done | failed | cancelled
    bytes_done: int = 0
    error: str | None = None
    result: str | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_id": self.model_id,
            "type": self.type,
            "state": self.state,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "error": self.error,
            "result": self.result,
        }


class _Sink:
    """The open ``.part`` file with its incremental hash and byte count."""

    def __init__(self, out: Any, sha: Any, done: int) -> None:
        self.out, self.sha, self.done = out, sha, done

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


def _regular(path: Path) -> os.stat_result | None:
    """``lstat`` of a regular file (never a symlink), or None."""
    try:
        info = path.lstat()
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


class LocalModelService:
    def __init__(
        self,
        models_dir: Path | None = None,
        catalog: Catalog | None = None,
        policy: DownloadPolicy | None = None,
        token_path: Path | None = None,
    ) -> None:
        self.models_dir = models_dir or default_models_dir()
        self._catalog = catalog
        self.policy = policy or DownloadPolicy()
        self.token_path = token_path or default_token_path()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._active: Job | None = None

    # --- catalog and paths -------------------------------------------------------------------------

    @property
    def catalog(self) -> Catalog:
        if self._catalog is None:
            try:
                path = os.getenv("SAURI_MODEL_CATALOG")
                self._catalog = load_catalog(Path(path)) if path else load_catalog()
            except CatalogError:
                raise LocalModelError(503, "catalog_unavailable") from None
        return self._catalog

    def _model(self, model_id: str) -> CatalogModel:
        model = self.catalog.get(model_id)
        if model is None:
            raise LocalModelError(404, "unknown_model")
        return model

    def _paths(self, model: CatalogModel) -> tuple[Path, Path, Path]:
        assert model.file is not None
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

    def _state(self, model: CatalogModel) -> dict[str, Any]:
        """Cheap state from stat and manifest only; the hash is recomputed by ``verify``."""
        if not model.downloadable:
            return {"state": "managed", "installed_size": None, "installed_at": None}
        final, _part, manifest_path = self._paths(model)
        if self._active and self._active.type == "install" and self._active.model_id == model.id:
            return {"state": "installing", "installed_size": None, "installed_at": None}
        info = _regular(final)
        if info is None:
            return {"state": "not_installed", "installed_size": None, "installed_at": None}
        record = self._read_manifest(manifest_path)
        state = "unverified"
        installed_at = None
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
        return {"state": state, "installed_size": info.st_size, "installed_at": installed_at}

    def in_use_processes(self, model: CatalogModel) -> list[str]:
        """Processes that currently run ``model``; see the module docstring for the marker contract."""
        if model.kind == "auxiliary":
            return [model.process]
        try:
            raw = (self.models_dir / SELECTION_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            selection: dict[str, Any] = {}
        except (OSError, UnicodeError):
            raise LocalModelError(503, "selection_unreadable") from None
        else:
            try:
                parsed = json.loads(raw)
            except ValueError:
                raise LocalModelError(503, "selection_unreadable") from None
            if not isinstance(parsed, dict):
                raise LocalModelError(503, "selection_unreadable")
            selection = parsed
        chosen = selection.get(model.process)
        if chosen is None:
            return [model.process] if model.default else []
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
            "disk_free_bytes": profile.disk_free_bytes,
        }

    def list_models(self) -> dict[str, Any]:
        recommendations = recommend(self.hardware(), self.catalog)
        recommended = {rec.model_id for rec in recommendations.values() if rec.model_id}
        models = []
        for model in self.catalog.models:
            view = {
                "id": model.id,
                "process": model.process,
                "kind": model.kind,
                "engine": model.engine,
                "size": model.size,
                "min_ram_gib": model.min_ram_gib,
                "requires": list(model.requires),
                "status": model.status,
                "default": model.default,
                "managed_by": model.managed_by,
                "recommended": model.id in recommended,
                "in_use_by": self._safe_in_use(model),
                **self._state(model),
            }
            models.append(view)
        return {
            "catalog_version": self.catalog.version,
            "models": models,
            "recommendations": {process: rec.as_dict() for process, rec in recommendations.items()},
            "active_job": self._active.id if self._active else None,
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
        if self._state(model)["state"] in ("installed", "unverified"):
            raise LocalModelError(409, "already_installed")
        final, part, _manifest = self._paths(model)
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            part_info = _regular(part)
            needed = -(-model.size * DISK_HEADROOM_PERCENT // 100) - (part_info.st_size if part_info else 0)
            free = disk_free_bytes(self.models_dir)
        except OSError:
            raise LocalModelError(503, "models_dir_unavailable") from None
        if free < max(needed, 0):
            raise LocalModelError(507, "insufficient_disk", needed_bytes=needed, free_bytes=free)
        job = Job(id=uuid.uuid4().hex, model_id=model.id, type="install", bytes_total=model.size)
        logger.info("local_model_install_started model=%s", model.id)
        return self._start(job, self._run(job, self._install(job, model), part))

    def verify(self, model_id: str) -> Job:
        model = self._downloadable(model_id)
        assert model.size is not None
        self._require_idle()
        final, _part, _manifest = self._paths(model)
        info = _regular(final)
        if info is None:
            raise LocalModelError(404, "not_installed")
        job = Job(id=uuid.uuid4().hex, model_id=model.id, type="verify", bytes_total=info.st_size)
        return self._start(job, self._run(job, self._verify(job, model), None))

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
                _unlink(self._paths(self._model(job.model_id))[1])
        return job

    def remove(self, model_id: str) -> None:
        model = self._downloadable(model_id)
        if self._active is not None and self._active.model_id == model.id:
            raise LocalModelError(409, "job_active", job_id=self._active.id)
        final, part, manifest = self._paths(model)
        if _regular(final) is None:
            raise LocalModelError(404, "not_installed")
        processes = self.in_use_processes(model)
        if processes:
            raise LocalModelError(409, "model_in_use", processes=processes)
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
            if part is not None:
                _unlink(part)
            raise
        except JobError as failure:
            job.state, job.error = "failed", failure.code
            if part is not None:
                _unlink(part)
        except (OSError, httpx.HTTPError) as exc:
            # Only the class name is logged: exception text can carry a URL or a path.
            logger.warning("local_model_job_error type=%s", type(exc).__name__)
            job.state, job.error = "failed", "io_error" if isinstance(exc, OSError) else "download_failed"
            if part is not None:
                _unlink(part)
        finally:
            self._active = None
            logger.info("local_model_job_finished model=%s type=%s state=%s", job.model_id, job.type, job.state)

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

    async def _install(self, job: Job, model: CatalogModel) -> None:
        assert model.size is not None and model.sha256 is not None
        final, part, manifest = self._paths(model)
        sha = hashlib.sha256()
        info = _regular(part)
        if os.path.lexists(part) and info is None:
            raise JobError("unsafe_path")
        if info is not None and info.st_size > model.size:
            _unlink(part)
            info = None
        if info is not None:
            await self._hash_into(part, sha, job)  # resume: re-hash what is already on disk
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "ab") as out:
            sink = _Sink(out, sha, job.bytes_done)
            token = self._token()
            attempts = 0
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False, trust_env=False
            ) as client:
                while sink.done < model.size:
                    before = sink.done
                    try:
                        await self._fetch(client, model, sink, job, token)
                    except httpx.TransportError as exc:
                        logger.warning("local_model_connection_lost type=%s", type(exc).__name__)
                    if sink.done < model.size:
                        # A cut that made progress does not count against the retry budget.
                        attempts = 0 if sink.done > before else attempts + 1
                        if attempts >= MAX_ATTEMPTS:
                            raise JobError("connection_lost")
                        await asyncio.sleep(RETRY_DELAY_S)
            out.flush()
            os.fsync(out.fileno())
        if not hmac.compare_digest(sink.sha.hexdigest(), model.sha256):
            raise JobError("hash_mismatch")
        os.replace(part, final)
        self._write_manifest(model, final, manifest, "installed")
        job.result = "installed"

    async def _fetch(
        self, client: httpx.AsyncClient, model: CatalogModel, sink: _Sink, job: Job, token: str | None
    ) -> None:
        headers = {"Accept-Encoding": "identity"}
        if sink.done:
            headers["Range"] = f"bytes={sink.done}-"
        url = self.policy.url_for(model)
        if not self.policy.allows(url):
            raise JobError("url_not_allowed")
        for _hop in range(MAX_REDIRECTS + 1):
            hop_headers = dict(headers)
            if token and self.policy.sends_token(url):
                hop_headers["Authorization"] = f"Bearer {token}"
            async with client.stream("GET", url, headers=hop_headers) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    url = urljoin(url, location) if location else ""
                    if not url or not self.policy.allows(url):
                        raise JobError("redirect_not_allowed")
                    continue
                await self._consume(response, model, sink, job)
                return
        raise JobError("too_many_redirects")

    async def _consume(self, response: httpx.Response, model: CatalogModel, sink: _Sink, job: Job) -> None:
        assert model.size is not None
        status = response.status_code
        if status == 206:
            match = _CONTENT_RANGE.fullmatch(response.headers.get("content-range", ""))
            if match is None or int(match[1]) != sink.done or int(match[3]) != model.size:
                raise JobError("bad_range")
        elif status == 200:
            length = response.headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) != model.size):
                raise JobError("size_mismatch")
            if sink.done:
                sink.restart()  # the server ignored Range: start over
                job.bytes_done = 0
        elif status in (401, 403):
            raise JobError("download_unauthorized")
        elif status == 404:
            raise JobError("download_not_found")
        else:
            raise JobError("download_http_error")
        async for chunk in response.aiter_raw():
            if sink.done + len(chunk) > model.size:
                raise JobError("size_exceeded")
            sink.out.write(chunk)
            sink.sha.update(chunk)
            sink.done += len(chunk)
            job.bytes_done = sink.done

    async def _verify(self, job: Job, model: CatalogModel) -> None:
        assert model.sha256 is not None
        final, _part, manifest = self._paths(model)
        sha = hashlib.sha256()
        await self._hash_into(final, sha, job)
        info = _regular(final)
        if info is None:
            raise JobError("not_installed")
        matches = hmac.compare_digest(sha.hexdigest(), model.sha256) and info.st_size == model.size
        self._write_manifest(model, final, manifest, "installed" if matches else "corrupt")
        job.result = "verified" if matches else "corrupt"

    def _write_manifest(self, model: CatalogModel, final: Path, manifest: Path, status: str) -> None:
        info = final.stat()
        record = {
            "id": model.id,
            "file": model.file,
            "revision": model.revision,
            "sha256": model.sha256,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "installed_at": _now(),
            "status": status,
        }
        temporary = manifest.with_name(manifest.name + ".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, manifest)


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
