"""Credentials must be selected by destination, never inherited by external hosts."""

import json
from pathlib import Path

import httpx
import pytest

from app.summaries.factory import create_summarization_engine
from app.summaries.passages import Turn, build_passages


@pytest.fixture
def keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    local, external = tmp_path / "engine-token", tmp_path / "provider-key"
    local.write_text("synthetic-local-engine-token")
    external.write_text("synthetic-external-provider-key")
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(local))
    monkeypatch.delenv("SUMMARIZATION_API_KEY_FILE", raising=False)
    return local, external


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.0.0.2", "[::1]", "host.docker.internal"])
async def test_local_destination_uses_only_engine_token(
    keys: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    local, external = keys
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", f"http://{host}:8003/v1")
    monkeypatch.setenv("SUMMARIZATION_API_KEY_FILE", str(external))
    engine = create_summarization_engine()
    assert engine._api_key == local.read_text()


@pytest.mark.parametrize("host", ["provider.example", "localhost.evil.test", "host.docker.internal.evil.test"])
def test_external_host_requires_explicit_file(
    keys: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", f"https://{host}/v1")
    with pytest.raises(ValueError, match="SUMMARIZATION_API_KEY_FILE.*external"):
        create_summarization_engine()


async def test_external_request_never_uses_local_token(
    keys: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    local, external = keys
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("SUMMARIZATION_API_KEY_FILE", str(external))
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {external.read_text()}"
        assert local.read_text() not in str(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
    "topic": "Synthetic", "conclusion": "Synthetic conclusion",
    "key_points": [{
        "title": "Block", "items": [{"text": "Point", "sub_items": []}],
        "sources": [{"passage_id": "P0000"}],
    }],
})}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        engine = create_summarization_engine()
        engine._client = client
        await engine.generate(build_passages([Turn("Synthetic", 0, 1000)]), "Summarize")
    assert len(requests) == 1
    monkeypatch.setenv("SUMMARIZATION_API_KEY_FILE", str(local))
    with pytest.raises(ValueError, match="local engine token"):
        create_summarization_engine()
    external.write_text(local.read_text())
    monkeypatch.setenv("SUMMARIZATION_API_KEY_FILE", str(external))
    with pytest.raises(ValueError, match="local engine token"):
        create_summarization_engine()


async def test_local_redirect_cannot_forward_engine_token(
    keys: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.summaries.engine import SummaryProviderError

    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://localhost:8003/v1")
    destinations = []

    def respond(request: httpx.Request) -> httpx.Response:
        destinations.append(request.url.host)
        assert request.url.host == "localhost"
        return httpx.Response(307, headers={"Location": "https://provider.example/v1/chat/completions"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        engine = create_summarization_engine()
        engine._client = client
        with pytest.raises(SummaryProviderError):
            await engine.generate(build_passages([Turn("Synthetic", 0, 1000)]), "Summarize")
    assert destinations == ["localhost"]
