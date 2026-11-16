"""Chat adapters (``openai-chat`` and ``anthropic-messages``) against fake providers on 127.0.0.1.

The fake provider is a small asyncio HTTP server so a test can see when the client goes away (Property 12).
No real provider, key or network is involved.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from types import ModuleType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sauri_engine_common.external import chat_anthropic, chat_openai
from sauri_engine_common.external.chat_common import MAX_SSE_EVENT_BYTES, MAX_SSE_LINE_BYTES, SseParser
from sauri_engine_common.external.errors import ERROR_CODES, ProviderError
from sauri_engine_common.external.safe_http import SafeHttp
from sauri_engine_common.external.schema import (
    ANTHROPIC_FORMATS,
    AdaptedSchema,
    SchemaNotAdaptableError,
    adapt_schema_for,
)
from sauri_engine_common.route import Route, RouteTimeouts
from sauri_engine_common.secrets import SecretRecord

KEY = "sk-test-KEY-0123456789abcdef"
PASSAGES = {"p1", "p2", "p3"}
SUMMARY = {"title": "Weekly sync", "key_points": [{"text": "Ship it", "sources": [{"passage_id": "p1"}]}]}
FAST = RouteTimeouts(connect_s=2.0, first_byte_s=5.0, idle_s=5.0, total_s=20.0)


# --- fake provider ----------------------------------------------------------------------------------------


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.body)
        return result


Handler = Callable[[Seen, asyncio.StreamWriter], Awaitable[None]]


@dataclass
class FakeProvider:
    handler: Handler
    seen: list[Seen] = field(default_factory=list)
    open_streams: int = 0
    port: int = 0
    _server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode()
            lines = head.split("\r\n")
            method, path, _version = lines[0].split(" ")
            headers = {k.lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:] if line)}
            body = await reader.readexactly(int(headers.get("content-length", "0")))
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()
            return
        request = Seen(method, path, headers, body)
        self.seen.append(request)
        self.open_streams += 1
        work: asyncio.Task[None] = asyncio.ensure_future(self.handler(request, writer))
        eof = asyncio.create_task(reader.read(1))  # a client that closes its socket ends the "stream"
        try:
            await asyncio.wait({work, eof}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.open_streams -= 1
            work.cancel()
            eof.cancel()
            await asyncio.gather(work, eof, return_exceptions=True)
            writer.close()


def _phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Custom"


async def send_head(writer: asyncio.StreamWriter, status: int, headers: dict[str, str]) -> None:
    lines = [f"HTTP/1.1 {status} {_phrase(status)}", *(f"{k}: {v}" for k, v in headers.items())]
    writer.write(("\r\n".join([*lines, "Connection: close"]) + "\r\n\r\n").encode())
    await writer.drain()


async def send_json(
    writer: asyncio.StreamWriter, status: int, body: Any, headers: dict[str, str] | None = None
) -> None:
    payload = json.dumps(body).encode()
    await send_head(writer, status, {"Content-Type": "application/json", "Content-Length": str(len(payload)),
                                     **(headers or {})})  # fmt: skip
    writer.write(payload)
    await writer.drain()


async def send_sse(writer: asyncio.StreamWriter, events: list[str], *, delay_s: float = 0.0) -> None:
    await send_head(writer, 200, {"Content-Type": "text/event-stream"})
    for event in events:
        writer.write(event.encode())
        await writer.drain()
        if delay_s:
            await asyncio.sleep(delay_s)


def data(obj: Any, event: str | None = None) -> str:
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {obj if isinstance(obj, str) else json.dumps(obj)}\n\n"


# --- provider flavours: the same scenarios run against both adapters ------------------------------------------


@dataclass(frozen=True)
class Flavor:
    name: str
    module: ModuleType
    kind: str
    transport: str
    path: str
    base_suffix: str

    def events(
        self, parts: list[str], *, finish: str = "stop", usage: tuple[int, int] | None = (11, 7), complete: bool = True
    ) -> list[str]:
        raise NotImplementedError


class OpenAIFlavor(Flavor):
    def events(
        self, parts: list[str], *, finish: str = "stop", usage: tuple[int, int] | None = (11, 7), complete: bool = True
    ) -> list[str]:
        base = {"id": "chatcmpl-1", "model": "m-real"}
        out = [data({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})]
        out += [
            data({**base, "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]})
            for part in parts
        ]
        if complete:
            out.append(data({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}))
            if usage:
                out.append(
                    data({**base, "choices": [], "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]}})
                )
            out.append(data("[DONE]"))
        return out


class AnthropicFlavor(Flavor):
    def events(
        self, parts: list[str], *, finish: str = "stop", usage: tuple[int, int] | None = (11, 7), complete: bool = True
    ) -> list[str]:
        reason = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}[finish]
        start = {"id": "msg_1", "model": "m-real", "content": [], "usage": {"input_tokens": usage[0] if usage else 1}}
        out = [
            data({"type": "message_start", "message": start}, "message_start"),
            data({"type": "ping"}, "ping"),
            data({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ]
        out += [
            data({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": part}})
            for part in parts
        ]
        out.append(data({"type": "content_block_stop", "index": 0}))
        if complete:
            out.append(
                data(
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": reason},
                        "usage": {"output_tokens": usage[1] if usage else 1},
                    }
                )
            )
            out.append(data({"type": "message_stop"}))
        return out


OPENAI = OpenAIFlavor("openai", chat_openai, "openai", "openai-chat", "/v1/chat/completions", "/v1")
ANTHROPIC = AnthropicFlavor("anthropic", chat_anthropic, "anthropic", "anthropic-messages", "/v1/messages", "")
flavors = pytest.mark.parametrize("flavor", [OPENAI, ANTHROPIC], ids=lambda f: f.name)


@pytest.fixture
async def serve() -> AsyncIterator[Callable[[Handler], Awaitable[FakeProvider]]]:
    started: list[FakeProvider] = []

    async def make(handler: Handler) -> FakeProvider:
        fake = FakeProvider(handler)
        await fake.start()
        started.append(fake)
        return fake

    yield make
    for fake in started:
        await fake.close()


def replying(events: list[str], *, delay_s: float = 0.0) -> Handler:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_sse(writer, events, delay_s=delay_s)

    return handler


def failing(status: int, body: Any, headers: dict[str, str] | None = None) -> Handler:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_json(writer, status, body, headers)

    return handler


def route_for(flavor: Flavor, fake: FakeProvider, *, timeouts: RouteTimeouts = FAST, kind: str | None = None) -> Route:
    return Route(
        version=1,
        capability="summary",
        kind=kind or flavor.kind,
        transport=flavor.transport,  # type: ignore[arg-type]
        base_url=f"{fake.url}{flavor.base_suffix}",
        model="m-requested",
        secret_ref=None,
        consent_version=1,
        timeouts=timeouts,
    )


def chat_request(*, structured: bool = True) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": "ignored-by-the-adapter",
        "temperature": 0,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You summarize meetings."},
            {"role": "user", "content": "Transcript: p1 said ship it."},
        ],
    }
    if structured:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "summary", "strict": True, "schema": summary_schema()},
        }
    return request


def summary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 120},
            "key_points": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "sources": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {"passage_id": {"type": "string", "enum": sorted(PASSAGES)}},
                                "required": ["passage_id"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["text", "sources"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "key_points"],
        "additionalProperties": False,
    }


def validate_citations(summary: Any) -> None:
    """Same contract as ``app.summaries.passages.validate_citations``: every cited passage must exist."""
    for point in summary["key_points"]:
        for ref in point["sources"]:
            if ref["passage_id"] not in PASSAGES:
                raise ValueError("unknown passage")


def secret(fake: FakeProvider) -> SecretRecord:
    return SecretRecord(key=KEY, origin=fake.url)


async def run_complete(flavor: Flavor, fake: FakeProvider, **kwargs: Any) -> dict[str, Any]:
    timeouts = kwargs.pop("timeouts", FAST)
    request = kwargs.pop("request", None) or chat_request()
    result: dict[str, Any] = await flavor.module.complete(
        request,
        route=route_for(flavor, fake, timeouts=timeouts, kind=kwargs.pop("kind", None)),
        secret=secret(fake),
        http=SafeHttp(),
        allow_local=kwargs.pop("allow_local", True),
        timeouts=None,
        **kwargs,
    )
    return result


async def error_of(flavor: Flavor, fake: FakeProvider, **kwargs: Any) -> ProviderError:
    with pytest.raises(ProviderError) as caught:
        await run_complete(flavor, fake, **kwargs)
    assert caught.value.code in ERROR_CODES
    return caught.value


# --- valid responses --------------------------------------------------------------------------------------


@flavors
async def test_structured_answer_is_aggregated_into_the_openai_shape(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(replying(flavor.events([json.dumps(SUMMARY)[:20], json.dumps(SUMMARY)[20:]])))
    completion = await run_complete(flavor, fake, validate_output=validate_citations)
    assert completion["object"] == "chat.completion"
    assert completion["model"] == "m-real"
    choice = completion["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": json.dumps(SUMMARY)}
    assert choice["finish_reason"] == "stop"
    assert completion["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


@flavors
async def test_usage_is_omitted_when_the_provider_does_not_report_it(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(replying(flavor.events(["hello"], usage=None)))
    completion = await run_complete(flavor, fake, request=chat_request(structured=False))
    if flavor is OPENAI:
        assert "usage" not in completion
    assert completion["choices"][0]["message"]["content"] == "hello"


async def test_openai_request_shape_and_auth(serve: Callable[[Handler], Awaitable[FakeProvider]]) -> None:
    fake = await serve(replying(OPENAI.events([json.dumps(SUMMARY)])))
    await run_complete(OPENAI, fake)
    (seen,) = fake.seen
    body = seen.json()
    assert (seen.method, seen.path) == ("POST", "/v1/chat/completions")
    assert seen.headers["authorization"] == f"Bearer {KEY}"
    assert body["model"] == "m-requested"
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert body["temperature"] == 0
    assert body["response_format"] == chat_request()["response_format"]
    assert "provider" not in body


@pytest.mark.parametrize(("kind", "expected"), [("openrouter", True), ("openai", False)])
async def test_require_parameters_is_sent_to_openrouter_only(
    serve: Callable[[Handler], Awaitable[FakeProvider]], kind: str, expected: bool
) -> None:
    fake = await serve(replying(OPENAI.events([json.dumps(SUMMARY)])))
    await run_complete(OPENAI, fake, kind=kind)
    body = fake.seen[0].json()
    assert body.get("provider") == ({"require_parameters": True} if expected else None)


async def test_anthropic_request_shape_and_auth(serve: Callable[[Handler], Awaitable[FakeProvider]]) -> None:
    fake = await serve(replying(ANTHROPIC.events([json.dumps(SUMMARY)])))
    request = chat_request()
    request["messages"].insert(1, {"role": "developer", "content": [{"type": "text", "text": "Be brief."}]})
    await run_complete(ANTHROPIC, fake, request=request)
    (seen,) = fake.seen
    body = seen.json()
    assert (seen.method, seen.path) == ("POST", "/v1/messages")
    assert seen.headers["x-api-key"] == KEY
    assert seen.headers["anthropic-version"] == chat_anthropic.ANTHROPIC_VERSION == "2026-10-21"
    assert "authorization" not in seen.headers
    assert body["system"] == "You summarize meetings.\n\nBe brief."
    assert body["messages"] == [{"role": "user", "content": "Transcript: p1 said ship it."}]
    assert body["max_tokens"] == chat_anthropic.DEFAULT_MAX_TOKENS
    assert body["stream"] is True and body["model"] == "m-requested"
    # Removed by API version 2026-10-21: sending them is a 400.
    assert not {"temperature", "top_p", "top_k"} & body.keys()
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert not any(DROPPED & node.keys() for node in walk(schema))
    assert "response_format" not in body


async def test_anthropic_honours_max_tokens_and_rejects_unsupported_input() -> None:
    route = Route(1, "summary", "anthropic", "anthropic-messages", "http://127.0.0.1:1", "m", None, 1)
    payload, adapted = chat_anthropic.build_payload({**chat_request(), "max_tokens": 321, "stop": "END"}, route)
    assert payload["max_tokens"] == 321 and payload["stop_sequences"] == ["END"]
    assert adapted is not None and {r.keyword for r in adapted.removed} >= {"maxItems", "minItems", "maxLength"}
    bad_requests: list[dict[str, Any]] = [
        {"messages": [{"role": "tool", "content": "x"}]},
        {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]},
        {"messages": []},
        {"messages": [{"role": "user", "content": "x"}], "response_format": {"type": "json_object"}},
        {"messages": [{"role": "user", "content": "x"}], "max_tokens": 0},
    ]
    for bad in bad_requests:
        with pytest.raises(ProviderError) as caught:
            chat_anthropic.build_payload(bad, route)
        assert caught.value.code == "provider_bad_request"


# --- output validation (Property 13) --------------------------------------------------------------------------


@flavors
async def test_invalid_json_is_rejected(flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]) -> None:
    fake = await serve(replying(flavor.events(['{"title": "cut off', " here"])))
    error = await error_of(flavor, fake)
    assert (error.code, error.reason, error.retryable) == ("provider_invalid_output", "invalid_json", False)


@flavors
async def test_nonexistent_citation_ids_are_rejected_locally(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    invented = {**SUMMARY, "key_points": [{"text": "x", "sources": [{"passage_id": "p999"}]}]}
    fake = await serve(replying(flavor.events([json.dumps(invented)])))
    error = await error_of(flavor, fake, validate_output=validate_citations)
    assert (error.code, error.reason) == ("provider_invalid_output", "validation_failed")


@flavors
async def test_output_that_breaks_the_original_schema_is_rejected_after_adaptation(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    """The provider never sees ``maxItems``; the original limit is still enforced by the caller's validator."""
    too_many = {"title": "t", "key_points": [{"text": "x", "sources": [{"passage_id": "p1"}]}] * 13}
    original = summary_schema()

    def validate(parsed: Any) -> None:
        if len(parsed["key_points"]) > original["properties"]["key_points"]["maxItems"]:
            raise ValueError("too many key points")

    fake = await serve(replying(flavor.events([json.dumps(too_many)])))
    error = await error_of(flavor, fake, validate_output=validate)
    assert error.code == "provider_invalid_output"


