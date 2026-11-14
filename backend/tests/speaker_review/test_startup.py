"""Startup needs no derived-audio keys; infrastructure doubles stay in tests."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests.meetings import test_transcript_word_turns as word_tests

migrated_url = word_tests.migrated_url
factory = word_tests.factory


async def test_api_lifespan_without_clip_keys(factory: word_tests.Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    monkeypatch.delenv("SPEAKER_EXCERPT_KEYRING", raising=False)
    monkeypatch.delenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", raising=False)
    queue = AsyncMock()
    monkeypatch.setattr(main, "create_job_queue", lambda: queue)
    async with main.app.router.lifespan_context(main.app):
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200 and response.json() == {"status": "ok"}
        await asyncio.sleep(0)
    queue.connect.assert_awaited()
    queue.disconnect.assert_awaited()


async def test_worker_subscribes_without_clip_keys(
    factory: word_tests.Factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app import worker

    monkeypatch.delenv("SPEAKER_EXCERPT_KEYRING", raising=False)
    monkeypatch.delenv("SPEAKER_EXCERPT_ACTIVE_KEY_ID", raising=False)
    token = tmp_path / "synthetic-engine-token"
    token.write_text("synthetic-engine-token", encoding="utf-8")
    monkeypatch.setenv("SAURI_ENGINE_TOKEN_FILE", str(token))
    monkeypatch.setenv("SUMMARIZATION_BASE_URL", "http://127.0.0.1:8003/v1")
    queue = AsyncMock()
    monkeypatch.setattr(worker, "create_job_queue", lambda: queue)
    monkeypatch.setattr(worker, "create_object_store", AsyncMock)

    def register_shutdown(sig: int, callback: Callable[[], None]) -> None:
        if sig == signal.SIGTERM:
            callback()

    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", register_shutdown)
    await worker.main()
    await asyncio.sleep(0)
    queue.connect.assert_awaited_once()
    assert {call.args[0] for call in queue.subscribe.await_args_list} == {
        "transcribe", "transcribe.failed", "diarize", "summarize", "summarize.failed",
    }
    queue.disconnect.assert_awaited_once()
