"""Pieces shared by the chat adapters: bounded SSE reading, timeouts, error mapping and aggregation.

Nothing here returns or logs a key, a header, a provider body or generated text in an error: every failure is a
``ProviderError`` with a closed class and a short ``reason`` code.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, aclosing
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from sauri_engine_common.external.errors import ProviderError, classify
from sauri_engine_common.external.safe_http import HttpStream, SafeHttp
from sauri_engine_common.route import RouteTimeouts

_T = TypeVar("_T")

MAX_SSE_LINE_BYTES: Final = 256 * 1024
MAX_SSE_EVENT_BYTES: Final = 1024 * 1024
MAX_CONTENT_CHARS: Final = 4 * 1024 * 1024
MAX_ERROR_BODY_BYTES: Final = 64 * 1024

_EOL: Final = re.compile(rb"\r\n|\n|\r")
_HINT: Final = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_CONTEXT_PHRASES: Final = (
    "prompt is too long",
    "maximum context length",
    "context_length_exceeded",
    "exceed_context_size",
    "exceeds the available context",
    "context window",
)
_QUOTA_HINTS: Final = ("insufficient_quota", "billing", "credit_balance", "quota_exceeded")
_STREAM_ERROR_STATUS: Final = {
    "overloaded_error": 529,
    "api_error": 500,
    "rate_limit_error": 429,
    "authentication_error": 401,
    "permission_error": 403,
    "billing_error": 402,
    "invalid_request_error": 400,
    "not_found_error": 404,
    "request_too_large": 413,
    "timeout_error": 504,
}


@dataclass(frozen=True)
class ChatUsage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class ChatChunk:
    """One increment of a chat answer; usage and finish reason arrive on the last chunks."""

    delta: str = ""
    finish_reason: str | None = None  # OpenAI vocabulary: stop, length, content_filter, tool_calls
    usage: ChatUsage | None = None
    id: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class SseEvent:
    event: str | None
    data: str


class SseParser:
    """Incremental server-sent-events reader with a bound on line and event size."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._event: str | None = None
        self._data: list[str] = []
        self._data_bytes = 0

    def feed(self, chunk: bytes) -> list[SseEvent]:
        self._buffer += chunk
        events: list[SseEvent] = []
        while True:
            match = _EOL.search(self._buffer)
            # A lone "\r" at the end may be the first half of "\r\n": wait for more bytes.
            if match is None or (match.group() == b"\r" and match.end() == len(self._buffer)):
                break
            line = bytes(self._buffer[: match.start()])
            del self._buffer[: match.end()]
            self._line(line, events)
        if len(self._buffer) > MAX_SSE_LINE_BYTES:
            raise ProviderError("provider_invalid_output", reason="sse_line_too_large")
        return events

    def _line(self, raw: bytes, events: list[SseEvent]) -> None:
        if len(raw) > MAX_SSE_LINE_BYTES:
            raise ProviderError("provider_invalid_output", reason="sse_line_too_large")
        if not raw:
            if self._data:
                events.append(SseEvent(self._event, "\n".join(self._data)))
            self._event, self._data, self._data_bytes = None, [], 0
            return
        if raw.startswith(b":"):
            return  # comment or keep-alive
        name, _, value = raw.decode("utf-8", errors="replace").partition(":")
        value = value.removeprefix(" ")
        if name == "data":
            self._data_bytes += len(value) + 1
            if self._data_bytes > MAX_SSE_EVENT_BYTES:
                raise ProviderError("provider_invalid_output", reason="sse_event_too_large")
            self._data.append(value)
        elif name == "event":
            self._event = value


# --- errors -------------------------------------------------------------------------------------------


