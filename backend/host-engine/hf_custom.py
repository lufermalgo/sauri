"""Custom models from public Hugging Face repositories ("Other" in Settings; spec settings-redesign R3).

A custom model is one weights file the user names by repository (``owner/repo``) or by a ``huggingface.co`` /
``hf.co`` URL (repository, ``tree``, ``blob`` or ``resolve``). Security properties:

* The source is only parsed: its host must be a Hugging Face one and its owner, repository, revision and path
  must match strict alphabets (no ``..``, no empty or dot segments). Every request is built from those parts
  on the download policy's own base URL, never from the URL the user typed.
* The revision is pinned to a commit SHA through the public API (``/api/models/{repo}/revision/{rev}``) and the
  files are listed at that commit (``/tree/{sha}?recursive=1``). SHA-256 and size come from the LFS metadata
  (``lfs.oid`` / ``lfs.size``); a file without LFS metadata is never offered. No account or token is used:
  a private or gated repository is refused.
* Only weights files are offered (``.gguf`` for summary, ``ggml-*.bin`` for transcription), at most 20 GiB.
  They are data: nothing downloaded is executed, imported or loaded as code by the host service.
* API redirects are followed by hand and only to hosts the policy allows; responses are size-capped.

Installed custom models are kept in ``<models>/custom_models.json`` (user data next to the models, never the
pinned catalog), and their files in ``<models>/custom/``. Each entry is re-validated when it is read.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx
from sauri_engine_common.recommend import CatalogModel

PROCESS_ENGINES: Final = {"transcription": "whisper.cpp", "summary": "llama.cpp"}
MAX_FILE_BYTES: Final = 20 << 30
CUSTOM_PREFIX: Final = "custom-"
REGISTRY_FILE: Final = "custom_models.json"
REGISTRY_VERSION: Final = 1
CUSTOM_DIR: Final = "custom"
SOURCE_HOSTS: Final = frozenset({"huggingface.co", "www.huggingface.co", "hf.co"})
MAX_SOURCE_CHARS: Final = 512
MAX_PATH_CHARS: Final = 512
MAX_TREE_PAGES: Final = 50
MAX_API_BYTES: Final = 16 << 20
MAX_API_REDIRECTS: Final = 5
API_TIMEOUT_S: Final = 10.0
_ID_HEX: Final = 16

_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
_REVISION: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_SEGMENT: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+-]{0,199}")
_LICENSE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
_CUSTOM_ID: Final = re.compile(rf"{CUSTOM_PREFIX}[0-9a-f]{{{_ID_HEX}}}")
_GGML_BIN: Final = re.compile(r"ggml-[A-Za-z0-9._+-]+\.bin")
_VAD: Final = re.compile(r"silero|vad", re.IGNORECASE)
# One shard of a split GGUF cannot be loaded on its own; a vision projector is not a chat model.
_GGUF_SHARD: Final = re.compile(r"-\d{5}-of-\d{5}\.gguf", re.IGNORECASE)
_LINK_NEXT: Final = re.compile(r'<([^>]+)>\s*;\s*rel="next"')
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
_HOST_LIKE: Final = re.compile(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d+)?")
_URL_FORMS: Final = frozenset({"tree", "blob", "resolve"})
_RESERVED_OWNERS: Final = frozenset({"datasets", "spaces", "api", "models"})


class CustomModelError(Exception):
    """A refusal with an HTTP status and a stable code (never a path, URL or value)."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


@dataclass(frozen=True)
class Source:
    repo: str
    revision: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class CustomFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Resolved:
    repo: str
    revision: str
    license: str | None
    files: tuple[CustomFile, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "revision": self.revision,
            "license": self.license,
            "files": [asdict(item) for item in self.files],
        }


