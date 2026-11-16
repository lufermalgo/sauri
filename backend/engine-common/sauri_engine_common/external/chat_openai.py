"""``openai-chat`` adapter: ``POST {base_url}/chat/completions`` in streaming mode, aggregated on demand.

Covers OpenAI, OpenRouter, Groq, Ollama, LM Studio and other OpenAI-compatible servers. Gemini's
OpenAI-compatible path is NOT claimed: it stays ``verified_on = None`` until it is tried with a real key (U10).
Provider kind and base URL come from the route; the key goes only in ``Authorization: Bearer``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from typing import Any, Final
from urllib.parse import urlsplit

from sauri_engine_common.external.chat_common import (
    ChatChunk,
    ChatUsage,
    bad_response,
    collect,
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
from sauri_engine_common.secrets import SecretRecord

# Request fields forwarded to the provider; ``model``, ``stream`` and ``provider`` are set here.
_FORWARDED: Final = (
    "messages",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stop",
    "seed",
    "response_format",
)


def is_openrouter(route: Route) -> bool:
    host = (urlsplit(route.base_url or "").hostname or "").lower()
    return route.kind == "openrouter" or host == "openrouter.ai" or host.endswith(".openrouter.ai")


def build_payload(request: dict[str, Any], route: Route) -> dict[str, Any]:
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ProviderError("provider_bad_request", reason="messages_missing")
    payload: dict[str, Any] = {name: request[name] for name in _FORWARDED if name in request}
    payload["model"] = route.model
    payload["stream"] = True
    payload["stream_options"] = {"include_usage": True}
    if is_openrouter(route):
        # Without this OpenRouter may route to an endpoint that silently ignores ``json_schema``.
        payload["provider"] = {"require_parameters": True}
    return payload


def _usage(raw: Any) -> ChatUsage | None:
    if not isinstance(raw, dict):
        return None
    prompt, completion = raw.get("prompt_tokens"), raw.get("completion_tokens")
    if isinstance(prompt, int) and isinstance(completion, int):
        return ChatUsage(prompt, completion)
    return None


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
    headers = {"authorization": f"Bearer {key}"} if key else {}
    finished = done = False
    async with aclosing(
        stream_events(
            http,
            join_url(route.base_url, "/chat/completions"),
            headers=headers,
            payload=build_payload(request, route),
            key=key,
            allow_local=allow_local,
            timeouts=timeouts or route.timeouts,
        )
    ) as events:
        async for event in events:
            if event.data.strip() == "[DONE]":
                done = True
                break
            data = parse_event_json(event)
            if "error" in data:
                raise error_from_stream_error(data["error"], key)
            choices = data.get("choices")
            if not isinstance(choices, list):
                raise bad_response()
            delta, finish = "", None
            if choices:
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise bad_response()
                content = (choice.get("delta") or {}).get("content")
                if isinstance(content, str):
                    delta = content
                if (choice.get("delta") or {}).get("refusal"):
                    raise ProviderError("provider_invalid_output", reason="refused")
                finish = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
            finished = finished or finish is not None
            model = data.get("model")
            ident = data.get("id")
            yield ChatChunk(
                delta=delta,
                finish_reason=finish,
                usage=_usage(data.get("usage")),
                id=ident if isinstance(ident, str) else None,
                model=model if isinstance(model, str) else None,
            )
    if not (done or finished):
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
    """The whole answer as an OpenAI ``chat.completion`` (with ``usage`` when the provider reports it)."""
    chunks = stream_chat(request, route=route, secret=secret, http=http, allow_local=allow_local, timeouts=timeouts)
    return await collect(chunks, model=route.model, structured=is_structured(request), validate_output=validate_output)
