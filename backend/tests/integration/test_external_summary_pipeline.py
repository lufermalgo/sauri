"""U3.3 (#1137): the summary worker resolves the route, falls back to the local engine and records provenance.

Real parts: the worker, the real summary client, the LLM gateway (``llm-engine/native_main``) served over HTTP on
a random loopback port, the route header, the host secret store (private files) and a disposable PostgreSQL.
Fake parts: the provider (an OpenAI-shaped chat server on loopback) and the local model (``server.chat`` of the
gateway answers a fixed summary). No real provider, key or meeting is involved; real-provider behavior stays
NO VERIFICADO until the owner's run (U10).

Needs ``SAURI_QA_POSTGRES_URL`` (a disposable ``sauri_t11_*`` database), like the other summary worker tests.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.copy.engine_notices_es import NOTICE_VERSIONS
from app.infra.models import MeetingSummary, ProcessedSummaryEvent, SummaryRequestOutbox
from app.summaries.engine import SummaryProviderError
from app.summaries.worker import start_worker
from tests.external_asr_support import Served, add_provider, choose, consent, serve
from tests.llm_engine.external_support import (
    KEY,
    FakeProvider,
    Handler,
    failing,
    openai_events,
    replying,
)
from tests.summaries.test_worker import CapturedQueue, Case, case, outcomes  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine-common"))
from sauri_engine_common.secrets import FileSecretStore, SecretRecord  # noqa: E402

SECRET_REF = "sauri/owner/summary-provider"
SUMMARY = {
    "topic": "Provider topic", "conclusion": "Provider conclusion",
    "key_points": [{
        "title": "Block", "items": [{"text": "Point", "sub_items": []}], "sources": [{"passage_id": "P0000"}],
    }],
}
LOCAL_SUMMARY = {**SUMMARY, "topic": "Local topic"}
GOOD: Handler = replying(openai_events([json.dumps(SUMMARY)]))


def local_completion() -> dict[str, Any]:
    message = {"content": json.dumps(LOCAL_SUMMARY)}
    return {"model": "qwen3.5-9b", "choices": [{"finish_reason": "stop", "message": message}]}


@dataclass
class World:
    case: Case
    queue: CapturedQueue
    native: ModuleType
    gateway: Served
    provider: FakeProvider
    local_calls: list[tuple[dict[str, Any], Any]] = field(default_factory=list)
    set_handler: Callable[[Handler], None] = field(default=lambda _h: None)

    async def link(self, *, fallback: bool = True, consented: bool = True, model: str = "gpt-requested") -> str:
        provider_id = await add_provider(
            self.case.factory, owner=self.case.owner, kind="openai_compatible", secret_ref=SECRET_REF,
            base_url=f"{self.provider.url}/v1",
        )
        await choose(
            self.case.factory, provider_id, model, owner=self.case.owner, capability="summary", fallback=fallback
        )
        if consented:
            await consent(self.case.factory, provider_id, owner=self.case.owner, capability="summary")
        return provider_id

    async def deliver(self, message: dict[str, Any] | None = None) -> None:
        await self.queue.handlers["summarize"]((message or self.case.message).copy())

    async def request(self) -> SummaryRequestOutbox:
        async with self.case.factory() as session:
            row = await session.get(SummaryRequestOutbox, self.case.message["event_id"])
            assert row is not None
            return row

    async def summaries(self) -> list[MeetingSummary]:
        return (await outcomes(self.case))[1]


@pytest.fixture
async def world(
    case: Case, monkeypatch: pytest.MonkeyPatch, tmp_path: Path  # noqa: F811
) -> AsyncIterator[World]:
    engine_dir = Path(__file__).resolve().parents[2] / "llm-engine"
    monkeypatch.syspath_prepend(str(engine_dir))
    spec = importlib.util.spec_from_file_location("sauri_test_llm_summary_pipeline", engine_dir / "native_main.py")
    assert spec is not None and spec.loader is not None
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    token = tmp_path / "engine_token"
    token.write_text("synthetic-token")
    store = FileSecretStore(tmp_path / "secrets")
    monkeypatch.setattr(native, "ENGINE_TOKEN_PATH", token)
    monkeypatch.setattr(native, "_secret_store", store)
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(token))

    local_calls: list[tuple[dict[str, Any], Any]] = []

    async def local_chat(body: dict[str, Any], selection: Any = None) -> dict[str, Any]:
        local_calls.append((body, selection))
        return local_completion()

    monkeypatch.setattr(native.server, "chat", local_chat)

    current: list[Handler] = [GOOD]

    async def dispatch(seen: Any, writer: Any) -> None:
        await current[0](seen, writer)

    provider = FakeProvider(dispatch)
    await provider.start()
    store.put(SECRET_REF, SecretRecord(key=KEY, origin=provider.url))
    queue = CapturedQueue()
    try:
        with serve(native.app) as gateway:
            monkeypatch.setenv("SUMMARIZATION_BASE_URL", f"{gateway.url}/v1")
            monkeypatch.setenv("SUMMARIZATION_MODEL", "qwen3.5-9b")
            await start_worker(queue, case.factory)
            yield World(
                case, queue, native, gateway, provider, local_calls,
                set_handler=lambda handler: current.__setitem__(0, handler),
            )
    finally:
        await provider.close()


async def test_property_1_without_configuration_the_local_engine_answers_and_nothing_goes_out(world: World) -> None:
    await world.deliver()

    (row,) = await world.summaries()
    assert (row.engine_name, row.engine_model, row.engine_external) == ("llama.cpp", "qwen3.5-9b", False)
    assert row.engine_fallback_reason is None and row.topic == "Local topic"
    assert len(world.local_calls) == 1 and world.local_calls[0][1] is None  # the default model, no route
    assert world.provider.connections == 0
    assert (await world.request()).status == "succeeded"


async def test_a_local_choice_without_a_provider_stays_on_the_local_engine(world: World) -> None:
    await choose(
        world.case.factory, None, "local:default", owner=world.case.owner, capability="summary", fallback=True
    )
    await world.deliver()
    (row,) = await world.summaries()
    assert (row.engine_name, row.engine_external) == ("llama.cpp", False) and world.provider.connections == 0


async def test_an_external_choice_with_consent_summarizes_through_the_provider(world: World) -> None:
    await world.link()

    await world.deliver()

    (row,) = await world.summaries()
    assert (row.engine_name, row.engine_model, row.engine_external) == ("openai_compatible", "m-real", True)
    assert row.engine_fallback_reason is None and row.topic == "Provider topic"
    assert world.local_calls == [] and world.provider.connections == 1
    assert world.provider.seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert (await world.request()).status == "succeeded"


@pytest.mark.parametrize("state", ["never", "revoked", "outdated"])
async def test_property_2_without_a_current_consent_nothing_is_sent_and_the_local_engine_is_not_used(
    world: World, state: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_id = await world.link(consented=False)
    if state != "never":
        await consent(
            world.case.factory, provider_id, owner=world.case.owner, capability="summary", revoked=state == "revoked"
        )
    if state == "outdated":  # the notice text changed in a release: the consent given for version 1 stops counting
        monkeypatch.setitem(NOTICE_VERSIONS, "summary", NOTICE_VERSIONS["summary"] + 1)

    await world.deliver()

    request = await world.request()
    assert (request.status, request.failure_cause) == ("failed", "consent_missing")
    assert await world.summaries() == [] and world.provider.connections == 0 and world.local_calls == []
    async with world.case.factory() as session:
        assert await session.get(ProcessedSummaryEvent, world.case.message["event_id"]) is None


@pytest.mark.parametrize(
    "status,body,reason",
    [
        (503, {"error": {"message": "down"}}, "provider_unavailable"),
        (429, {"error": {"message": "slow down"}}, "provider_rate_limited"),
        (402, {"error": {"message": "pay"}}, "provider_quota"),
        (504, {"error": {"message": "late"}}, "provider_timeout"),
    ],
)
async def test_property_14_a_transient_failure_with_fallback_runs_the_local_engine_once_and_records_it(
    world: World, status: int, body: dict[str, Any], reason: str
) -> None:
    world.set_handler(failing(status, body))
    await world.link(fallback=True)

    await world.deliver()

    (row,) = await world.summaries()
    assert (row.engine_name, row.engine_model, row.engine_external) == ("llama.cpp", "qwen3.5-9b", False)
    assert row.engine_fallback_reason == reason and row.topic == "Local topic"
    assert world.provider.connections == 1 and len(world.local_calls) == 1
    assert world.local_calls[0][1] is None  # a new request for the default local model, never another provider
    request = await world.request()
    assert (request.status, request.failure_cause) == ("succeeded", None)


async def test_property_14_a_transient_failure_without_fallback_is_retried_by_the_queue_and_keeps_its_cause(
    world: World,
) -> None:
    world.set_handler(failing(503, {"error": {"message": "down"}}))
    await world.link(fallback=False)

    with pytest.raises(SummaryProviderError):
        await world.deliver()

    request = await world.request()
    assert (request.status, request.failure_cause) == ("running", "provider_unavailable")
    assert world.local_calls == [] and await world.summaries() == []
    await world.queue.handlers["summarize.failed"](world.case.message.copy())  # the retries are exhausted
    request = await world.request()
    assert (request.status, request.failure_cause) == ("failed", "provider_unavailable")


@pytest.mark.parametrize(
    "status,body,cause",
    [
        (401, {"error": {"message": "bad key"}}, "provider_auth"),
        (400, {"error": {"message": "bad parameter"}}, "provider_bad_request"),
        (400, {"error": {"code": "context_length_exceeded"}}, "provider_context_exceeded"),
    ],
)
async def test_property_14_user_action_failures_end_the_request_and_never_change_the_engine(
    world: World, status: int, body: dict[str, Any], cause: str
) -> None:
    world.set_handler(failing(status, body))
    await world.link(fallback=True)

    await world.deliver()  # terminal: acknowledged, not retried

    request = await world.request()
    assert (request.status, request.failure_cause) == ("failed", cause)
    assert world.local_calls == [] and await world.summaries() == [] and world.provider.connections == 1


async def test_property_13_an_invalid_provider_answer_is_rejected_locally_and_saves_nothing(world: World) -> None:
    world.set_handler(replying(openai_events([json.dumps({"topic": "no key points"})])))
    await world.link(fallback=True)

    await world.deliver()

    request = await world.request()
    assert (request.status, request.failure_cause) == ("failed", "provider_invalid_output")
    assert world.local_calls == [] and await world.summaries() == []


async def test_property_13_a_citation_to_a_missing_passage_is_not_saved(world: World) -> None:
    invented = {**SUMMARY, "key_points": [{**SUMMARY["key_points"][0], "sources": [{"passage_id": "P9999"}]}]}
    world.set_handler(replying(openai_events([json.dumps(invented)])))
    await world.link(fallback=True)
    await world.deliver()
    request = await world.request()
    assert (request.status, request.failure_cause) == ("failed", "provider_invalid_output")
    assert await world.summaries() == []


async def test_property_15_a_change_applies_to_the_next_attempt_without_restarting_anything(world: World) -> None:
    await world.link(fallback=False)
    await world.deliver()
    assert (await world.summaries())[0].engine_external is True

    await choose(
        world.case.factory, None, "local:default", owner=world.case.owner, capability="summary", fallback=False
    )
    second = {**world.case.message, "event_id": str(uuid4()), "generation": 2}
    async with world.case.factory() as session, session.begin():
        session.add(SummaryRequestOutbox(**second, status="pending", delivered_at=datetime.now(UTC)))
    await world.deliver(second)

    async with world.case.factory() as session:
        rows = list(await session.scalars(select(MeetingSummary).order_by(MeetingSummary.generation)))
    assert [(r.generation, r.engine_external) for r in rows] == [(1, True), (2, False)]
    assert world.provider.connections == 1 and len(world.local_calls) == 1


async def test_property_15_a_redelivery_never_duplicates_the_summary_or_calls_an_engine_again(world: World) -> None:
    await world.link()
    await world.deliver()
    await world.deliver()  # the broker delivers the same message again after the commit
    await world.deliver()

    assert len(await world.summaries()) == 1 and world.provider.connections == 1 and world.local_calls == []
    async with world.case.factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProcessedSummaryEvent)) == 1


async def test_property_15_a_retry_after_a_failure_with_another_engine_saves_one_summary(world: World) -> None:
    world.set_handler(failing(503, {"error": {"message": "down"}}))
    provider_id = await world.link(fallback=False)
    with pytest.raises(SummaryProviderError):
        await world.deliver()
    assert await world.summaries() == []

    # The owner turns the fallback on before the redelivery: the local engine answers this time.
    await choose(
        world.case.factory, provider_id, "gpt-requested", owner=world.case.owner, capability="summary", fallback=True
    )
    await world.deliver()
    await world.deliver()  # and a duplicate delivery after that

    (row,) = await world.summaries()
    assert (row.engine_external, row.engine_fallback_reason) == (False, "provider_unavailable")
    request = await world.request()
    assert (request.status, request.failure_cause) == ("succeeded", None)
