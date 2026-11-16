"""Provider connection probe, model catalog and local model-app discovery for the host service.

Every outbound call goes through ``SafeHttp`` (``sauri_engine_common.external.safe_http``), the only place that
opens a connection: resolved-IP pinning, no redirects, capped bodies, ``https`` required except for loopback
targets of a declared local app (``allow_local``).

Keys are read from the secret store by reference, only after their bound origin matches the target.
Nothing here returns or logs a key, a header or a provider body: failures carry a closed error class,
a short cause code and, at most, a provider error code limited to ``[A-Za-z0-9_.:-]`` and 64 characters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sauri_engine_common.external.errors import ProviderError, classify
from sauri_engine_common.external.safe_http import (
    CONNECT_TIMEOUT_S,
    MAX_RESPONSE_BYTES,  # noqa: F401  (re-exported: the provider tests import the SSRF helpers from here)
    MAX_URL_CHARS,
    HttpResult,
    SafeHttp,
    address_allowed,  # noqa: F401
    classify_address,  # noqa: F401
    parse_ip_literal,  # noqa: F401
    parse_target,  # noqa: F401
)
from sauri_engine_common.route import Capability, RouteError, Transport, origin_of
from sauri_engine_common.secrets import SecretError, SecretRecord, SecretStore, validate_ref

logger = logging.getLogger("sauri.host_engine.providers")

PROBE_TIMEOUT_S: Final = 10.0
MODELS_TIMEOUT_S: Final = 15.0
LOCAL_TIMEOUT_S: Final = 1.5
MAX_REQUEST_BYTES: Final = 16 * 1024
MAX_MODELS: Final = 1000
CACHE_TTL_S: Final = 24 * 3600.0
CACHE_MAX_ENTRIES: Final = 64
ANTHROPIC_VERSION: Final = "2023-06-01"
LOCAL_APPS: Final[tuple[tuple[str, str, int], ...]] = (("ollama", "Ollama", 11434), ("lmstudio", "LM Studio", 1234))
LOCAL_APP_KINDS: Final = frozenset(app_id for app_id, _label, _port in LOCAL_APPS)

# Request-validation causes: the caller sent a target that must never be contacted.
REQUEST_CAUSES: Final = frozenset(
    {"invalid_url", "base_url_invalid", "invalid_host", "address_not_allowed", "https_required"}
)


# --- models: parsing, filtering, starter ---------------------------------------------------------------

# Ids that name non-chat models (speech, embeddings, images...), plus common embedding and rerank families.
NOT_CHAT: Final = re.compile(
    r"(embed|tts|audio|speech|transcri|whisper|image|imagen|veo|dall-e|moderation|aqa|realtime|rerank|bge|minilm"
    r"|nomic|mxbai|sora|lyria|(?:^|[^a-z0-9])(?:gte|e5)(?:$|[^a-z0-9]))",
    re.IGNORECASE,
)
_AUDIO_IN: Final = re.compile(r"(whisper|transcri|scribe|stt|speech-to-text|asr)", re.IGNORECASE)
_AUDIO_OUT: Final = re.compile(r"(tts|synthes|text-to-speech|playai)", re.IGNORECASE)
# Starter ("Auto") model: the everyday chat model of the provider, read from its own list.
_LIGHT: Final = re.compile(r"(?:^|[^a-z])(flash|mini|haiku|small|instant|fast)(?:$|[^a-z])", re.IGNORECASE)
_TINY: Final = re.compile(r"(?:^|[^a-z])(lite|nano|tiny|micro|[1-3]b)(?:$|[^a-z])", re.IGNORECASE)
_ODD: Final = re.compile(
    r"(preview|exp|experimental|beta|alpha|thinking|codex|coder|code|guard|vision|search|instruct|tuning|learnlm)",
    re.IGNORECASE,
)
_DATED: Final = re.compile(r"\d{4}-?\d{2}-?\d{2}")


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str


def _version(model_id: str) -> list[int]:
    return [int(number) for number in re.findall(r"\d+", _DATED.sub("", model_id))]


def _newest_first(model_id: str) -> tuple[list[int], int]:
    # Descending version (a missing part counts as -1, so 4.1 beats 4), then the plain alias before a
    # suffixed or dated twin.
    numbers = _version(model_id)[:8]
    return ([-number for number in numbers] + [1] * (8 - len(numbers)), len(model_id))


def starter_model(ids: list[str]) -> str | None:
    """The model a new provider starts with (port of the APX rule): light tier first, newest version."""
    usual = [model_id for model_id in ids if not _ODD.search(model_id)]
    plain = [model_id for model_id in usual if not _DATED.search(model_id)]
    pool = plain or usual or ids
    light = [model_id for model_id in pool if _LIGHT.search(model_id) and not _TINY.search(model_id)]
    candidates = light or [model_id for model_id in pool if not _TINY.search(model_id)] or pool
    return min(candidates, key=_newest_first) if candidates else None


def filter_models(models: list[ModelInfo], capability: Capability) -> list[ModelInfo]:
    """Keep what the process can use: chat models for summary/chat, speech-to-text models for audio."""
    if capability in ("summary", "chat"):
        return [model for model in models if not NOT_CHAT.search(model.id)]
    return [model for model in models if _AUDIO_IN.search(model.id) and not _AUDIO_OUT.search(model.id)]


def parse_models(body: bytes) -> list[ModelInfo]:
    try:
        data = json.loads(body)
    except ValueError:
        raise ProviderError("provider_invalid_output", reason="invalid_response") from None
    listed = data.get("data") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        raise ProviderError("provider_invalid_output", reason="invalid_response")
    models: dict[str, ModelInfo] = {}
    for entry in listed:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        model_id = entry["id"].removeprefix("models/")
        if not model_id or len(model_id) > 256 or any(ord(char) < 0x20 for char in model_id):
            continue
        label = entry.get("display_name")
        name = label if isinstance(label, str) and label and len(label) <= 128 else model_id
        models.setdefault(model_id, ModelInfo(model_id, name))
        if len(models) >= MAX_MODELS:
            break
    return list(models.values())


def _public_model(model: ModelInfo) -> dict[str, str]:
    return {"id": model.id, "name": model.name}


# --- requests -----------------------------------------------------------------------------------------

_HINT: Final = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
PROBE_SCHEMA: Final = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


class _Target(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    transport: Transport
    base_url: str = Field(min_length=1, max_length=MAX_URL_CHARS)
    secret_ref: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._/-]{1,200}$")
    # Set by the API layer only for declared local apps; admits loopback and private addresses.
    allow_local: bool = False


class ProbeBody(_Target):
    capability: Capability | None = None
    model: str | None = Field(default=None, min_length=1, max_length=256)


class ModelsBody(_Target):
    capability: Capability
    refresh: bool = False


class UpstreamError(ProviderError):
    """A classified provider failure with the HTTP status and a bounded, key-free provider code."""

    def __init__(self, code: str, *, reason: str, status: int, hint: str | None, retry_after_s: int | None) -> None:
        super().__init__(code, reason=reason, retry_after_s=retry_after_s)
        self.status = status
        self.hint = hint


def _join(base: str, suffix: str) -> str:
    return base.rstrip("/") + suffix


def _anthropic_url(base: str, suffix: str) -> str:
    base = base.rstrip("/")
    return _join(base.removesuffix("/v1"), "/v1" + suffix)


def _auth_headers(transport: Transport, key: str | None) -> dict[str, str]:
    if key is None:
        return {}
    if transport == "anthropic-messages":
        return {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    if transport == "assemblyai":
        return {"authorization": key}
    if transport == "deepgram":
        return {"authorization": f"Token {key}"}
    return {"authorization": f"Bearer {key}"}


def _check_url(body: _Target) -> tuple[str, str]:
    """(method-less) URL of the cheap authenticated call that proves the provider answers."""
    base = body.base_url
    if body.transport == "anthropic-messages":
        return "models", _anthropic_url(base, "/models?limit=100")
    if body.transport == "assemblyai":
        return "reachable", _join(base, "/v2/transcript?limit=1")
    if body.transport == "deepgram":
        return "reachable", _join(base, "/v1/projects")
    return "models", _join(base, "/models")


def _error_hint(body: bytes, key: str | None) -> str | None:
    """A provider error code such as ``invalid_api_key``; never free text, never anything containing the key."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    error = data.get("error") if isinstance(data, dict) else None
    candidates: list[Any] = []
    if isinstance(error, dict):
        candidates += [error.get("code"), error.get("type"), error.get("status")]
    elif isinstance(error, str):
        candidates.append(error)
    if isinstance(data, dict):
        candidates.append(data.get("type"))
    for candidate in candidates:
        if isinstance(candidate, str) and _HINT.fullmatch(candidate):
            if key and key.lower() in candidate.lower():
                return None
            return candidate.lower()
    return None


