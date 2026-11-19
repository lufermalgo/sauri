"""Custom models (a weights file from a public Hugging Face repository): the registry and its validation.

Shared by ``host-engine`` (which installs, verifies and removes them) and the engine gateways (which load the one a
route names). The registry is ``<models>/custom_models.json``, user data next to the models and never the pinned
catalog; the files live in ``<models>/custom/``. Every record is validated again when it is read, as if it came
from the network: a record with any field out of its alphabet (a ``..`` path, a revision that is not a commit, a
size over 20 GiB, a file the process cannot use) is ignored. A custom model is turned into a ``CatalogModel`` so
the usual manifest check (``installed``, SHA-256, size and ``mtime_ns``) applies to it unchanged.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from sauri_engine_common.recommend import CatalogModel

PROCESS_ENGINES: Final = {"transcription": "whisper.cpp", "summary": "llama.cpp"}
MAX_FILE_BYTES: Final = 20 << 30
CUSTOM_PREFIX: Final = "custom-"
REGISTRY_FILE: Final = "custom_models.json"
REGISTRY_VERSION: Final = 1
CUSTOM_DIR: Final = "custom"
MAX_PATH_CHARS: Final = 512
_ID_HEX: Final = 16

COMMIT: Final = re.compile(r"[0-9a-f]{40}")
SHA256: Final = re.compile(r"[0-9a-f]{64}")
LICENSE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
_SEGMENT: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._+-]{0,199}")
_CUSTOM_ID: Final = re.compile(rf"{CUSTOM_PREFIX}[0-9a-f]{{{_ID_HEX}}}")
_GGML_BIN: Final = re.compile(r"ggml-[A-Za-z0-9._+-]+\.bin")
_VAD: Final = re.compile(r"silero|vad", re.IGNORECASE)
# One shard of a split GGUF cannot be loaded on its own; a vision projector is not a chat model.
_GGUF_SHARD: Final = re.compile(r"-\d{5}-of-\d{5}\.gguf", re.IGNORECASE)
_RESERVED_OWNERS: Final = frozenset({"datasets", "spaces", "api", "models"})


class CustomModelError(Exception):
    """A refusal with an HTTP status and a stable code (never a path, URL or value)."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


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
        """The entry as a catalog model, so install, verify, removal and loading work as for any other model."""
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


def registry_path(models_dir: Path) -> Path:
    return models_dir / REGISTRY_FILE


def _entry(raw: Any) -> CustomEntry | None:
    """A registry record, validated again as if it came from the network; None when anything is off."""
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
    if not isinstance(sha256, str) or SHA256.fullmatch(sha256) is None:
        return None
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_FILE_BYTES:
        return None
    if not compatible(process, path):
        return None
    license_ = license_ if isinstance(license_, str) and LICENSE.fullmatch(license_) else None
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


def find_custom(models_dir: Path, model_id: str, process: str) -> CatalogModel | None:
    """The custom model ``model_id`` of ``process`` from the registry; None when absent or unreadable."""
    try:
        entries = read_registry(models_dir)
    except (OSError, UnicodeError, ValueError):
        return None
    entry = next((item for item in entries if item.id == model_id and item.process == process), None)
    return None if entry is None else entry.model()
