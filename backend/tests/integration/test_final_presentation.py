"""Same stage/rollback/access contract against disposable PostgreSQL, not SQLite."""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.diarization.test_prepared_presentation_worker import (
    test_parent_commit_final_handoff_activation_and_redelivery as exercise_contract,
)
from tests.integration.test_diarization_reservation_concurrency import pg as _pg

pg = _pg


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_projection_postgres(
    pg: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch, ambiguous: bool
) -> None:
    await exercise_contract(pg, monkeypatch, ambiguous)
