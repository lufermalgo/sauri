"""Allowlisted OpenAI usage and credentials excluded from all captured logs."""

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

from app.summaries.engine import OpenAICompatibleSummarizationEngine, SummaryProviderError
from app.summaries.factory import create_summarization_engine
from app.summaries.passages import Turn, build_passages

SECRET = "PRIVATE-CONTENT-SENTINEL"
LOGGER = "app.summaries.engine"
PASSAGES = build_passages([Turn(SECRET, 0, 1000)])
CONTENT = {"topic": "ok", "key_points": [{"text": "point", "sources": [{"passage_id": "P0000"}]}]}


def events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(record.getMessage()) for record in caplog.records if record.name == LOGGER]


async def generate(envelope: dict[str, object]) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=json.dumps(
                {
                    "choices": [{"message": {"content": json.dumps(CONTENT)}}],
                    **envelope,
                }
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await OpenAICompatibleSummarizationEngine("http://localhost/v1", SECRET, client=client).generate(
            PASSAGES,
            SECRET,
        )
    assert result.topic == "ok"


async def test_usage_and_file_credential_are_not_logged(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG)
    key_file = tmp_path / "key"
    key_file.write_text(SECRET)
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(key_file))
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost/v1")

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(CONTENT)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "secret": SECRET},
                "thinking": SECRET,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        engine = create_summarization_engine()
        engine._client = client
        await engine.generate(PASSAGES, SECRET)
    [event] = events(caplog)
    assert event["outcome"] == "succeeded"
    assert event["prompt_tokens"] == 100 and event["completion_tokens"] == 20 and event["total_tokens"] == 120
    assert SECRET not in caplog.text
    assert set(event) == {
        "schema_version",
        "timestamp",
        "operation",
        "provider",
        "outcome",
        "duration_seconds",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }


@pytest.mark.parametrize("value", [None, True, -1, "12", [], {}, 2**90, float("inf"), float("nan")])
async def test_invalid_usage_is_omitted(caplog: pytest.LogCaptureFixture, value: object) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    await generate({"usage": {"prompt_tokens": value, "completion_tokens": value, "total_tokens": value}})
    [event] = events(caplog)
    assert not {"prompt_tokens", "completion_tokens", "total_tokens"} & event.keys()


async def test_transport_error_is_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    async def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(SECRET)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(SummaryProviderError) as error:
            await OpenAICompatibleSummarizationEngine("http://localhost/v1", "local", client=client).generate(
                PASSAGES,
                SECRET,
            )
    assert events(caplog)[0]["outcome"] == "error"
    assert SECRET not in caplog.text + str(error.value)


async def test_cancel_is_preserved(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def cancel(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(transport=httpx.MockTransport(cancel)) as client:
        with pytest.raises(asyncio.CancelledError):
            await OpenAICompatibleSummarizationEngine("http://localhost/v1", "local", client=client).generate(
                PASSAGES,
                SECRET,
            )
    assert events(caplog)[0]["outcome"] == "cancelled"


async def test_deadline_is_reported_without_private_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(stall)) as client:
        engine = OpenAICompatibleSummarizationEngine(
            "http://localhost/v1", "local", client=client, timeout_seconds=0.01
        )
        with pytest.raises(TimeoutError):
            await engine.generate(PASSAGES, SECRET)
    assert events(caplog)[0]["outcome"] == "timeout" and SECRET not in caplog.text


async def test_logging_failure_does_not_retry_valid_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr("app.summaries.engine.logger.info", fail)
    await generate({"usage": {"prompt_tokens": 3}})


@pytest.mark.parametrize("invalid", [False, True])
async def test_transcript_text_never_appears_in_logs(caplog: pytest.LogCaptureFixture, invalid: bool) -> None:
    caplog.set_level(logging.DEBUG)
    transcript = "Synthetic confidential transcript sentinel with multiple words"
    passages = build_passages([Turn(transcript, 0, 1000)])

    def respond(request: httpx.Request) -> httpx.Response:
        assert transcript in json.loads(request.content)["messages"][1]["content"]
        content = "not JSON: " + transcript if invalid else json.dumps({**CONTENT, "topic": transcript})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "diagnostic": transcript})

    from app.summaries.passages import SummaryInvalidError

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        engine = OpenAICompatibleSummarizationEngine("http://localhost/v1", "synthetic", client=client)
        if invalid:
            with pytest.raises(SummaryInvalidError) as error:
                await engine.generate(passages, "Summarize")
            assert transcript not in str(error.value)
        else:
            assert (await engine.generate(passages, "Summarize")).topic == transcript
    assert events(caplog)
    assert transcript not in caplog.text
