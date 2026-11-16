"""``LocalProvider`` sends the resolved route to the gateway and reads its classified failures (U4.3)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sauri_engine_common.external.errors import ProviderError
from sauri_engine_common.route import ROUTE_HEADER, Route, decode_route

from app.transcription import local_provider
from app.transcription.asr_engine import TranscriptionOptions
from app.transcription.local_provider import LocalProvider

BODY = {
    "contract_version": 2,
    "segments": [{"text": "hola", "start_ms": 0, "end_ms": 500}],
    "words": [{"text": "hola", "start_ms": 0, "end_ms": 500, "probability": None, "timing_repaired": False}],
    "language": "es",
    "engine": {"name": "assemblyai", "model": "universal-2", "device": "remote"},
    "diagnostics": {"inverted_words": 0},
}
ROUTE = Route(
    version=1, capability="transcription", kind="assemblyai", transport="assemblyai",
    base_url="https://api.assemblyai.com", model="universal-2", secret_ref="sauri/o/p", consent_version=1,
)


class Gateway:
    """A fake gateway that records requests; ``reply`` swaps the answer."""

    def __init__(self) -> None:
        self.seen: list[httpx.Request] = []
        self.reply = httpx.Response(200, json=BODY)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        return self.reply


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    fake = Gateway()
    real = httpx.AsyncClient
    monkeypatch.setattr(
        local_provider.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake.handler))
    )
    return fake


async def transcribe(route: Route | None) -> Any:
    return await LocalProvider("http://gateway.test").transcribe("recordings/a.wav", TranscriptionOptions(route=route))


async def test_no_route_sends_exactly_the_request_of_before(gateway: Gateway) -> None:
    result = await transcribe(None)
    assert ROUTE_HEADER not in gateway.seen[0].headers
    assert result.engine.device == "remote" and result.words[0].text == "hola"


async def test_a_route_travels_in_the_header_without_keys_or_content(gateway: Gateway) -> None:
    await transcribe(ROUTE)
    header = gateway.seen[0].headers[ROUTE_HEADER]
    assert decode_route(header) == ROUTE
    assert "key" not in header.lower()
    assert gateway.seen[0].content == b'{"audio_ref":"recordings/a.wav","contract_version":2,"language":"es"}'


@pytest.mark.parametrize("code", ["provider_unavailable", "provider_auth", "consent_missing", "no_word_timestamps"])
async def test_gateway_failures_become_classified_errors(gateway: Gateway, code: str) -> None:
    gateway.reply = httpx.Response(502, json={"error": {"code": code, "retryable": True, "retry_after_s": 9}})
    with pytest.raises(ProviderError) as raised:
        await transcribe(ROUTE)
    assert raised.value.code == code and raised.value.retry_after_s == 9


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(422, json={"detail": "no_speech"}),
        httpx.Response(500, json={"detail": "engine_failed"}),
        httpx.Response(502, json={"error": {"code": "made_up_class"}}),
        httpx.Response(502, text="not json"),
    ],
)
async def test_other_failures_keep_the_http_error_the_worker_already_handles(
    gateway: Gateway, reply: httpx.Response
) -> None:
    gateway.reply = reply
    with pytest.raises(httpx.HTTPStatusError):
        await transcribe(ROUTE)