def _raise_for_status(result: HttpResult, key: str | None) -> None:
    if 200 <= result.status < 300:
        return
    hint = _error_hint(result.body, key)
    base = classify(result.status, hint, retry_after=result.retry_after)
    reason = "redirect_refused" if 300 <= result.status < 400 else f"http_{result.status}"
    raise UpstreamError(base.code, reason=reason, status=result.status, hint=hint, retry_after_s=base.retry_after_s)


def _schema_request(body: ProbeBody, model: str) -> tuple[str, dict[str, Any]]:
    prompt = 'Reply with the JSON object {"ok": true}.'
    messages = [{"role": "user", "content": prompt}]
    if body.transport == "anthropic-messages":
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 64,
            "messages": messages,
            "output_config": {"format": {"type": "json_schema", "schema": PROBE_SCHEMA}},
        }
        return _anthropic_url(body.base_url, "/messages"), payload
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "probe", "strict": True, "schema": PROBE_SCHEMA},
        },
    }
    if body.kind == "openrouter":
        payload["provider"] = {"require_parameters": True}
    return _join(body.base_url, "/chat/completions"), payload


def _schema_text(transport: Transport, body: bytes) -> str | None:
    try:
        data = json.loads(body)
        if transport == "anthropic-messages":
            blocks = [block for block in data["content"] if block.get("type") == "text"]
            text = blocks[0]["text"]
        else:
            text = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None
    return text if isinstance(text, str) else None