@flavors
async def test_truncated_and_refused_structured_answers_are_classified(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    cut = await serve(replying(flavor.events(['{"title": "x'], finish="length")))
    error = await error_of(flavor, cut)
    assert (error.code, error.reason) == ("provider_context_exceeded", "output_truncated")
    refused = await serve(replying(flavor.events(["I cannot help with that"], finish="content_filter")))
    error = await error_of(flavor, refused)
    assert (error.code, error.reason) == ("provider_invalid_output", "refused")


async def test_openai_refusal_delta_is_a_refusal(serve: Callable[[Handler], Awaitable[FakeProvider]]) -> None:
    event = data({"choices": [{"index": 0, "delta": {"refusal": "no"}, "finish_reason": None}]})
    fake = await serve(replying([event]))
    assert (await error_of(OPENAI, fake)).reason == "refused"


# --- HTTP errors --------------------------------------------------------------------------------------------


@flavors
async def test_429_with_retry_after_is_rate_limited(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(failing(429, {"error": {"type": "rate_limit_error"}}, {"Retry-After": "7"}))
    error = await error_of(flavor, fake)
    assert (error.code, error.retry_after_s, error.retryable) == ("provider_rate_limited", 7, True)
    assert error.to_payload() == {"error": {"code": "provider_rate_limited", "retryable": True, "retry_after_s": 7}}


@pytest.mark.parametrize(
    ("status", "body", "code", "retryable"),
    [
        (500, {"error": {"type": "api_error"}}, "provider_unavailable", True),
        (503, {"error": {"code": "overloaded"}}, "provider_unavailable", True),
        (529, {"type": "error", "error": {"type": "overloaded_error"}}, "provider_unavailable", True),
        (401, {"error": {"code": "invalid_api_key"}}, "provider_auth", False),
        (403, {"error": {"type": "permission_error"}}, "provider_auth", False),
        (402, {"error": {"message": "insufficient credits"}}, "provider_quota", True),
        (429, {"error": {"code": "insufficient_quota"}}, "provider_quota", True),
        (
            400,
            {"error": {"type": "invalid_request_error", "message": "Your credit balance is too low"}},
            "provider_quota",
            True,
        ),  # fmt: skip
        (400, {"error": {"code": "context_length_exceeded"}}, "provider_context_exceeded", False),
        (
            400,
            {"error": {"type": "invalid_request_error", "message": "prompt is too long: 9 tokens > 8"}},
            "provider_context_exceeded",
            False,
        ),  # fmt: skip
        (413, {"error": {"type": "request_too_large"}}, "provider_context_exceeded", False),
        (400, {"error": {"code": "bad_param"}}, "provider_bad_request", False),
        (504, "<html>gateway timeout</html>", "provider_timeout", True),
    ],
)
@flavors
async def test_http_failures_map_to_the_closed_classes(
    flavor: Flavor,
    serve: Callable[[Handler], Awaitable[FakeProvider]],
    status: int,
    body: Any,
    code: str,
    retryable: bool,
) -> None:
    fake = await serve(failing(status, body))
    error = await error_of(flavor, fake)
    assert (error.code, error.retryable) == (code, retryable)
    assert error.reason == f"http_{status}"


@flavors
async def test_redirects_are_refused_and_not_followed(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    target = await serve(replying(flavor.events(["x"])))
    fake = await serve(failing(307, {}, {"Location": f"{target.url}{flavor.path}"}))
    error = await error_of(flavor, fake)
    assert (error.code, error.reason) == ("provider_bad_request", "redirect_refused")
    assert len(fake.seen) == 1 and target.seen == []


@flavors
async def test_loopback_is_refused_unless_the_route_is_a_declared_local_app(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(replying(flavor.events(["x"])))
    error = await error_of(flavor, fake, allow_local=False)
    assert (error.code, error.reason) == ("provider_bad_request", "address_not_allowed")
    assert fake.seen == []


# --- streams: cuts, silences, malformed events ------------------------------------------------------------------


@flavors
async def test_a_stream_that_ends_without_its_terminator_is_cut(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(replying(flavor.events(['{"title":'], complete=False)))
    error = await error_of(flavor, fake)
    assert (error.code, error.reason, error.retryable) == ("provider_unavailable", "stream_cut", True)


@flavors
async def test_a_connection_dropped_mid_body_is_cut(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_head(writer, 200, {"Content-Type": "text/event-stream", "Transfer-Encoding": "chunked"})
        event = flavor.events(["{"], complete=False)[0].encode()
        writer.write(f"{len(event):x}\r\n".encode() + event + b"\r\n")
        await writer.drain()
        writer.transport.abort()

    fake = await serve(handler)
    error = await error_of(flavor, fake)
    assert (error.code, error.reason) == ("provider_unavailable", "stream_cut")


@flavors
async def test_slow_first_byte_times_out(flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]) -> None:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(30)

    fake = await serve(handler)
    started = time.monotonic()
    error = await error_of(flavor, fake, timeouts=RouteTimeouts(2.0, 0.3, 5.0, 20.0))
    assert (error.code, error.reason, error.retryable) == ("provider_timeout", "first_byte", True)
    assert time.monotonic() - started < 2.0
    await asyncio.sleep(0.2)
    assert fake.open_streams == 0


@flavors
async def test_silence_between_events_times_out(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_sse(writer, flavor.events(["a"], complete=False))
        await asyncio.sleep(30)

    fake = await serve(handler)
    error = await error_of(flavor, fake, timeouts=RouteTimeouts(2.0, 5.0, 0.3, 20.0))
    assert (error.code, error.reason) == ("provider_timeout", "idle")


@flavors
async def test_total_time_is_bounded_even_when_events_keep_coming(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_head(writer, 200, {"Content-Type": "text/event-stream"})
        while True:
            writer.write(b": keep-alive\n\n")
            await writer.drain()
            await asyncio.sleep(0.05)

    fake = await serve(handler)
    error = await error_of(flavor, fake, timeouts=RouteTimeouts(2.0, 5.0, 5.0, 0.4))
    assert (error.code, error.reason) == ("provider_timeout", "total")


@flavors
async def test_an_answer_that_is_not_an_event_stream_is_a_bad_response(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(failing(200, {"hello": "world"}))
    error = await error_of(flavor, fake)
    assert (error.code, error.reason) == ("provider_invalid_output", "bad_response")


@flavors
async def test_an_event_that_is_not_json_is_a_bad_response(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(replying(["data: not json at all\n\n"]))
    error = await error_of(flavor, fake)
    assert (error.code, error.reason) == ("provider_invalid_output", "bad_response")


async def test_errors_inside_a_200_stream_are_classified(serve: Callable[[Handler], Awaitable[FakeProvider]]) -> None:
    overloaded = await serve(
        replying([data({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, "error")])
    )
    error = await error_of(ANTHROPIC, overloaded)
    assert (error.code, error.reason) == ("provider_unavailable", "stream_error_529")
    rate_limited = await serve(replying([data({"error": {"code": 429, "message": "slow down"}})]))
    error = await error_of(OPENAI, rate_limited)
    assert (error.code, error.reason) == ("provider_rate_limited", "stream_error_429")


def test_sse_parser_handles_crlf_split_chunks_comments_and_multiline_data() -> None:
    parser = SseParser()
    events = parser.feed(b": hi\r\nevent: a\r\ndata: one\r")
    events += parser.feed(b"\ndata: two\r\n\r\ndata: x\n")
    events += parser.feed(b"\n")
    assert [(e.event, e.data) for e in events] == [("a", "one\ntwo"), (None, "x")]


def test_sse_parser_bounds_lines_and_events() -> None:
    with pytest.raises(ProviderError) as caught:
        SseParser().feed(b"data: " + b"a" * (MAX_SSE_LINE_BYTES + 1))
    assert caught.value.reason == "sse_line_too_large"
    parser = SseParser()
    line = b"data: " + b"a" * (MAX_SSE_LINE_BYTES // 2) + b"\n"
    with pytest.raises(ProviderError) as caught:
        for _ in range(MAX_SSE_EVENT_BYTES // len(line) + 2):
            parser.feed(line)
    assert caught.value.reason == "sse_event_too_large"


# --- cancellation (Property 12) ---------------------------------------------------------------------------------


async def hang_after_first_event(flavor: Flavor) -> Handler:
    async def handler(_seen: Seen, writer: asyncio.StreamWriter) -> None:
        await send_sse(writer, flavor.events(["partial"], complete=False))
        await asyncio.sleep(60)

    return handler


async def hang_before_any_byte(_seen: Seen, _writer: asyncio.StreamWriter) -> None:
    await asyncio.sleep(60)


async def wait_until(condition: Callable[[], bool], *, limit_s: float) -> float:
    started = time.monotonic()
    while not condition():
        assert time.monotonic() - started < limit_s, "condition not reached in time"
        await asyncio.sleep(0.01)
    return time.monotonic() - started


@pytest.mark.parametrize("phase", ["before_first_byte", "mid_stream"])
@flavors
async def test_cancelling_the_caller_closes_the_upstream_connection_within_two_seconds(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]], phase: str
) -> None:
    fake = await serve(hang_before_any_byte if phase == "before_first_byte" else await hang_after_first_event(flavor))
    task = asyncio.create_task(run_complete(flavor, fake))
    await wait_until(lambda: fake.open_streams == 1, limit_s=2.0)
    await asyncio.sleep(0.2)
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await wait_until(lambda: fake.open_streams == 0, limit_s=2.0)
    assert time.monotonic() - started <= 2.0


@flavors
async def test_closing_the_iterator_closes_the_upstream_connection(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(await hang_after_first_event(flavor))
    chunks = flavor.module.stream_chat(
        chat_request(), route=route_for(flavor, fake), secret=secret(fake), http=SafeHttp(), allow_local=True
    )
    pieces: list[str] = []
    async for chunk in chunks:
        pieces.append(chunk.delta)
        if "partial" in pieces:
            break
    assert fake.open_streams == 1
    started = time.monotonic()
    await chunks.aclose()
    await wait_until(lambda: fake.open_streams == 0, limit_s=2.0)
    assert time.monotonic() - started <= 2.0


# --- secrets stay out of errors and logs (Property 4) -------------------------------------------------------------


@flavors
async def test_the_key_never_reaches_logs_exceptions_or_payloads(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]], caplog: pytest.LogCaptureFixture
) -> None:
    echo = {"error": {"message": f"Incorrect API key provided: {KEY}", "type": "invalid_request_error",
                      "code": f"bad_{KEY}"}}  # fmt: skip
    in_stream = data({"type": "error", "error": {"type": "api_error", "message": f"boom {KEY}", "code": KEY}}, "error")
    scenarios = [
        failing(401, echo),
        failing(400, echo),
        failing(429, echo, {"Retry-After": "3"}),
        replying([in_stream]),
        replying(flavor.events([f"the model repeats {KEY}"])),
    ]
    caplog.set_level(logging.DEBUG)
    outputs: list[str] = []
    for handler in scenarios:
        fake = await serve(handler)
        try:
            completion = await run_complete(flavor, fake, request=chat_request(structured=False))
            outputs.append(json.dumps(completion))
        except ProviderError as exc:
            chain: list[BaseException | None] = [exc, exc.__cause__, exc.__context__]
            outputs += [f"{item!s} {item!r}" for item in chain if item is not None]
            outputs += ["".join(traceback.format_exception(exc)), json.dumps(exc.to_payload()), str(exc.reason)]
    outputs.append(caplog.text)
    # The one place text from the provider is allowed to appear is the successful completion itself.
    assert all(KEY not in text for text in outputs[:-1] if "the model repeats" not in text)
    assert KEY not in caplog.text and "Bearer" not in caplog.text and "x-api-key" not in caplog.text.lower()


# --- schema adaptation (Property 13) ------------------------------------------------------------------------------

DROPPED = {
    "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "maxItems", "uniqueItems", "minContains", "maxContains", "minProperties", "maxProperties",
}  # fmt: skip


def walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += walk(value)
    elif isinstance(node, list):
        for value in node:
            found += walk(value)
    return found


def test_summary_schema_is_adapted_and_the_record_says_what_was_removed() -> None:
    original = summary_schema()
    adapted = adapt_schema_for("anthropic-messages", original)
    assert original == summary_schema()  # the caller's schema is never mutated
    removed = {(r.path, r.keyword, repr(r.value)) for r in adapted.removed}
    assert ("/properties/title", "maxLength", "120") in removed
    assert ("/properties/key_points", "maxItems", "12") in removed
    assert ("/properties/key_points/items/properties/text", "minLength", "1") in removed
    sources = "/properties/key_points/items/properties/sources"
    assert {(sources, "minItems", "2"), (sources, "maxItems", "4")} <= removed
    sent = adapted.schema
    assert not any(DROPPED & node.keys() for node in walk(sent))
    points = sent["properties"]["key_points"]
    assert "maxItems=12" in points["description"]  # the model still sees the dropped limit
    # What the provider must keep to constrain the output.
    enum = points["items"]["properties"]["sources"]["items"]["properties"]["passage_id"]["enum"]
    assert enum == sorted(PASSAGES) and sent["required"] == ["title", "key_points"]


def test_minitems_zero_or_one_formats_and_patterns_follow_the_documented_rules() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "array", "minItems": 1, "items": {"type": "string", "format": "email"}},
            "b": {"type": "array", "minItems": 0, "items": {"type": "string", "format": "iban"}},
            "c": {"type": "string", "pattern": "^(?=a)b$"},
            "d": {"type": "string", "pattern": "^[a-z]{1,3}$"},
            "e": {"type": "integer", "minimum": 1, "maximum": 9},
        },
        "required": ["a", "b", "c", "d", "e"],
    }
    adapted = adapt_schema_for("anthropic-messages", schema)
    props = adapted.schema["properties"]
    assert props["a"]["minItems"] == 1 and props["a"]["items"]["format"] in ANTHROPIC_FORMATS
    assert props["b"]["minItems"] == 0 and "format" not in props["b"]["items"]
    assert "pattern" not in props["c"] and props["d"]["pattern"] == "^[a-z]{1,3}$"
    assert "minimum" not in props["e"] and adapted.schema["additionalProperties"] is False
    assert ("", "additionalProperties", True) in {(r.path, r.keyword, r.value) for r in adapted.removed}


def test_openai_transport_takes_the_strict_schema_unchanged() -> None:
    original = summary_schema()
    adapted = adapt_schema_for("openai-chat", original)
    assert adapted == AdaptedSchema(original, ())
    assert adapted.schema is not original


@pytest.mark.parametrize(
    ("schema", "reason"),
    [
        ({"type": "object", "properties": {"a": {"$ref": "https://example.com/x.json"}}}, "schema_external_ref"),
        (
            {"type": "object", "properties": {"a": {"allOf": [{"$ref": "#/$defs/x"}]}}, "$defs": {"x": {}}},
            "schema_allof_ref",
        ),  # fmt: skip
        (
            {
                "type": "object",
                "properties": {"n": {"$ref": "#/$defs/node"}},
                "$defs": {"node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/node"}}}},
            },
            "schema_recursive",
        ),  # fmt: skip
        (
            {
                "type": "object",
                "properties": {"n": {"$ref": "#/$defs/a"}},
                "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}},
            },
            "schema_recursive",
        ),  # fmt: skip
    ],
)
def test_schemas_that_no_removal_can_fix_are_rejected(schema: dict[str, Any], reason: str) -> None:
    with pytest.raises(SchemaNotAdaptableError) as caught:
        adapt_schema_for("anthropic-messages", schema)
    assert (caught.value.code, caught.value.reason) == ("provider_bad_request", reason)


_leaf = st.fixed_dictionaries(
    {"type": st.sampled_from(["string", "integer", "number", "boolean"])},
    optional={
        "minLength": st.integers(0, 5),
        "maxLength": st.integers(1, 500),
        "minimum": st.integers(-5, 5),
        "maximum": st.integers(5, 50),
        "multipleOf": st.integers(1, 3),
        "format": st.sampled_from(["email", "iban", "uuid", "regex"]),
        "pattern": st.sampled_from(["^a+$", "(?!x)a", "\\1", "\\bword\\b"]),
        "enum": st.lists(st.sampled_from(["a", "b", 1, None]), min_size=1, max_size=3),
    },
)
_schemas = st.recursive(
    _leaf,
    lambda children: st.one_of(
        st.fixed_dictionaries(
            {"type": st.just("array"), "items": children},
            optional={"minItems": st.integers(0, 4), "maxItems": st.integers(1, 20), "uniqueItems": st.booleans()},
        ),
        st.fixed_dictionaries(
            {"type": st.just("object"), "properties": st.dictionaries(st.sampled_from("abcd"), children, max_size=3)},
            optional={"additionalProperties": st.booleans(), "minProperties": st.integers(0, 2)},
        ),
        st.fixed_dictionaries({"anyOf": st.lists(children, min_size=1, max_size=2)}),
    ),
    max_leaves=12,
)


@settings(max_examples=150, deadline=None)
@given(_schemas)
def test_adapted_schemas_never_carry_what_the_provider_rejects(schema: dict[str, Any]) -> None:
    before = copy.deepcopy(schema)
    adapted = adapt_schema_for("anthropic-messages", schema)
    assert schema == before
    for node in walk(adapted.schema):
        assert not DROPPED & node.keys()
        assert node.get("minItems", 0) in (0, 1)
        if node.get("type") == "object" or "properties" in node:
            assert node["additionalProperties"] is False
        if node.get("type") == "string" and "format" in node:
            assert node["format"] in ANTHROPIC_FORMATS
        assert all(not isinstance(v, dict | list) for v in node.get("enum", []))
    assert all(r.keyword in DROPPED | {"minItems", "format", "pattern", "enum", "additionalProperties"}
               for r in adapted.removed)  # fmt: skip


@flavors
async def test_a_local_app_without_a_key_gets_no_credentials_header(
    flavor: Flavor, serve: Callable[[Handler], Awaitable[FakeProvider]]
) -> None:
    fake = await serve(replying(flavor.events(["hello"])))
    completion = await flavor.module.complete(
        chat_request(structured=False),
        route=route_for(flavor, fake),
        secret=None,
        http=SafeHttp(),
        allow_local=True,
    )
    assert completion["choices"][0]["message"]["content"] == "hello"
    assert not {"authorization", "x-api-key"} & fake.seen[0].headers.keys()
