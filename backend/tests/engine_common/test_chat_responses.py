"""``chatgpt-responses`` adapter against fake servers on 127.0.0.1 (no OpenAI, no token, no network)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from sauri_engine_common.chatgpt_login import ChatGptCredentials
from sauri_engine_common.external import chat_responses
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.external.safe_http import SafeHttp
from sauri_engine_common.route import Route, RouteTimeouts

from tests.llm_engine.external_support import FakeProvider, Handler, Seen, data, failing, replying

TOKEN_1, TOKEN_2 = "access-synthetic-1", "access-synthetic-2"
ACCOUNT = "acct-test-0001"
FAST = RouteTimeouts(connect_s=2.0, first_byte_s=5.0, idle_s=5.0, total_s=20.0)
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
REQUEST: dict[str, Any] = {
    "model": "ignored",
    "temperature": 0,
    "stream": False,
    "max_tokens": 99,
    "messages": [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Transcript: private meeting words"},
    ],
    "response_format": {"type": "json_schema", "json_schema": {"name": "summary", "strict": True, "schema": SCHEMA}},
}


class StubLogin:
    def __init__(self) -> None:
        self.renewed = 0
        self.dead = False

    async def credentials(self) -> ChatGptCredentials:
        return ChatGptCredentials(TOKEN_1, ACCOUNT)

    async def renew(self) -> ChatGptCredentials:
        if self.dead:
            raise ProviderError("provider_auth", reason="login_required")
        self.renewed += 1
        return ChatGptCredentials(TOKEN_2, ACCOUNT)


def events(parts: list[str], *, deltas: bool = True, status: str = "completed", reason: str | None = None) -> list[str]:
    out = [data({"type": "response.created", "response": {"id": "resp_1", "model": "gpt-real"}})]
    out.append(data({"type": "response.reasoning_summary_text.delta", "delta": "thinking"}))
    if deltas:
        out += [data({"type": "response.output_text.delta", "delta": part}) for part in parts]
    out.append(
        data(
            {
                "type": "response.output_item.done",
                "item": {"type": "message", "content": [{"type": "output_text", "text": "".join(parts)}]},
            }
        )
    )
    response: dict[str, Any] = {"status": status, "usage": {"input_tokens": 11, "output_tokens": 7}}
    if reason:
        response["incomplete_details"] = {"reason": reason}
    kind = "response.completed" if status == "completed" else "response.incomplete"
    return [*out, data({"type": kind, "response": response})]


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


def route(fake: FakeProvider) -> Route:
    return Route(
        version=1, capability="summary", kind="chatgpt_plan", transport="chatgpt-responses",
        base_url=f"{fake.url}/backend-api/codex", model="gpt-5-test", secret_ref=None, consent_version=1,
        timeouts=FAST,
    )  # fmt: skip


async def run(fake: FakeProvider, login: StubLogin | None = None, request: dict[str, Any] | None = None) -> Any:
    return await chat_responses.complete(
        request or REQUEST, route=route(fake), login=login or StubLogin(), http=SafeHttp(), allow_local=True
    )


async def test_the_answer_comes_back_in_the_chat_shape(serve: Any) -> None:
    fake = await serve(replying(events(['{"title": ', '"Weekly sync"}'])))
    result = await run(fake)
    assert json.loads(result["choices"][0]["message"]["content"]) == {"title": "Weekly sync"}
    assert result["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert (result["id"], result["model"], result["choices"][0]["finish_reason"]) == ("resp_1", "gpt-real", "stop")
    sent = fake.seen[0]
    assert sent.path == "/backend-api/codex/responses"
    assert sent.headers["authorization"] == f"Bearer {TOKEN_1}"
    assert sent.headers["chatgpt-account-id"] == ACCOUNT and sent.headers["originator"] == "sauri"
    body = sent.json()
    assert body["model"] == "gpt-5-test" and body["store"] is False and body["stream"] is True
    assert body["instructions"] == "Be brief."
    assert body["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Transcript: private meeting words"}],
        }
    ]
    assert body["text"] == {"format": {"type": "json_schema", "name": "summary", "schema": SCHEMA, "strict": True}}
    assert not {"temperature", "max_tokens", "max_output_tokens", "response_format", "messages"} & set(body)


async def test_a_message_that_arrives_only_whole_still_answers(serve: Any) -> None:
    fake = await serve(replying(events(['{"title": "Whole"}'], deltas=False)))
    result = await run(fake)
    assert json.loads(result["choices"][0]["message"]["content"]) == {"title": "Whole"}


async def test_default_instructions_when_the_request_has_no_system_prompt(serve: Any) -> None:
    fake = await serve(replying(events(['{"title": "x"}'])))
    await run(fake, request={**REQUEST, "messages": [{"role": "user", "content": "hi"}]})
    assert fake.seen[0].json()["instructions"] == chat_responses.DEFAULT_INSTRUCTIONS


async def test_an_incomplete_response_is_a_truncation_for_structured_output(serve: Any) -> None:
    fake = await serve(replying(events(['{"title": "cut'], status="incomplete", reason="max_output_tokens")))
    with pytest.raises(ProviderError) as caught:
        await run(fake)
    assert (caught.value.code, caught.value.reason) == ("provider_context_exceeded", "output_truncated")


async def test_a_refusal_is_invalid_output(serve: Any) -> None:
    refusal = [
        data(
            {
                "type": "response.output_item.done",
                "item": {"type": "message", "content": [{"type": "refusal", "refusal": "no"}]},
            }
        ),
        data({"type": "response.completed", "response": {"status": "completed"}}),
    ]
    fake = await serve(replying(refusal))
    with pytest.raises(ProviderError) as caught:
        await run(fake)
    assert (caught.value.code, caught.value.reason) == ("provider_invalid_output", "refused")


async def test_a_cut_stream_is_unavailable(serve: Any) -> None:
    fake = await serve(replying(events(["a"])[:3]))
    with pytest.raises(ProviderError) as caught:
        await run(fake)
    assert (caught.value.code, caught.value.reason) == ("provider_unavailable", "stream_cut")


def stream_error(error: dict[str, Any], *, wrapped: bool = True) -> list[str]:
    body = {"type": "response.failed", "response": {"error": error}} if wrapped else {"type": "error", **error}
    return [data(body)]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        ({"code": "usage_limit_reached", "message": "limit"}, "provider_quota"),
        ({"code": "rate_limit_exceeded"}, "provider_rate_limited"),
        ({"code": "context_length_exceeded"}, "provider_context_exceeded"),
        ({"code": "invalid_prompt"}, "provider_bad_request"),
        ({"code": "server_error"}, "provider_unavailable"),
    ],
)
async def test_errors_inside_the_stream_are_classified(serve: Any, error: dict[str, Any], code: str) -> None:
    fake = await serve(replying(stream_error(error)))
    with pytest.raises(ProviderError) as caught:
        await run(fake)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("status", "headers", "body", "code", "retry_after"),
    [
        (429, {"Retry-After": "17"}, {"error": {"type": "rate_limit_exceeded"}}, "provider_rate_limited", 17),
        (429, {}, {"error": {"type": "usage_limit_reached", "resets_in_seconds": 3600}}, "provider_quota", None),
        (403, {}, {"error": {"code": "forbidden"}}, "provider_auth", None),
        (400, {}, {"error": {"code": "unsupported_parameter"}}, "provider_bad_request", None),
        (503, {"Retry-After": "5"}, {}, "provider_unavailable", 5),
    ],
)
async def test_http_errors_are_mapped(
    serve: Any, status: int, headers: dict[str, str], body: dict[str, Any], code: str, retry_after: int | None
) -> None:
    fake = await serve(failing(status, body, headers))
    with pytest.raises(ProviderError) as caught:
        await run(fake)
    assert (caught.value.code, caught.value.retry_after_s) == (code, retry_after)
    assert caught.value.to_payload() == {
        "error": {"code": code, "retryable": caught.value.retryable, "retry_after_s": retry_after}
    }


async def test_a_401_refreshes_the_token_once_and_retries(serve: Any) -> None:
    async def handler(seen: Seen, writer: Any) -> None:
        if seen.headers["authorization"] == f"Bearer {TOKEN_1}":
            await failing(401, {"error": {"code": "token_expired"}})(seen, writer)
        else:
            await replying(events(['{"title": "ok"}']))(seen, writer)

    fake = await serve(handler)
    login = StubLogin()
    result = await run(fake, login)
    assert json.loads(result["choices"][0]["message"]["content"]) == {"title": "ok"}
    assert login.renewed == 1 and len(fake.seen) == 2


async def test_a_second_401_asks_for_a_new_sign_in(serve: Any) -> None:
    fake = await serve(failing(401, {"error": {"code": "token_expired"}}))
    login = StubLogin()
    with pytest.raises(ProviderError) as caught:
        await run(fake, login)
    assert (caught.value.code, caught.value.reason, caught.value.retryable) == (
        "provider_auth",
        "login_required",
        False,
    )
    assert login.renewed == 1


async def test_a_refused_refresh_after_a_401_asks_for_a_new_sign_in(serve: Any) -> None:
    fake = await serve(failing(401, {}))
    login = StubLogin()
    login.dead = True
    with pytest.raises(ProviderError) as caught:
        await run(fake, login)
    assert (caught.value.code, caught.value.reason) == ("provider_auth", "login_required")


async def test_unsupported_response_formats_and_roles_are_refused_before_sending(serve: Any) -> None:
    fake = await serve(replying(events(["x"])))
    for request in (
        {**REQUEST, "response_format": {"type": "json_object"}},
        {**REQUEST, "messages": [{"role": "tool", "content": "x"}]},
        {**REQUEST, "messages": []},
    ):
        with pytest.raises(ProviderError) as caught:
            await run(fake, request=request)
        assert caught.value.code == "provider_bad_request"
    assert fake.seen == []


async def test_neither_the_token_nor_the_text_reaches_the_logs_or_errors(
    serve: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = await serve(failing(400, {"error": {"code": "bad", "message": f"echo {TOKEN_1} private meeting words"}}))
    with pytest.raises(ProviderError) as caught:
        await run(fake)
    for text in (caplog.text, repr(caught.value), json.dumps(caught.value.to_payload())):
        assert TOKEN_1 not in text and "private meeting words" not in text


# --- models ----------------------------------------------------------------------------------------------------

MODELS = {
    "models": [
        {"slug": "gpt-5-mini", "display_name": "GPT-5 mini", "visibility": "list", "priority": 2},
        {"slug": "gpt-5", "display_name": "GPT-5", "visibility": "list", "priority": 1},
        {"slug": "internal-x", "visibility": "hide", "priority": 0},
        {"slug": "no-priority"},
        {"display_name": "no slug"},
    ]
}


async def test_models_come_from_the_plan_in_its_order_and_hidden_ones_are_left_out(serve: Any) -> None:
    fake = await serve(failing(200, MODELS))
    models = await chat_responses.list_models(
        StubLogin(), SafeHttp(), base_url=f"{fake.url}/backend-api/codex", allow_local=True
    )
    assert [(m.id, m.name) for m in models] == [
        ("gpt-5", "GPT-5"),
        ("gpt-5-mini", "GPT-5 mini"),
        ("no-priority", "no-priority"),
    ]
    sent = fake.seen[0]
    assert sent.path == f"/backend-api/codex/models?client_version={chat_responses.CLIENT_VERSION}"
    assert sent.headers["chatgpt-account-id"] == ACCOUNT and sent.headers["authorization"] == f"Bearer {TOKEN_1}"


async def test_models_refresh_once_on_a_401_then_ask_for_a_new_sign_in(serve: Any) -> None:
    fake = await serve(failing(401, {}))
    login = StubLogin()
    with pytest.raises(ProviderError) as caught:
        await chat_responses.list_models(login, SafeHttp(), base_url=f"{fake.url}/c", allow_local=True)
    assert (caught.value.code, caught.value.reason) == ("provider_auth", "login_required")
    assert login.renewed == 1 and len(fake.seen) == 2


async def test_models_429_is_retryable(serve: Any) -> None:
    fake = await serve(failing(429, {}, {"Retry-After": "12"}))
    with pytest.raises(ProviderError) as caught:
        await chat_responses.list_models(StubLogin(), SafeHttp(), base_url=f"{fake.url}/c", allow_local=True)
    assert (caught.value.code, caught.value.retry_after_s) == ("provider_rate_limited", 12)
