"""Provider errors cannot silently turn partial or ungrounded output into an artifact."""

import json
from pathlib import Path

import httpx
import pytest

from app.summaries.engine import ContextExceededError, OpenAICompatibleSummarizationEngine, SummaryProviderError
from app.summaries.factory import create_summarization_engine
from app.summaries.passages import SummaryInvalidError, Turn, build_passages


@pytest.mark.parametrize(
    "status,body,error",
    [
        (400, {"error": {"code": "context_length_exceeded"}}, ContextExceededError),
        (400, {"error": {"type": "exceed_context_size_error"}}, ContextExceededError),
        (503, {"private": "provider diagnostic"}, SummaryProviderError),
        (200, {"choices": [{"finish_reason": "length"}]}, ContextExceededError),
        (200, {"choices": [{"message": {"content": "not JSON"}}]}, SummaryInvalidError),
        (
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "topic": "synthetic", "conclusion": "synthetic",
                                    "key_points": [{
                                        "title": "unsupported", "items": [{"text": "x", "sub_items": []}],
                                        "sources": [{"passage_id": "invented"}],
                                    }],
                                }
                            )
                        }
                    }
                ]
            },
            SummaryInvalidError,
        ),
    ],
)
async def test_fail_closed(status: int, body: dict[str, object], error: type[Exception]) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json=body)

    passages = build_passages([Turn("Synthetic start", 0, 1000), Turn("Synthetic END", 70_000, 71_000)])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        engine = OpenAICompatibleSummarizationEngine("http://localhost/v1", "local", client=client)
        with pytest.raises(error):
            await engine.generate(passages, "summarize")
    assert len(requests) == 1  # No truncating retry.
    payload = json.loads(requests[0].content)
    assert "Synthetic END" in payload["messages"][1]["content"]
    schema = payload["response_format"]["json_schema"]["schema"]
    assert "$ref" not in json.dumps(schema)
    sources = schema["properties"]["key_points"]["items"]["properties"]["sources"]["items"]
    assert sources["properties"]["passage_id"]["enum"] == ["P0000", "P0001"]
    system = payload["messages"][0]["content"]
    for required in ("acronyms", "absences", "goals, proposals, decisions and achievements", "untrusted data"):
        assert required in system


def test_defaults_and_https_compatibility(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in ("SUMMARIZATION_BASE_URL", "SUMMARIZATION_MODEL", "SUMMARIZATION_API_KEY_FILE"):
        monkeypatch.delenv(key, raising=False)
    engine = create_summarization_engine()
    assert engine.base_url == "http://host.docker.internal:8003/v1" and engine.model == "qwen3.5-9b"
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost:11434/v1/")
    assert create_summarization_engine().base_url == "http://localhost:11434/v1"
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "https://example.test/v1/")
    with pytest.raises(ValueError, match="local engine gateway"):
        create_summarization_engine()
    credential = tmp_path / "provider-key"
    credential.write_text("synthetic-external-key")
    monkeypatch.setenv("SUMMARIZATION_API_KEY_FILE", str(credential))  # No longer read: the key lives on the host.
    with pytest.raises(ValueError, match="local engine gateway"):
        create_summarization_engine()


@pytest.mark.parametrize("value", ["", "secret\nheader", "non-ascii-\u00f1"])
def test_bad_engine_token_file_fails_without_leaking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost:8003/v1")
    path = tmp_path / "credential"
    path.write_text(value)
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(path))
    with pytest.raises(ValueError, match="SAURI_ENGINE_TOKEN_FILE") as caught:
        create_summarization_engine()
    assert value.strip() not in str(caught.value) or not value.strip()
    path.unlink()
    with pytest.raises(ValueError, match="SAURI_ENGINE_TOKEN_FILE"):
        create_summarization_engine()
