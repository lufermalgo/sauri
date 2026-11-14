"""Keep SQLite unit tests isolated from PostgreSQL-only coordination.

Worker slot integration is exercised without this stub by test_pipeline_workers.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.infra.engine_slot import engine_slot


@pytest.fixture(autouse=True)
def sqlite_worker_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def slot(engine: AsyncEngine, *, kind: str, timeout_s: float) -> AsyncIterator[None]:
        if engine.dialect.name == "sqlite":
            yield
        else:
            async with engine_slot(engine, kind=kind, timeout_s=timeout_s):
                yield

    monkeypatch.setattr("app.transcription.worker.engine_slot", slot)
    monkeypatch.setattr("app.diarization.worker.engine_slot", slot)