def _matches_probe_schema(text: str | None) -> bool:
    if text is None:
        return False
    try:
        value = json.loads(text)
    except ValueError:
        return False
    return isinstance(value, dict) and set(value) == {"ok"} and isinstance(value["ok"], bool)


def _failure(exc: ProviderError) -> dict[str, Any]:
    return {
        "error_class": exc.code,
        "retryable": exc.retryable,
        "retry_after_s": exc.retry_after_s,
        "cause": exc.reason,
        "hint": exc.hint if isinstance(exc, UpstreamError) else None,
    }


# --- service -------------------------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    models: list[ModelInfo]
    stored_at: float
    fetched_at: str


class ProviderService:
    def __init__(
        self,
        *,
        http: SafeHttp | None = None,
        clock: Callable[[], float] = time.monotonic,
        local_apps: tuple[tuple[str, str, int], ...] = LOCAL_APPS,
        probe_timeout_s: float = PROBE_TIMEOUT_S,
        models_timeout_s: float = MODELS_TIMEOUT_S,
        local_timeout_s: float = LOCAL_TIMEOUT_S,
        connect_timeout_s: float = CONNECT_TIMEOUT_S,
    ) -> None:
        self._http = http or SafeHttp()
        self._clock = clock
        self._local_apps = local_apps
        self._probe_timeout_s = probe_timeout_s
        self._models_timeout_s = models_timeout_s
        self._local_timeout_s = local_timeout_s
        self._connect_timeout_s = connect_timeout_s
        self._cache: dict[tuple[str, str, str, str | None], _CacheEntry] = {}

    async def _record(self, store: SecretStore, body: _Target) -> SecretRecord | None:
        if body.secret_ref is None:
            return None
        try:
            record = await asyncio.to_thread(store.get, validate_ref(body.secret_ref))
        except SecretError:
            raise ProviderError("secret_unavailable") from None
        try:
            matches = origin_of(record.origin) == origin_of(body.base_url)
        except RouteError:
            matches = False
        if not matches:
            raise ProviderError("origin_mismatch")  # the key is never sent to another origin
        return record

    async def _call(
        self, method: str, url: str, key: str | None, transport: Transport, body: bytes | None, *,
        allow_local: bool, timeout_s: float,
    ) -> HttpResult:  # fmt: skip
        headers = _auth_headers(transport, key)
        if body is not None:
            headers["content-type"] = "application/json"
        result = await self._http.request(
            method, url, headers=headers, body=body, allow_local=allow_local,
            total_timeout_s=timeout_s, connect_timeout_s=min(self._connect_timeout_s, timeout_s),
        )  # fmt: skip
        _raise_for_status(result, key)
        return result

    async def _list_models(self, body: _Target, key: str | None, timeout_s: float) -> list[ModelInfo]:
        if body.transport == "chatgpt-responses":
            raise ProviderError("provider_unsupported")
        _kind, url = _check_url(body)
        result = await self._call(
            "GET", url, key, body.transport, None, allow_local=body.allow_local, timeout_s=timeout_s
        )
        if body.transport in ("assemblyai", "deepgram"):
            return []  # the model is fixed by the provider; the call only proves the key works
        return parse_models(result.body)

    async def probe(self, store: SecretStore, body: ProbeBody) -> dict[str, Any]:
        started = time.monotonic()
        result: dict[str, Any] = {"ok": False, "json_schema_ok": None}
        key: str | None = None
        try:
            record = await self._record(store, body)
            key = record.key if record is not None else None
            models = await self._list_models(body, key, self._probe_timeout_s)
        except ProviderError as exc:
            result.update(_failure(exc))
            result["latency_ms"] = round((time.monotonic() - started) * 1000)
            logger.info("probe ok=false class=%s cause=%s", exc.code, exc.reason)
            return result
        result.update(ok=True, latency_ms=round((time.monotonic() - started) * 1000))
        if body.capability in ("summary", "chat") and body.transport in ("openai-chat", "anthropic-messages"):
            result.update(await self._check_schema(body, key, models))
        logger.info("probe ok=true schema=%s", result.get("json_schema_ok"))
        return result

    async def _check_schema(self, body: ProbeBody, key: str | None, models: list[ModelInfo]) -> dict[str, Any]:
        """One minimal request with a JSON schema; ``False`` only when the provider cannot honor it."""
        model = body.model or starter_model([m.id for m in filter_models(models, "chat")])
        if model is None:
            return {"json_schema_ok": None, "schema_cause": "no_chat_model"}
        url, payload = _schema_request(body, model)
        try:
            result = await self._call(
                "POST", url, key, body.transport, json.dumps(payload).encode(),
                allow_local=body.allow_local, timeout_s=self._probe_timeout_s,
            )  # fmt: skip
        except UpstreamError as exc:
            if exc.status in (400, 404, 422):
                return {"json_schema_ok": False, "schema_cause": exc.reason, "schema_hint": exc.hint}
            return {"json_schema_ok": None, "schema_cause": exc.reason, "schema_error_class": exc.code}
        except ProviderError as exc:
            return {"json_schema_ok": None, "schema_cause": exc.reason, "schema_error_class": exc.code}
        if _matches_probe_schema(_schema_text(body.transport, result.body)):
            return {"json_schema_ok": True, "schema_model": model}
        return {"json_schema_ok": False, "schema_cause": "output_not_schema", "schema_model": model}

    async def models(self, store: SecretStore, body: ModelsBody) -> dict[str, Any]:
        cache_key = (body.kind, body.transport, body.base_url.rstrip("/"), body.secret_ref)
        entry = self._cache.get(cache_key)
        fresh = entry is not None and self._clock() - entry.stored_at < CACHE_TTL_S
        # A model app on this computer answers at once or not at all: it is asked every time.
        cached = fresh and not body.refresh and body.kind not in LOCAL_APP_KINDS
        if not cached or entry is None:
            record = await self._record(store, body)
            listed = await self._list_models(body, record.key if record else None, self._models_timeout_s)
            entry = _CacheEntry(listed, self._clock(), datetime.now(UTC).isoformat(timespec="seconds"))
            if body.kind not in LOCAL_APP_KINDS:
                self._remember(cache_key, entry)
        shown = filter_models(entry.models, body.capability)
        return {
            "models": [_public_model(model) for model in shown],
            "starter": starter_model([model.id for model in shown]),
            "fetched_at": entry.fetched_at,
            "cached": cached,
        }

    def _remember(self, key: tuple[str, str, str, str | None], entry: _CacheEntry) -> None:
        self._cache.pop(key, None)
        while len(self._cache) >= CACHE_MAX_ENTRIES:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = entry

    async def _look(self, app_id: str, label: str, port: int) -> dict[str, Any]:
        base = f"http://127.0.0.1:{port}/v1"
        found: dict[str, Any] = {"id": app_id, "label": label, "port": port, "base_url": base, "running": False}
        try:
            result = await self._http.request(
                "GET", f"{base}/models", headers={}, allow_local=True,
                total_timeout_s=self._local_timeout_s, connect_timeout_s=self._local_timeout_s,
            )  # fmt: skip
            models = filter_models(parse_models(result.body), "chat") if result.status == 200 else None
        except ProviderError:
            models = None
        if models is not None:
            found.update(
                running=True, models=[_public_model(m) for m in models], starter=starter_model([m.id for m in models])
            )
        return found

    async def discover_local(self) -> dict[str, Any]:
        apps = await asyncio.gather(*(self._look(*app) for app in self._local_apps))
        return {"apps": list(apps)}


