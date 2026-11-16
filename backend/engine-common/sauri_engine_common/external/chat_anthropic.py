"""``anthropic-messages`` adapter: ``POST {base_url}/v1/messages`` in streaming mode, aggregated on demand.

Checked against the Anthropic API docs on 2026-11-16:

- ``anthropic-version: 2026-10-21`` (platform.claude.com/docs/en/api/versioning). That version removes
  ``temperature``, ``top_p`` and ``top_k`` (a request that sends them gets ``400``), so they are never sent.
- Structured output is ``output_config.format = {"type": "json_schema", "schema": ...}`` with no beta header
  (platform.claude.com/docs/en/build-with-claude/structured-outputs). The schema is adapted by ``schema.py``;
  the answer must be validated by the caller against the ORIGINAL schema (``validate_output``).
- The key goes in ``x-api-key`` (the API accepts it as well as ``Authorization: Bearer``).
- Streaming events: ``message_start`` (input tokens), ``content_block_delta`` with ``text_delta``,
  ``message_delta`` (``stop_reason`` and cumulative ``output_tokens``), ``message_stop``, ``ping``, ``error``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from typing import Any, Final

from sauri_engine_common.external.chat_common import (
    ChatChunk,
    ChatUsage,
    bad_response,
    collect,
    error_from_stream_error,
    is_structured,
    parse_event_json,
    stream_cut,
    stream_events,
)
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.safe_http import SafeHttp
from sauri_engine_common.external.schema import AdaptedSchema, adapt_schema_for
from sauri_engine_common.route import Route, RouteTimeouts
from sauri_engine_common.secrets import SecretRecord

ANTHROPIC_VERSION: Final = "2026-10-21"
DEFAULT_MAX_TOKENS: Final = 16384  # ``max_tokens`` is required by the API
_STOP_REASONS: Final = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
}


def messages_url(base_url: str) -> str:
    base = base_url.rstrip("/").removesuffix("/v1")
    return f"{base}/v1/messages"


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(
        isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str) for part in content
    ):
        return "".join(part["text"] for part in content)
    raise ProviderError("provider_bad_request", reason="content_unsupported")


def build_payload(request: dict[str, Any], route: Route) -> tuple[dict[str, Any], AdaptedSchema | None]:
    """The Messages API body and, for structured requests, the schema adaptation record."""
    raw = request.get("messages")
    if not isinstance(raw, list) or not raw:
        raise ProviderError("provider_bad_request", reason="messages_missing")
    system: list[str] = []
    messages: list[dict[str, str]] = []
    for message in raw:
        role = message.get("role") if isinstance(message, dict) else None
        if role in ("system", "developer"):
            system.append(_text_of(message.get("content")))
        elif role in ("user", "assistant"):
            messages.append({"role": role, "content": _text_of(message.get("content"))})
        else:
            raise ProviderError("provider_bad_request", reason="role_unsupported")
    max_tokens = request.get("max_tokens", request.get("max_completion_tokens", DEFAULT_MAX_TOKENS))
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
        raise ProviderError("provider_bad_request", reason="max_tokens_invalid")
    payload: dict[str, Any] = {"model": route.model, "max_tokens": max_tokens, "messages": messages, "stream": True}
    if system:
        payload["system"] = "\n\n".join(system)
    stop = request.get("stop")
    if isinstance(stop, str):
        payload["stop_sequences"] = [stop]
    elif isinstance(stop, list):
        payload["stop_sequences"] = stop
    adapted: AdaptedSchema | None = None
    response_format = request.get("response_format")
    if response_format is not None:
        schema = (response_format.get("json_schema") or {}).get("schema") if isinstance(response_format, dict) else None
        if not is_structured(request) or not isinstance(schema, dict):
            raise ProviderError("provider_bad_request", reason="response_format_unsupported")
        adapted = adapt_schema_for("anthropic-messages", schema)
        payload["output_config"] = {"format": {"type": "json_schema", "schema": adapted.schema}}
    return payload, adapted


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


async def stream_chat(
    request: dict[str, Any],
    *,
    route: Route,
    secret: SecretRecord | None,
    http: SafeHttp,
    allow_local: bool = False,
    timeouts: RouteTimeouts | None = None,
) -> AsyncGenerator[ChatChunk, None]:
    """Yield the answer as it arrives. Closing the iterator closes the upstream connection."""
    if route.base_url is None:
        raise ProviderError("provider_bad_request", reason="base_url_missing")
    key = secret.key if secret is not None else None
    headers = {"anthropic-version": ANTHROPIC_VERSION}
    if key:
        headers["x-api-key"] = key
    payload, _adapted = build_payload(request, route)
    message_id: str | None = None
    model: str | None = None
    prompt_tokens = 0
    stopped = False
    async with aclosing(
        stream_events(
            http,
            messages_url(route.base_url),
            headers=headers,
            payload=payload,
            key=key,
            allow_local=allow_local,
            timeouts=timeouts or route.timeouts,
        )
    ) as events:
        async for event in events:
            data = parse_event_json(event)
            kind = data.get("type")
            if kind == "message_start":
                message = data.get("message")
                if not isinstance(message, dict):
                    raise bad_response()
                usage = _dict(message.get("usage"))
                prompt_tokens = sum(
                    _count(usage.get(name))
                    for name in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                )
                ident, answered_by = message.get("id"), message.get("model")
                message_id = ident if isinstance(ident, str) else None
                model = answered_by if isinstance(answered_by, str) else None
                yield ChatChunk(id=message_id, model=model)
            elif kind == "content_block_delta":
                delta = data.get("delta")
                if isinstance(delta, dict) and delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                    yield ChatChunk(delta=delta["text"])
            elif kind == "message_delta":
                delta = _dict(data.get("delta"))
                reason = delta.get("stop_reason")
                usage = _dict(data.get("usage"))
                yield ChatChunk(
                    finish_reason=_STOP_REASONS.get(reason, "stop") if isinstance(reason, str) else None,
                    usage=ChatUsage(prompt_tokens, _count(usage.get("output_tokens"))),
                )
            elif kind == "message_stop":
                stopped = True
                break
            elif kind == "error":
                raise error_from_stream_error(data.get("error"), key)
            # ping, content_block_start/stop and unknown event types are ignored on purpose
    if not stopped:
        raise stream_cut()


async def complete(
    request: dict[str, Any],
    *,
    route: Route,
    secret: SecretRecord | None,
    http: SafeHttp,
    allow_local: bool = False,
    timeouts: RouteTimeouts | None = None,
    validate_output: Callable[[Any], object] | None = None,
) -> dict[str, Any]:
    """The whole answer as an OpenAI ``chat.completion`` (with ``usage``).

    For structured requests ``validate_output`` must check the parsed JSON against the ORIGINAL schema and the
    citations; the schema sent to the provider is the adapted one (``build_payload`` returns the record).
    """
    chunks = stream_chat(request, route=route, secret=secret, http=http, allow_local=allow_local, timeouts=timeouts)
    return await collect(chunks, model=route.model, structured=is_structured(request), validate_output=validate_output)
