"""``chatgpt-responses`` adapter: the Responses API the ChatGPT plan serves for Codex, in streaming mode.

``POST {base_url}/responses`` with ``store: false`` and ``stream: true`` (the backend only streams), the system
prompt as ``instructions``, and the account's bearer token plus ``chatgpt-account-id`` and ``originator``
headers. Structured output is ``text.format = {"type": "json_schema", ...}``. This is not a documented path
(owner decision of 2026-11-16, see ``chatgpt_login.py``): whether the backend honors ``json_schema`` is NOT
VERIFIED until the live acceptance, and the caller validates the answer anyway (``validate_output``).

Sampling and length fields of the chat request (``temperature``, ``max_tokens``...) are not forwarded: the
backend rejects some of them for its models. Models come from ``GET {base_url}/models?client_version=...``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, Final, Protocol

from sauri_engine_common.chatgpt_login import CLIENT_VERSION, ChatGptCredentials, login_required
from sauri_engine_common.external.chat_common import (
    ChatChunk,
    ChatUsage,
    bad_response,
    collect,
    error_from_http,
    error_from_stream_error,
    is_structured,
    join_url,
    parse_event_json,
    stream_cut,
    stream_events,
)
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.safe_http import SafeHttp
from sauri_engine_common.route import Route, RouteTimeouts

DEFAULT_INSTRUCTIONS: Final = "You are a helpful assistant."
MODELS_TIMEOUT_S: Final = 15.0
MAX_MODELS: Final = 200
_INCOMPLETE_FINISH: Final = {"max_output_tokens": "length", "content_filter": "content_filter"}


class CredentialSource(Protocol):
    async def credentials(self) -> ChatGptCredentials: ...

    async def renew(self) -> ChatGptCredentials: ...


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str) for part in content
    ):
        return "".join(part["text"] for part in content)
    raise ProviderError("provider_bad_request", reason="content_unsupported")


def build_payload(request: dict[str, Any], route: Route) -> dict[str, Any]:
    raw = request.get("messages")
    if not isinstance(raw, list) or not raw:
        raise ProviderError("provider_bad_request", reason="messages_missing")
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for message in raw:
        role = message.get("role") if isinstance(message, dict) else None
        text = _text_of(message.get("content")) if role in ("system", "developer", "user", "assistant") else ""
        if role in ("system", "developer"):
            instructions.append(text)
        elif role in ("user", "assistant"):
            kind = "input_text" if role == "user" else "output_text"
            items.append({"type": "message", "role": role, "content": [{"type": kind, "text": text}]})
        else:
            raise ProviderError("provider_bad_request", reason="role_unsupported")
    payload: dict[str, Any] = {
        "model": route.model,
        "instructions": "\n\n".join(instructions) or DEFAULT_INSTRUCTIONS,
        "input": items,
        "store": False,
        "stream": True,
    }
    response_format = request.get("response_format")
    if response_format is not None:
        spec = _dict(_dict(response_format).get("json_schema"))
        schema = spec.get("schema")
        if not is_structured(request) or not isinstance(schema, dict):
            raise ProviderError("provider_bad_request", reason="response_format_unsupported")
        name = spec.get("name") if isinstance(spec.get("name"), str) else "result"
        payload["text"] = {
            "format": {"type": "json_schema", "name": name, "schema": schema, "strict": spec.get("strict") is True}
        }
    return payload


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _stream_failure(error: Any) -> ProviderError:
    """An error that arrived inside the stream, reduced to a class from its code (never its message)."""
    probe = " ".join(str(_dict(error).get(name, "")) for name in ("code", "type")).lower()
    synthetic: dict[str, Any] | None = None
    if "usage_limit" in probe or "quota" in probe:
        synthetic = {"code": 429, "type": "insufficient_quota"}
    elif "rate_limit" in probe:
        synthetic = {"code": 429, "type": "rate_limit_error"}
    elif "context_length" in probe or "context_window" in probe:
        synthetic = {"code": 400, "type": "context_length_exceeded"}
    elif "invalid_prompt" in probe or "invalid_request" in probe:
        synthetic = {"code": 400}
    return error_from_stream_error(synthetic if synthetic is not None else error, None)


def _message_text(item: Any) -> tuple[str, bool]:
    """(text, refused) of a finished output message item."""
    parts, refused = [], False
    for part in _dict(item).get("content") or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "refusal":
            refused = True
        elif isinstance(part.get("text"), str):
            parts.append(part["text"])
    return "".join(parts), refused


async def stream_chat(
    request: dict[str, Any],
    *,
    route: Route,
    credentials: ChatGptCredentials,
    http: SafeHttp,
    allow_local: bool = False,
    timeouts: RouteTimeouts | None = None,
) -> AsyncGenerator[ChatChunk, None]:
    """Yield the answer as it arrives. Closing the iterator closes the upstream connection."""
    if route.base_url is None:
        raise ProviderError("provider_bad_request", reason="base_url_missing")
    headers = {**credentials.headers(), "accept": "text/event-stream"}
    streamed = False
    whole, refused = "", False
    completed = False
    async with aclosing(
        stream_events(
            http,
            join_url(route.base_url, "/responses"),
            headers=headers,
            payload=build_payload(request, route),
            key=credentials.token,
            allow_local=allow_local,
            timeouts=timeouts or route.timeouts,
        )
    ) as events:
        async for event in events:
            data = parse_event_json(event)
            kind = data.get("type")
            if kind == "response.created":
                response = _dict(data.get("response"))
                ident, model = response.get("id"), response.get("model")
                yield ChatChunk(
                    id=ident if isinstance(ident, str) else None, model=model if isinstance(model, str) else None
                )
            elif kind == "response.output_text.delta":
                delta = data.get("delta")
                if isinstance(delta, str) and delta:
                    streamed = True
                    yield ChatChunk(delta=delta)
            elif kind == "response.output_item.done":
                item = _dict(data.get("item"))
                if item.get("type") == "message":
                    text, was_refused = _message_text(item)
                    whole += text
                    refused = refused or was_refused
            elif kind in ("response.completed", "response.incomplete"):
                response = _dict(data.get("response"))
                usage = _dict(response.get("usage"))
                finish = "stop"
                if kind == "response.incomplete" or response.get("status") == "incomplete":
                    reason = _dict(response.get("incomplete_details")).get("reason")
                    finish = _INCOMPLETE_FINISH.get(reason, "length") if isinstance(reason, str) else "length"
                if not streamed and whole:
                    yield ChatChunk(delta=whole)
                elif not streamed and refused:
                    raise ProviderError("provider_invalid_output", reason="refused")
                yield ChatChunk(
                    finish_reason=finish,
                    usage=ChatUsage(_count(usage.get("input_tokens")), _count(usage.get("output_tokens"))),
                )
                completed = True
                break
            elif kind in ("response.failed", "error"):
                error = _dict(data.get("response")).get("error") or data.get("error") or data
                raise _stream_failure(error)
            # every other event type (reasoning, item added, ping...) is ignored on purpose
    if not completed:
        raise stream_cut()


def _is_unauthorized(error: ProviderError) -> bool:
    return error.code == "provider_auth" and error.reason == "http_401"


async def complete(
    request: dict[str, Any],
    *,
    route: Route,
    login: CredentialSource,
    http: SafeHttp,
    allow_local: bool = False,
    timeouts: RouteTimeouts | None = None,
    validate_output: Callable[[Any], object] | None = None,
) -> dict[str, Any]:
    """The whole answer as an OpenAI ``chat.completion``.

    A 401 refreshes the token once and retries (the token can lapse before its own expiry says); a second 401
    means the account must sign in again (``provider_auth`` / ``login_required``).
    """

    async def once(credentials: ChatGptCredentials) -> dict[str, Any]:
        chunks = stream_chat(
            request, route=route, credentials=credentials, http=http, allow_local=allow_local, timeouts=timeouts
        )
        return await collect(
            chunks, model=route.model, structured=is_structured(request), validate_output=validate_output
        )

    try:
        return await once(await login.credentials())
    except ProviderError as error:
        if not _is_unauthorized(error):
            raise
    try:
        return await once(await login.renew())
    except ProviderError as error:
        if _is_unauthorized(error):
            raise login_required() from None
        raise


@dataclass(frozen=True)
class PlanModel:
    id: str
    name: str


def parse_models(body: bytes) -> list[PlanModel]:
    """Models the plan offers, in its own priority order; hidden ones are left out."""
    try:
        data = json.loads(body)
    except ValueError:
        raise bad_response() from None
    listed = data.get("models") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        raise bad_response()
    entries: list[tuple[float, int, PlanModel]] = []
    for index, entry in enumerate(listed):
        if not isinstance(entry, dict) or not isinstance(entry.get("slug"), str) or entry.get("visibility") == "hide":
            continue
        slug = entry["slug"]
        if not slug or len(slug) > 256 or any(ord(char) < 0x20 for char in slug):
            continue
        label = entry.get("display_name")
        name = label if isinstance(label, str) and label and len(label) <= 128 else slug
        priority = entry.get("priority")
        rank = float(priority) if isinstance(priority, int | float) and not isinstance(priority, bool) else 999.0
        entries.append((rank, index, PlanModel(slug, name)))
    seen: dict[str, PlanModel] = {}
    for _rank, _index, model in sorted(entries, key=lambda item: item[:2]):
        seen.setdefault(model.id, model)
    return list(seen.values())[:MAX_MODELS]


async def list_models(
    login: CredentialSource,
    http: SafeHttp,
    *,
    base_url: str,
    allow_local: bool = False,
    timeout_s: float = MODELS_TIMEOUT_S,
) -> list[PlanModel]:
    """``GET {base_url}/models?client_version=...`` with one refresh on a 401."""
    url = f"{join_url(base_url, '/models')}?client_version={CLIENT_VERSION}"
    credentials = await login.credentials()
    for attempt in (0, 1):
        result = await http.request(
            "GET",
            url,
            headers={**credentials.headers(), "accept": "application/json"},
            allow_local=allow_local,
            total_timeout_s=timeout_s,
        )
        if 200 <= result.status < 300:
            return parse_models(result.body)
        error = error_from_http(result.status, result.body, result.retry_after, credentials.token)
        if not _is_unauthorized(error):
            raise error
        if attempt == 1:
            raise login_required()
        credentials = await login.renew()
    raise login_required()  # unreachable: the loop returns or raises