# --- routes --------------------------------------------------------------------------------------------


def _status_for(exc: ProviderError) -> int:
    if exc.code == "secret_unavailable":
        return 503
    if exc.code == "origin_mismatch" or exc.reason in REQUEST_CAUSES:
        return 422
    return 502


async def _read_body(request: Request, model: type[BaseModel]) -> Any:
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_REQUEST_BYTES):
        raise HTTPException(status_code=413, detail="payload_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="payload_too_large")
        chunks.append(chunk)
    try:
        return model.model_validate_json(b"".join(chunks))
    except ValidationError:
        # The message quotes the rejected input; never return or log it.
        raise HTTPException(status_code=422, detail="invalid_request") from None


def build_router(
    get_store: Callable[[], Awaitable[SecretStore]],
    require_token: Callable[..., None],
    service: ProviderService | None = None,
) -> APIRouter:
    """Routes of this module; ``native_main`` passes its own store getter and management-token check."""
    svc = service or ProviderService()
    router = APIRouter(dependencies=[Depends(require_token)])

    @router.post("/v1/providers/probe")
    async def probe(request: Request) -> dict[str, Any]:
        body = cast(ProbeBody, await _read_body(request, ProbeBody))
        return await svc.probe(await get_store(), body)

    @router.post("/v1/providers/models", response_model=None)
    async def models(request: Request) -> dict[str, Any] | JSONResponse:
        body = cast(ModelsBody, await _read_body(request, ModelsBody))
        try:
            return await svc.models(await get_store(), body)
        except ProviderError as exc:
            logger.info("models ok=false class=%s cause=%s", exc.code, exc.reason)
            error = {"code": exc.code, "retryable": exc.retryable, "cause": exc.reason}
            return JSONResponse(status_code=_status_for(exc), content={"error": error})

    @router.get("/v1/discover/local")
    async def discover_local() -> dict[str, Any]:
        return await svc.discover_local()

    return router
