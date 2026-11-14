"""Finite local-generation budgets without changing the frozen request content."""

import asyncio
import json

import httpx
import pytest

from app.summaries.engine import OpenAICompatibleSummarizationEngine
from app.summaries.factory import create_summarization_engine
from app.summaries.passages import Turn, build_passages


@pytest.mark.parametrize("configured,expected", [(None, 1025.0), ("240.5", 365.5)])
def test_factory_generation_budget(monkeypatch: pytest.MonkeyPatch, configured: str | None, expected: float) -> None:
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("SUMMARIZATION_MODEL", "local-model")
    monkeypatch.delenv("SUMMARIZATION_TIMEOUT_SECONDS", raising=False)
    if configured is not None:
        monkeypatch.setenv("SUMMARIZATION_TIMEOUT_SECONDS", configured)
    assert create_summarization_engine().timeout_seconds == expected


@pytest.mark.parametrize("configured", ["", "zero", "0", "-1", "nan", "inf", "-inf"])
def test_invalid_budget_fails_closed(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("SUMMARIZATION_MODEL", "local-model")
    monkeypatch.setenv("SUMMARIZATION_TIMEOUT_SECONDS", configured)
    with pytest.raises(ValueError, match="SUMMARIZATION_TIMEOUT_SECONDS"):
        create_summarization_engine()


@pytest.mark.parametrize("injected", [False, True])
async def test_request_uses_long_generation_budget_without_changing_payload(
    monkeypatch: pytest.MonkeyPatch,
    injected: bool,
) -> None:
    transcript = "Synthetic transcript. " * 5000
    instructions = "  Frozen instructions\n"
    real_client = httpx.AsyncClient

    async def respond(request: httpx.Request) -> httpx.Response:
        # The old fixed 60 seconds is insufficient even before response headers.
        assert request.extensions["timeout"]["read"] == 1025.0
        assert request.extensions["timeout"]["connect"] == 10.0
        payload = json.loads(request.content)
        assert payload["messages"][1]["content"].endswith(transcript)
        assert instructions in payload["messages"][1]["content"]
        assert payload["model"] == "local-model"
        assert payload["stream"] is False
        assert payload["temperature"] == 0
        schema = payload["response_format"]["json_schema"]["schema"]
        assert schema["$defs"]["PassageRef"]["properties"]["passage_id"]["enum"] == ["P0000"]
        assert schema["$defs"]["KeyPoint"]["properties"]["sources"]["maxItems"] == 2
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "topic": "Synthetic", "key_points": [{"text": "Point", "sources": [{"passage_id": "P0000"}]}],
        })}}]})

    transport = httpx.MockTransport(respond)
    if injected:
        async with real_client(transport=transport, timeout=0.001) as client:
            result = await OpenAICompatibleSummarizationEngine(
                "http://localhost:11434",
                "local-model",
                client=client,
            ).generate(build_passages([Turn(transcript, 0, 1000)]), instructions)
    else:

        def local_client(**kwargs: object) -> httpx.AsyncClient:
            return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr("app.summaries.engine.httpx.AsyncClient", local_client)
        result = await OpenAICompatibleSummarizationEngine("http://localhost:11434", "local-model").generate(
            build_passages([Turn(transcript, 0, 1000)]),
            instructions,
        )
    assert result.topic == "Synthetic" and [p.text for p in result.key_points] == ["Point"]


async def test_total_deadline_cancels_generation_instead_of_waiting_forever() -> None:
    cancelled = asyncio.Event()

    async def stall(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(stall)) as client:
        engine = OpenAICompatibleSummarizationEngine(
            "http://localhost:11434",
            "local-model",
            client=client,
            timeout_seconds=0.02,
        )
        with pytest.raises(TimeoutError):
            await engine.generate(build_passages([Turn("Synthetic", 0, 1000)]), "Frozen")
    assert cancelled.is_set()
