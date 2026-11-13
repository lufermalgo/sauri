"""Finite local-generation budgets without changing the frozen request content."""

import asyncio
import json

import httpx
import pytest

from app.summaries.engine import OllamaSummarizationEngine
from app.summaries.factory import create_summarization_engine


@pytest.mark.parametrize("configured,expected", [(None, 900.0), ("240.5", 240.5)])
def test_factory_generation_budget(monkeypatch: pytest.MonkeyPatch, configured: str | None, expected: float) -> None:
    monkeypatch.setenv("SUMMARIZATION_OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("SUMMARIZATION_OLLAMA_MODEL", "local-model")
    monkeypatch.delenv("SUMMARIZATION_TIMEOUT_SECONDS", raising=False)
    if configured is not None:
        monkeypatch.setenv("SUMMARIZATION_TIMEOUT_SECONDS", configured)
    assert create_summarization_engine().timeout_seconds == expected


@pytest.mark.parametrize("configured", ["", "zero", "0", "-1", "nan", "inf", "-inf"])
def test_invalid_budget_fails_closed(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    monkeypatch.setenv("SUMMARIZATION_OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("SUMMARIZATION_OLLAMA_MODEL", "local-model")
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
        assert request.extensions["timeout"]["read"] == 900.0
        assert request.extensions["timeout"]["connect"] == 10.0
        payload = json.loads(request.content)
        assert payload["prompt"].endswith(f"{instructions}\nTranscript:\n{transcript}")
        assert payload["model"] == "local-model"
        assert payload["stream"] is False
        assert set(payload) == {"model", "prompt", "stream", "format"}
        return httpx.Response(200, json={"response": '{"topic":"Synthetic","key_points":["Point"]}'})

    transport = httpx.MockTransport(respond)
    if injected:
        async with real_client(transport=transport, timeout=0.001) as client:
            result = await OllamaSummarizationEngine(
                "http://localhost:11434",
                "local-model",
                client=client,
            ).generate(transcript, instructions)
    else:

        def local_client(**kwargs: object) -> httpx.AsyncClient:
            return real_client(transport=transport, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr("app.summaries.engine.httpx.AsyncClient", local_client)
        result = await OllamaSummarizationEngine("http://localhost:11434", "local-model").generate(
            transcript,
            instructions,
        )
    assert result.topic == "Synthetic" and result.key_points == ["Point"]


async def test_total_deadline_cancels_generation_instead_of_waiting_forever() -> None:
    cancelled = asyncio.Event()

    async def stall(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(stall)) as client:
        engine = OllamaSummarizationEngine(
            "http://localhost:11434",
            "local-model",
            client=client,
            timeout_seconds=0.02,
        )
        with pytest.raises(TimeoutError):
            await engine.generate("Synthetic", "Frozen")
    assert cancelled.is_set()
