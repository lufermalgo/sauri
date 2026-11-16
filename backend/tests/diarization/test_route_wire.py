"""``LocalProvider`` sends the resolved route to the gateway and reads its classified failures (U5.2),
and the factory accepts an external route only with its consent version."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx
import pytest
from sauri_engine_common.route import decode_route

from app.diarization import local_provider
from app.diarization.diarization_engine import DiarizationOptions
from app.diarization.factory import create_diarization_engine
from app.diarization.local_provider import LocalProvider
from app.engines.routing import ROUTE_HEADER, ProviderError, Route

BODY = {
    "contract_version": 2,
    "segments": [{"speaker": "0", "start_ms": 0, "end_ms": 500}, {"speaker": "1", "start_ms": 500, "end_ms": 900}],
    "speaker_count": 2,
    "engine": {"name": "deepgram", "model": "nova-3", "device": "remote"},
    "diagnostics": {"external": {"label_policy": "provider", "speaker_count_per_part": [2]}},
}
ROUTE = Route(
    version=1, capability="diarization", kind="deepgram", transport="deepgram",
    base_url="https://api.deepgram.com", model="nova-3", secret_ref="sauri/o/p", consent_version=1,
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


async def diarize(route: Route | None) -> Any:
    return await LocalProvider("http://gateway.test").diarize("recordings/a.wav", DiarizationOptions(route=route))


async def test_no_route_sends_exactly_the_request_of_before(gateway: Gateway) -> None:
    result = await diarize(None)
    assert ROUTE_HEADER not in gateway.seen[0].headers
    assert gateway.seen[0].content == b'{"audio_ref":"recordings/a.wav","contract_version":2}'
    assert result.engine.device == "remote" and result.speaker_count == 2
    assert result.diagnostics["external"]["label_policy"] == "provider"  # counts reach the worker


async def test_a_route_travels_in_the_header_without_keys_or_content(gateway: Gateway) -> None:
    await diarize(ROUTE)
    header = gateway.seen[0].headers[ROUTE_HEADER]
    assert decode_route(header) == ROUTE
    assert "key" not in header.lower()
    assert gateway.seen[0].content == b'{"audio_ref":"recordings/a.wav","contract_version":2}'


async def test_an_answer_without_diagnostics_still_reads(gateway: Gateway) -> None:
    gateway.reply = httpx.Response(200, json={k: v for k, v in BODY.items() if k != "diagnostics"})
    assert (await diarize(None)).diagnostics == {}


@pytest.mark.parametrize(
    "code", ["provider_unavailable", "provider_auth", "consent_missing", "provider_invalid_output"]
)
async def test_gateway_failures_become_classified_errors(gateway: Gateway, code: str) -> None:
    gateway.reply = httpx.Response(502, json={"error": {"code": code, "retryable": True, "retry_after_s": 9}})
    with pytest.raises(ProviderError) as raised:
        await diarize(ROUTE)
    assert raised.value.code == code and raised.value.retry_after_s == 9


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(422, json={"detail": "normalize_failed"}),
        httpx.Response(500, json={"detail": "Diarization failed"}),
        httpx.Response(502, json={"error": {"code": "made_up_class"}}),
        httpx.Response(502, text="not json"),
    ],
)
async def test_other_failures_keep_the_http_error_the_worker_already_handles(
    gateway: Gateway, reply: httpx.Response
) -> None:
    gateway.reply = reply
    with pytest.raises(httpx.HTTPStatusError):
        await diarize(ROUTE)


def test_the_factory_without_a_route_or_a_local_one_is_the_legacy_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARIZATION_LOCAL_URL", "http://gateway.test")
    monkeypatch.delenv("DIARIZATION_PROVIDER", raising=False)
    local = Route(version=1, capability="diarization", kind="local", transport=None, base_url=None,
                  model="local:default", secret_ref=None, consent_version=None)
    assert isinstance(create_diarization_engine(), LocalProvider)
    assert isinstance(create_diarization_engine(None), LocalProvider)
    assert isinstance(create_diarization_engine(local), LocalProvider)


def test_the_factory_accepts_an_external_route_only_with_its_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARIZATION_LOCAL_URL", "http://gateway.test")
    monkeypatch.delenv("DIARIZATION_PROVIDER", raising=False)
    assert isinstance(create_diarization_engine(ROUTE), LocalProvider)  # the gateway client carries the route
    with pytest.raises(ProviderError) as refused:
        create_diarization_engine(replace(ROUTE, consent_version=None))
    assert refused.value.code == "consent_missing"


def test_the_legacy_cloud_setting_stays_rejected_even_with_a_consented_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARIZATION_LOCAL_URL", "http://gateway.test")
    monkeypatch.setenv("DIARIZATION_PROVIDER", "cloud")
    with pytest.raises(ValueError, match="DIARIZATION_PROVIDER"):
        create_diarization_engine(ROUTE)
