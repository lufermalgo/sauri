"""The summary client sends the route header, reports who answered and classifies gateway failures (U3.3, #1137)."""

import json
from typing import Any

import httpx
import pytest
from sauri_engine_common.route import decode_route

from app.engines.routing import ROUTE_HEADER, ProviderError, Route
from app.summaries.engine import (
    ContextExceededError,
    OpenAICompatibleSummarizationEngine,
    SummaryInvalidError,
    SummaryProviderError,
)
from app.summaries.passages import Turn, build_passages

PASSAGES = build_passages([Turn("Synthetic transcript.", 0, 1000)])
VALID = {
    "topic": "Synthetic topic", "conclusion": "Synthetic conclusion",
    "key_points": [{
        "title": "Block", "items": [{"text": "Point", "sub_items": []}], "sources": [{"passage_id": "P0000"}],
    }],
}


def external_route(capability: str = "summary") -> Route:
    return Route(
        version=1, capability=capability, kind="openai", transport="openai-chat",  # type: ignore[arg-type]
        base_url="https://api.example.test/v1", model="gpt-requested", secret_ref="sauri/owner/provider",
        consent_version=1,
    )


def local_route() -> Route:
    return Route(
        version=1, capability="summary", kind="local", transport=None, base_url=None, model="local:qwen-small",
        secret_ref=None, consent_version=None,
    )


def completion(content: object, *, model: str | None = "answered-model", finish: str = "stop") -> dict[str, Any]:
    body: dict[str, Any] = {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(content)}}]}
    if model is not None:
        body["model"] = model
    return body


async def ask(
    response: httpx.Response, route: Route | None = None
) -> tuple[Any, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        engine = OpenAICompatibleSummarizationEngine("http://localhost:8003/v1", "qwen3.5-9b", client=client)
        try:
            answer = await engine.generate(PASSAGES, "Summarize", route)
        except Exception as error:  # the caller asserts on the class
            return error, seen
    return answer, seen


async def test_without_a_route_no_header_is_sent_and_the_local_engine_is_named() -> None:
    answer, seen = await ask(httpx.Response(200, json=completion(VALID, model="qwen3.5-9b")))
    assert ROUTE_HEADER not in seen[0].headers
    assert (answer.engine_name, answer.engine_model) == ("llama.cpp", "qwen3.5-9b")
    assert answer.summary.topic == "Synthetic topic"


async def test_an_external_route_travels_in_the_header_and_the_answering_model_is_reported() -> None:
    route = external_route()
    answer, seen = await ask(httpx.Response(200, json=completion(VALID, model="gpt-answered-2026")), route)
    assert decode_route(seen[0].headers[ROUTE_HEADER]) == route
    assert (answer.engine_name, answer.engine_model) == ("openai", "gpt-answered-2026")


async def test_a_response_without_a_model_falls_back_to_the_requested_one() -> None:
    answer, _ = await ask(httpx.Response(200, json=completion(VALID, model=None)), external_route())
    assert answer.engine_model == "gpt-requested"


async def test_a_local_model_route_still_names_the_local_engine() -> None:
    answer, seen = await ask(httpx.Response(200, json=completion(VALID, model="qwen-small")), local_route())
    assert decode_route(seen[0].headers[ROUTE_HEADER]) == local_route()
    assert (answer.engine_name, answer.engine_model) == ("llama.cpp", "qwen-small")


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (502, "provider_auth", False), (502, "provider_quota", True), (429, "provider_rate_limited", True),
        (504, "provider_timeout", True), (502, "provider_unavailable", True), (400, "provider_bad_request", False),
        (400, "provider_context_exceeded", False), (403, "consent_missing", False), (403, "origin_mismatch", False),
        (503, "secret_unavailable", False), (400, "provider_unsupported", False),
    ],
)
async def test_gateway_errors_become_classified_provider_errors(status: int, code: str, retryable: bool) -> None:
    body = {"error": {"code": code, "retryable": retryable, "retry_after_s": 7}}
    error, _ = await ask(httpx.Response(status, json=body), external_route())
    assert isinstance(error, ProviderError)
    assert (error.code, error.retryable) == (code, retryable)


async def test_an_unknown_error_body_keeps_the_legacy_unavailable_class() -> None:
    error, _ = await ask(httpx.Response(502, json={"error": {"code": "made_up", "retryable": True}}), external_route())
    assert isinstance(error, SummaryProviderError)


@pytest.mark.parametrize(
    "content",
    [
        {"topic": "x"},  # breaks the schema
        {**VALID, "key_points": [{**VALID["key_points"][0], "sources": [{"passage_id": "invented"}]}]},  # bad citation
    ],
)
async def test_property_13_external_invalid_output_is_rejected_locally_with_its_class(content: object) -> None:
    error, _ = await ask(httpx.Response(200, json=completion(content)), external_route())
    assert isinstance(error, ProviderError) and error.code == "provider_invalid_output"


async def test_property_13_unparseable_external_output_is_invalid_output() -> None:
    response = httpx.Response(200, json={"choices": [{"message": {"content": "not JSON"}}], "model": "m"})
    error, _ = await ask(response, external_route())
    assert isinstance(error, ProviderError) and error.code == "provider_invalid_output"


async def test_external_output_cut_by_length_is_context_exceeded() -> None:
    error, _ = await ask(httpx.Response(200, json=completion(VALID, finish="length")), external_route())
    assert isinstance(error, ProviderError) and error.code == "provider_context_exceeded"


async def test_the_local_engine_keeps_its_own_causes() -> None:
    invalid, _ = await ask(httpx.Response(200, json=completion({"topic": "x"})))
    assert isinstance(invalid, SummaryInvalidError)
    cut, _ = await ask(httpx.Response(200, json=completion(VALID, finish="length")))
    assert isinstance(cut, ContextExceededError)