def error_hint(body: bytes, key: str | None) -> str | None:
    """A provider error code such as ``invalid_api_key``; never free text, never anything containing the key."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    error = data.get("error") if isinstance(data, dict) else None
    return _hint_from(error, key)


def _hint_from(error: Any, key: str | None) -> str | None:
    candidates: list[Any] = []
    message = ""
    if isinstance(error, dict):
        candidates += [error.get("code"), error.get("type"), error.get("status")]
        if isinstance(error.get("message"), str):
            message = error["message"].lower()
    elif isinstance(error, str):
        candidates.append(error)
    # Free text is only ever matched against known phrases; it is never copied into the hint.
    if any(phrase in message for phrase in _CONTEXT_PHRASES):
        return "context_length_exceeded"
    if "credit balance" in message:
        return "credit_balance"
    for candidate in candidates:
        if isinstance(candidate, str) and _HINT.fullmatch(candidate):
            if key and key.lower() in candidate.lower():
                return None
            return candidate.lower()
    return None


def error_from_http(status: int, body: bytes, retry_after: str | None, key: str | None) -> ProviderError:
    hint = error_hint(body, key)
    base = classify(status, hint, retry_after=retry_after)
    reason = "redirect_refused" if 300 <= status < 400 else f"http_{status}"
    if status == 413:  # classify() reads 413 as an oversized audio upload; for chat it is the prompt
        return ProviderError("provider_context_exceeded", reason=reason)
    if status == 400 and hint is not None and any(marker in hint for marker in _QUOTA_HINTS):
        return ProviderError("provider_quota", reason=reason)
    return ProviderError(base.code, retry_after_s=base.retry_after_s, reason=reason)


def error_from_stream_error(error: Any, key: str | None) -> ProviderError:
    """An error object that arrived inside a 200 stream (Anthropic ``error`` event, OpenRouter ``error`` chunk)."""
    status: int | None = None
    if isinstance(error, dict):
        code = error.get("code")
        if isinstance(code, int) and not isinstance(code, bool):
            status = code
        else:
            for name in (error.get("type"), code):
                if isinstance(name, str) and name in _STREAM_ERROR_STATUS:
                    status = _STREAM_ERROR_STATUS[name]
                    break
    base = classify(status, _hint_from(error, key))
    reason = f"stream_error_{status}" if status is not None else "stream_error"
    return ProviderError(base.code, retry_after_s=base.retry_after_s, reason=reason)


def bad_response() -> ProviderError:
    return ProviderError("provider_invalid_output", reason="bad_response")


def stream_cut() -> ProviderError:
    return ProviderError("provider_unavailable", reason="stream_cut")


def parse_event_json(event: SseEvent) -> dict[str, Any]:
    try:
        data = json.loads(event.data)
    except ValueError:
        raise bad_response() from None
    if not isinstance(data, dict):
        raise bad_response()
    return data


# --- bounded streaming -----------------------------------------------------------------------------------


async def _within(make: Callable[[], Awaitable[_T]], *, limit_s: float, deadline: float, phase: str) -> _T:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise ProviderError("provider_timeout", reason="total")
    try:
        async with asyncio.timeout(min(limit_s, remaining)):
            return await make()
    except TimeoutError:
        raise ProviderError("provider_timeout", reason="total" if remaining <= limit_s else phase) from None


async def stream_events(
    http: SafeHttp,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    key: str | None,
    allow_local: bool,
    timeouts: RouteTimeouts,
) -> AsyncGenerator[SseEvent, None]:
    """POST ``payload`` and yield server-sent events until the provider closes the stream.

    ``first_byte_s`` bounds the wait for the first body byte, ``idle_s`` the silence between later chunks and
    ``total_s`` the whole call. Closing this iterator, or cancelling the task that reads it, closes the
    upstream connection.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeouts.total_s
    first_deadline = loop.time() + timeouts.first_byte_s
    send_headers = {**headers, "content-type": "application/json", "accept": "text/event-stream"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    async with AsyncExitStack() as stack:
        response: HttpStream = await _within(
            lambda: stack.enter_async_context(
                http.open_stream(
                    "POST",
                    url,
                    headers=send_headers,
                    body=body,
                    allow_local=allow_local,
                    read_timeout_s=max(timeouts.first_byte_s, timeouts.idle_s),
                    connect_timeout_s=timeouts.connect_s,
                )
            ),
            limit_s=timeouts.first_byte_s,
            deadline=deadline,
            phase="first_byte",
        )
        if not 200 <= response.status < 300:
            error_body = await _within(
                lambda: response.read_capped(MAX_ERROR_BODY_BYTES),
                limit_s=timeouts.idle_s,
                deadline=deadline,
                phase="idle",
            )
            raise error_from_http(response.status, error_body, response.retry_after, key)
        if response.content_type != "text/event-stream":
            raise bad_response()
        parser = SseParser()
        first = True
        async with aclosing(response.iter_bytes()) as chunks:
            while True:
                limit = max(first_deadline - loop.time(), 0.001) if first else timeouts.idle_s
                try:
                    chunk = await _within(
                        chunks.__anext__, limit_s=limit, deadline=deadline, phase="first_byte" if first else "idle"
                    )
                except StopAsyncIteration:
                    return
                first = False
                for event in parser.feed(chunk):
                    yield event


# --- aggregation ---------------------------------------------------------------------------------------


def is_structured(request: dict[str, Any]) -> bool:
    response_format = request.get("response_format")
    return isinstance(response_format, dict) and response_format.get("type") == "json_schema"


def join_url(base: str, suffix: str) -> str:
    return base.rstrip("/") + suffix


async def collect(
    chunks: AsyncGenerator[ChatChunk, None],
    *,
    model: str,
    structured: bool,
    validate_output: Callable[[Any], object] | None,
) -> dict[str, Any]:
    """Accumulate chunks into an OpenAI ``chat.completion`` and, for structured requests, check the output.

    ``validate_output`` receives the parsed JSON and must raise when it breaks the ORIGINAL schema or cites
    something that does not exist; any exception becomes ``provider_invalid_output`` (Property 13).
    """
    parts: list[str] = []
    size = 0
    finish_reason: str | None = None
    usage: ChatUsage | None = None
    completion_id: str | None = None
    answered_by = model
    async with aclosing(chunks):
        async for chunk in chunks:
            size += len(chunk.delta)
            if size > MAX_CONTENT_CHARS:
                raise ProviderError("provider_invalid_output", reason="response_too_large")
            parts.append(chunk.delta)
            finish_reason = chunk.finish_reason or finish_reason
            usage = chunk.usage or usage
            completion_id = chunk.id or completion_id
            answered_by = chunk.model or answered_by
    text = "".join(parts)
    if structured:
        _check_structured(text, finish_reason, validate_output)
    completion: dict[str, Any] = {
        "id": completion_id or "chatcmpl-external",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": answered_by,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason or "stop",
            }
        ],
    }
    if usage is not None:
        completion["usage"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }
    return completion


def _check_structured(text: str, finish_reason: str | None, validate_output: Callable[[Any], object] | None) -> None:
    if finish_reason == "length":
        raise ProviderError("provider_context_exceeded", reason="output_truncated")
    if finish_reason == "content_filter":
        raise ProviderError("provider_invalid_output", reason="refused")
    try:
        parsed = json.loads(text)
    except ValueError:
        raise ProviderError("provider_invalid_output", reason="invalid_json") from None
    if validate_output is None:
        return
    try:
        validate_output(parsed)
    except ProviderError:
        raise
    except Exception:
        raise ProviderError("provider_invalid_output", reason="validation_failed") from None
