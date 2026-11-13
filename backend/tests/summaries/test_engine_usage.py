"""Allowlisted provider usage, without logging private meeting content."""

import asyncio
import json
import logging

import httpx
import pytest

from app.summaries.engine import OllamaSummarizationEngine

SECRET = "PRIVATE-CONTENT-SENTINEL"
LOGGER = "app.summaries.engine"


def events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(record.getMessage()) for record in caplog.records if record.name == LOGGER]


async def generate(envelope: dict[str, object]) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": '{"topic":"ok","key_points":[]}', **envelope})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await OllamaSummarizationEngine("http://localhost", SECRET, client=client).generate(SECRET, SECRET)
    assert result.topic == "ok"


async def test_usage_is_numeric_and_private_payload_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    await generate({
        "prompt_eval_count": 17839,
        "eval_count": 294,
        "total_duration": 724_381_100_000,
        "load_duration": 0,
        "prompt_eval_duration": 618_588_410_000,
        "eval_duration": 105_792_690_000,
        "context": [SECRET],
        "thinking": SECRET,
        "model": SECRET,
        "prompt": SECRET,
    })
    [event] = events(caplog)
    assert event["outcome"] == "succeeded"
    assert event["prompt_eval_count"] == 17839 and event["eval_count"] == 294
    assert event["prompt_eval_duration_seconds"] == pytest.approx(618.58841)
    assert event["load_duration_seconds"] == 0
    assert event["duration_seconds"] >= 0  # type: ignore[operator]
    assert SECRET not in json.dumps(event)
    assert set(event) == {
        "schema_version", "timestamp", "operation", "provider", "outcome", "duration_seconds",
        "prompt_eval_count", "eval_count", "total_duration_seconds", "load_duration_seconds",
        "prompt_eval_duration_seconds", "eval_duration_seconds",
    }


@pytest.mark.parametrize("value", [None, True, -1, "12", [], {}, 2**90])
async def test_invalid_counts_are_omitted(caplog: pytest.LogCaptureFixture, value: object) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    await generate({"prompt_eval_count": value, "eval_count": value})
    [event] = events(caplog)
    assert "prompt_eval_count" not in event and "eval_count" not in event
    assert "total_duration_seconds" not in event


@pytest.mark.parametrize("value", [None, True, -1, "12", [], {}, 2**90, float("inf"), float("nan")])
async def test_invalid_durations_are_omitted(caplog: pytest.LogCaptureFixture, value: object) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def respond(request: httpx.Request) -> httpx.Response:
        # JSON encoding of nonfinite values is not accepted by HTTPX's json= path.
        body = json.dumps({"response": '{"topic":"ok","key_points":[]}', "total_duration": value})
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await OllamaSummarizationEngine("http://localhost", "local", client=client).generate(SECRET, SECRET)
    [event] = events(caplog)
    assert "total_duration_seconds" not in event


async def test_error_is_preserved_without_exception_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(SECRET)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(httpx.ConnectError, match=SECRET):
            await OllamaSummarizationEngine("http://localhost", "local", client=client).generate(SECRET, SECRET)
    [event] = events(caplog)
    assert event["outcome"] == "error" and SECRET not in json.dumps(event)


async def test_cancel_is_preserved(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def cancel(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(transport=httpx.MockTransport(cancel)) as client:
        with pytest.raises(asyncio.CancelledError):
            await OllamaSummarizationEngine("http://localhost", "local", client=client).generate(SECRET, SECRET)
    assert events(caplog)[0]["outcome"] == "cancelled"


async def test_deadline_is_reported_without_private_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)

    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(stall)) as client:
        engine = OllamaSummarizationEngine("http://localhost", "local", client=client, timeout_seconds=0.01)
        with pytest.raises(TimeoutError):
            await engine.generate(SECRET, SECRET)
    [event] = events(caplog)
    assert event["outcome"] == "timeout" and SECRET not in json.dumps(event)


async def test_logging_failure_does_not_retry_valid_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr("app.summaries.engine.logger.info", fail)
    await generate({"prompt_eval_count": 3})
