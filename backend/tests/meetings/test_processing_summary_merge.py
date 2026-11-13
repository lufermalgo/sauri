"""Real PostgreSQL regression for independent Alembic 014 branches (#250).

Only an explicitly isolated, disposable local database is used. No summary
or processing policy is changed by the no-op merge revision.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    raw = os.getenv("SAURI_MERGE_TEST_DATABASE_URL", "")
    if not raw:
        pytest.skip("set SAURI_MERGE_TEST_DATABASE_URL to a disposable PostgreSQL database")
    url = make_url(raw)
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.port is None
        or url.port < 55000
        or not (url.database or "").startswith("sauri_merge_")
    ):
        pytest.fail("merge regression requires an isolated local high-port sauri_merge_* database")
    return raw


async def _upgrade(target: str) -> None:
    # Alembic has a synchronous CLI and creates its own engine on a worker thread.
    await asyncio.to_thread(command.upgrade, Config(str(ROOT / "alembic.ini")), target)


async def _downgrade(target: str) -> None:
    await asyncio.to_thread(command.downgrade, Config(str(ROOT / "alembic.ini")), target)


@pytest.mark.parametrize("starting_parent", ["014_processing_revisions", "014_meeting_summaries_templates"])
async def test_merge_preserves_both_sibling_014_schemas_and_existing_rows(
    starting_parent: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _database_url()
    monkeypatch.setenv("DATABASE_URL", raw)
    engine = create_async_engine(raw)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
        await _upgrade(starting_parent)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id,email,name,password_hash,is_sales,created_at) "
                    "VALUES ('merge-owner','merge-owner@example.test','Synthetic','not-a-password',true,now())"
                )
            )
            if starting_parent == "014_processing_revisions":
                await connection.execute(
                    text(
                        "INSERT INTO meetings (id,origin,process_state,created_by,created_at) "
                        "VALUES ('merge-meeting','manual','completed','merge-owner',now())"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO session_recordings (id,meeting_id,idempotency_key,capture_origin,audio_ref,"
                        "duration_seconds,interrupted,finished_at) VALUES "
                        "('merge-recording','merge-meeting','merge-key','web_upload','synthetic/audio',10,false,now())"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO processing_revisions(id,recording_id,revision,created_at) "
                        "VALUES ('merge-revision','merge-recording',1,now())"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO recording_processing_states(recording_id,in_flight_revision_id) "
                        "VALUES ('merge-recording','merge-revision')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO processing_revision_outbox(id,recording_id,processing_revision_id,event_type,"
                        "delivery_status,created_at) VALUES "
                        "('merge-event','merge-recording','merge-revision','processing_revision_admitted','pending',now())"
                    )
                )
            else:
                await connection.execute(
                    text(
                        "INSERT INTO summary_templates(id,owner_user_id,name,version,instructions,"
                        "created_at,updated_at) "
                        "VALUES ('merge-template','merge-owner','Synthetic',1,'Synthetic only',now(),now())"
                    )
                )
        await _upgrade("head")
        async with engine.connect() as connection:
            heads = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            assert heads == ["015_merge_processing_summaries"]
            assert (await connection.execute(text("SELECT count(*) FROM processing_revisions"))).scalar_one() == (
                1 if starting_parent == "014_processing_revisions" else 0
            )
            assert (await connection.execute(text("SELECT count(*) FROM summary_templates"))).scalar_one() == (
                1 if starting_parent == "014_meeting_summaries_templates" else 0
            )
            if starting_parent == "014_processing_revisions":
                rows = (
                    await connection.execute(
                        text(
                            "SELECT s.in_flight_revision_id, o.processing_revision_id, o.delivery_status "
                            "FROM recording_processing_states s JOIN processing_revision_outbox o "
                            "ON o.recording_id=s.recording_id WHERE s.recording_id='merge-recording'"
                        )
                    )
                ).one()
                assert tuple(rows) == ("merge-revision", "merge-revision", "pending")
            else:
                owner = (
                    await connection.execute(
                        text("SELECT owner_user_id FROM summary_templates WHERE id='merge-template'")
                    )
                ).scalar_one()
                assert owner == "merge-owner"

        # Rolling back only the sibling introduced by this upgrade must not
        # discard rows that existed at the starting parent. Re-upgrade must
        # restore the merged head and both schemas without touching those rows.
        await _downgrade(starting_parent)
        other_parent = (
            "014_meeting_summaries_templates"
            if starting_parent == "014_processing_revisions"
            else "014_processing_revisions"
        )
        # Downgrading the mergepoint yields two heads; explicitly remove only
        # the sibling added during upgrade, leaving the stamped parent intact.
        await _downgrade(f"{other_parent}@013_manual_recovery_persistence")
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all() == [
                starting_parent
            ]
            if starting_parent == "014_processing_revisions":
                assert (
                    await connection.execute(text("SELECT count(*) FROM processing_revision_outbox"))
                ).scalar_one() == 1
            else:
                assert (await connection.execute(text("SELECT count(*) FROM summary_templates"))).scalar_one() == 1
        await _upgrade("head")
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all() == [
                "015_merge_processing_summaries"
            ]
            assert (await connection.execute(text("SELECT count(*) FROM processing_revisions"))).scalar_one() == (
                1 if starting_parent == "014_processing_revisions" else 0
            )
            assert (await connection.execute(text("SELECT count(*) FROM summary_templates"))).scalar_one() == (
                1 if starting_parent == "014_meeting_summaries_templates" else 0
            )
    finally:
        await engine.dispose()