@dataclass(frozen=True)
class CustomEntry:
    """One installed custom model as the registry keeps it."""

    process: str
    repo: str
    revision: str
    path: str  # the file inside the repository
    size: int
    sha256: str
    license: str | None = None
    installed_at: str | None = None

    @property
    def id(self) -> str:
        return CUSTOM_PREFIX + self.sha256[:_ID_HEX]

    @property
    def file(self) -> str:
        """Where the file lives, relative to the models directory (never a name taken as is from the repository)."""
        return f"{CUSTOM_DIR}/{self.sha256[:_ID_HEX]}-{self.path.rsplit('/', 1)[-1]}"

    def model(self) -> CatalogModel:
        """The entry as a catalog model, so install, verify and removal work as for any other model."""
        return CatalogModel(
            id=self.id, process=self.process, kind="model", engine=PROCESS_ENGINES[self.process],  # type: ignore[arg-type]
            repo=self.repo, revision=self.revision, file=self.file, size=self.size, sha256=self.sha256,
            min_ram_gib=0, requires=(), rank=1000, status="proposal", default=False, license=self.license,
        )  # fmt: skip

    def origin(self) -> dict[str, str]:
        return {"repo": self.repo, "revision": self.revision, "file": self.path}


def is_custom_id(model_id: str) -> bool:
    return _CUSTOM_ID.fullmatch(model_id) is not None


def check_process(process: Any) -> str:
    if process not in PROCESS_ENGINES:
        raise CustomModelError(422, "invalid_process")
    return str(process)


def check_repo(repo: Any) -> str:
    if not isinstance(repo, str):
        raise CustomModelError(422, "invalid_source")
    owner, _, name = repo.partition("/")
    if not _valid_name(owner) or not _valid_name(name) or owner.lower() in _RESERVED_OWNERS:
        raise CustomModelError(422, "invalid_source")
    return repo


def check_path(path: Any) -> str:
    """A file path inside a repository: safe segments only, no ``..``, no absolute path, no backslash."""
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS:
        raise CustomModelError(422, "invalid_file")
    segments = path.split("/")
    if any(segment in (".", "..") or _SEGMENT.fullmatch(segment) is None for segment in segments):
        raise CustomModelError(422, "invalid_file")
    return path


def _valid_name(name: str) -> bool:
    return _NAME.fullmatch(name) is not None and ".." not in name


def parse_source(source: Any) -> Source:
    """``owner/repo`` or a Hugging Face URL (repository, ``tree``, ``blob`` or ``resolve``); see the docstring."""
    if not isinstance(source, str):
        raise CustomModelError(422, "invalid_source")
    text = source.strip()
    if not text or len(text) > MAX_SOURCE_CHARS or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in text):
        raise CustomModelError(422, "invalid_source")
    if "://" in text:
        text = _url_path(text)
    elif _HOST_LIKE.fullmatch(text.split("/", 1)[0]):
        text = _url_path("https://" + text)  # "huggingface.co/owner/repo" typed without the scheme
    segments = [unquote(segment) for segment in text.strip("/").split("/")]
    if len(segments) < 2:
        raise CustomModelError(422, "invalid_source")
    repo = check_repo(f"{segments[0]}/{segments[1]}")
    rest = segments[2:]
    if not rest:
        return Source(repo)
    form = rest[0]
    if form not in _URL_FORMS or len(rest) < 2:
        raise CustomModelError(422, "invalid_source")
    revision = rest[1]
    if _REVISION.fullmatch(revision) is None or ".." in revision:
        raise CustomModelError(422, "invalid_source")
    if form == "tree":
        return Source(repo, revision)
    if len(rest) < 3:
        raise CustomModelError(422, "invalid_source")
    try:
        path = check_path("/".join(rest[2:]))
    except CustomModelError:
        raise CustomModelError(422, "invalid_source") from None
    return Source(repo, revision, path)


def _url_path(url: str) -> str:
    """The path of a Hugging Face URL; any other host (or credentials, or another port) is refused."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise CustomModelError(422, "invalid_source") from None
    if parts.scheme not in ("https", "http"):
        raise CustomModelError(422, "invalid_source")
    host = (parts.hostname or "").lower()
    if host not in SOURCE_HOSTS or parts.username is not None or parts.password is not None:
        raise CustomModelError(422, "host_not_allowed")
    if port not in (None, 443):
        raise CustomModelError(422, "host_not_allowed")
    return parts.path


def compatible(process: str, path: str) -> bool:
    """Weights files an engine of ``process`` can load: ``.gguf`` for summary, ``ggml-*.bin`` for transcription."""
    name = path.rsplit("/", 1)[-1]
    if process == "summary":
        return (
            name.lower().endswith(".gguf")
            and _GGUF_SHARD.search(name) is None
            and not name.lower().startswith("mmproj")
        )
    # A voice detector (Silero VAD) uses the same naming but cannot transcribe.
    return _GGML_BIN.fullmatch(name) is not None and _VAD.search(name) is None


# --- Hugging Face API ---------------------------------------------------------------------------------


class HubClient:
    """Read-only calls to the public Hugging Face API, never with a credential.

    ``base_url`` and ``allows`` come from the download policy, so tests can point both at a loopback server.
    """

    def __init__(self, base_url: str, allows: Callable[[str], bool]) -> None:
        self.base_url, self.allows = base_url.rstrip("/"), allows

    @staticmethod
    def _client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(API_TIMEOUT_S, connect=5.0), follow_redirects=False, trust_env=False
        )

    async def resolve(self, process: str, source: Source) -> Resolved:
        """Pin the revision to a commit and list the compatible files (only ``source.path`` when it names one)."""
        revision = source.revision or "main"
        try:
            async with self._client() as client:
                info = await self._model_info(client, source.repo, revision)
                sha = info.get("sha")
                if not isinstance(sha, str) or COMMIT.fullmatch(sha) is None:
                    raise CustomModelError(503, "unreachable")
                if info.get("gated") not in (None, False) or info.get("private") is True:
                    raise CustomModelError(403, "gated")
                entries = await self._tree(client, source.repo, sha)
        except httpx.HTTPError:
            raise CustomModelError(503, "unreachable") from None
        files = _lfs_files(entries)
        if source.path is not None:
            files = [item for item in files if item.path == source.path]
            if not files:
                listed = any(isinstance(item, dict) and item.get("path") == source.path for item in entries)
                raise CustomModelError(422 if listed else 404, "no_compatible_files" if listed else "not_found")
        offered = tuple(sorted((item for item in files if compatible(process, item.path)), key=lambda f: f.path))
        if not offered:
            raise CustomModelError(422, "no_compatible_files")
        return Resolved(source.repo, sha, _license(info), offered)

    async def _model_info(self, client: httpx.AsyncClient, repo: str, revision: str) -> dict[str, Any]:
        url = f"{self.base_url}/api/models/{repo}/revision/{quote(revision, safe='')}"
        status, headers, body = await self._get_json(client, url)
        if status in (401, 403):
            # Anonymous calls get 401 for a repository that does not exist or is private.
            missing = headers.get("x-error-code", "").lower() in ("reponotfound", "revisionnotfound")
            raise CustomModelError(404 if missing else 403, "not_found" if missing else "gated")
        if status == 404:
            raise CustomModelError(404, "not_found")
        if status != 200 or not isinstance(body, dict):
            raise CustomModelError(503, "unreachable")
        return body

    async def _tree(self, client: httpx.AsyncClient, repo: str, sha: str) -> list[Any]:
        url: str | None = f"{self.base_url}/api/models/{repo}/tree/{sha}?recursive=1"
        entries: list[Any] = []
        for _page in range(MAX_TREE_PAGES):
            if url is None:
                return entries
            status, headers, body = await self._get_json(client, url)
            if status in (401, 403):
                raise CustomModelError(403, "gated")
            if status == 404:
                raise CustomModelError(404, "not_found")
            if status != 200 or not isinstance(body, list):
                raise CustomModelError(503, "unreachable")
            entries.extend(body)
            match = _LINK_NEXT.search(headers.get("link", ""))
            url = urljoin(url, match[1]) if match else None
        if url is not None:
            raise CustomModelError(503, "unreachable")  # far more files than any model repository has
        return entries

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> tuple[int, httpx.Headers, Any]:
        """GET with redirects followed by hand (allowed hosts only) and a capped body."""
        for _hop in range(MAX_API_REDIRECTS + 1):
            if not self.allows(url):
                raise CustomModelError(503, "unreachable")
            async with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    url = urljoin(url, location) if location else ""
                    continue
                if response.status_code != 200:
                    return response.status_code, response.headers, None
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_API_BYTES:
                        raise CustomModelError(503, "unreachable")
                try:
                    return 200, response.headers, json.loads(bytes(data))
                except ValueError:
                    raise CustomModelError(503, "unreachable") from None
        raise CustomModelError(503, "unreachable")


def _lfs_files(entries: list[Any]) -> list[CustomFile]:
    """Files whose LFS metadata gives a SHA-256 and a size within the cap; anything else is left out."""
    files = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        lfs, path = entry.get("lfs"), entry.get("path")
        if not isinstance(lfs, dict):
            continue
        oid, size = lfs.get("oid"), lfs.get("size")
        if not isinstance(oid, str) or _SHA256.fullmatch(oid) is None:
            continue
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_FILE_BYTES:
            continue
        try:
            files.append(CustomFile(check_path(path), size, oid))
        except CustomModelError:
            continue
    return files


def _license(info: dict[str, Any]) -> str | None:
    card = info.get("cardData")
    value = card.get("license") if isinstance(card, dict) else None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        tags = info.get("tags")
        if isinstance(tags, list):
            value = next((tag[8:] for tag in tags if isinstance(tag, str) and tag.startswith("license:")), None)
    return value if isinstance(value, str) and _LICENSE.fullmatch(value) else None


# --- registry -----------------------------------------------------------------------------------------


def registry_path(models_dir: Path) -> Path:
    return models_dir / REGISTRY_FILE


def _entry(raw: Any) -> CustomEntry | None:
    """A registry record, re-validated as if it came from the network; None when anything is off."""
    if not isinstance(raw, dict):
        return None
    try:
        process = check_process(raw.get("process"))
        repo = check_repo(raw.get("repo"))
        path = check_path(raw.get("path"))
    except CustomModelError:
        return None
    revision, size, sha256 = raw.get("revision"), raw.get("size"), raw.get("sha256")
    license_, installed_at = raw.get("license"), raw.get("installed_at")
    if not isinstance(revision, str) or COMMIT.fullmatch(revision) is None:
        return None
    if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
        return None
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_FILE_BYTES:
        return None
    if not compatible(process, path):
        return None
    license_ = license_ if isinstance(license_, str) and _LICENSE.fullmatch(license_) else None
    installed_at = installed_at if isinstance(installed_at, str) and len(installed_at) <= 64 else None
    return CustomEntry(process, repo, revision, path, size, sha256, license_, installed_at)


def read_registry(models_dir: Path) -> list[CustomEntry]:
    """The installed custom models; a missing registry is empty. Raises ``OSError``/``ValueError`` when unreadable."""
    try:
        raw = registry_path(models_dir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("custom_registry_invalid")
    entries: dict[str, CustomEntry] = {}
    for item in data["models"]:
        entry = _entry(item)
        if entry is not None:
            entries.setdefault(entry.id, entry)
    return list(entries.values())


def write_registry(models_dir: Path, entries: list[CustomEntry]) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    target = registry_path(models_dir)
    temporary = target.with_name(target.name + ".tmp")
    record = {"version": REGISTRY_VERSION, "models": [asdict(entry) for entry in entries]}
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
