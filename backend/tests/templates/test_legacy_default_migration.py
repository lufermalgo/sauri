"""Migration 021 moves the unedited legacy-id default template to the structured instructions."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.copy.templates_es import DEFAULT_INSTRUCTIONS, DEFAULT_INSTRUCTIONS_V2, DEFAULT_NAME
from app.templates.seed import seed_id

BACKEND = Path(__file__).parents[2]
HEAD = "021_default_summary_legacy_default"
PREVIOUS = "020_default_summary_structure"
BEFORE_STRUCTURE = "019_failed_summary_request"


async def test_postgres_021_updates_only_unedited_legacy_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_qa_legacy_default_{uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        target = url.set(drivername="postgresql+asyncpg", database=database)
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        config = Config(str(BACKEND / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, "014_meeting_summaries_templates")
        connection = await asyncpg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False))
        owners = ("seeded", "legacy", "legacyedit", "legacyname", "copyowner")
        for owner in owners:
            await connection.execute(
                "INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
                "VALUES ($1::varchar, $2::varchar, 'Synthetic', 'test-only', true, now())",
                owner, f"{owner}@example.test",
            )
        # The real 015 seeds the v1 starter (seeded id) for every owner without a default.
        await asyncio.to_thread(command.upgrade, config, BEFORE_STRUCTURE)

        async def add_template(template_id: str, owner: str, name: str, instructions: str, version: int = 1) -> None:
            await connection.execute(
                "INSERT INTO summary_templates "
                "(id, owner_user_id, name, instructions, version, created_at, updated_at) "
                "VALUES ($1, $2, $3, $4, $5, now(), now())",
                template_id, owner, name, instructions, version,
            )

        async def make_default(owner: str, template_id: str) -> None:
            await connection.execute(
                "UPDATE users SET default_summary_template_id = $1 WHERE id = $2", template_id, owner,
            )

        # Defaults created by an earlier mechanism: their ids are not the owners' seeded ids.
        await add_template("legacy-plain", "legacy", DEFAULT_NAME, DEFAULT_INSTRUCTIONS)
        await add_template("legacy-edited", "legacyedit", DEFAULT_NAME, "Personal wording", 2)
        await add_template("legacy-renamed", "legacyname", "Mi plantilla", DEFAULT_INSTRUCTIONS)
        # Same text and name as the old starter, but not any user's default.
        await add_template("copy-not-default", "copyowner", DEFAULT_NAME, DEFAULT_INSTRUCTIONS)
        for owner, template_id in (
            ("legacy", "legacy-plain"), ("legacyedit", "legacy-edited"), ("legacyname", "legacy-renamed"),
        ):
            await make_default(owner, template_id)
        await connection.execute(
            "INSERT INTO meetings (id, meet_link, origin, process_state, created_by, created_at) "
            "VALUES ('meeting', 'https://meet.example.test', 'link', 'completed', 'legacy', now()); "
            "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, created_at) "
            "VALUES ('transcript', 'meeting', 'es', 'synthetic', true, now())"
        )
        await connection.execute(
            "INSERT INTO summary_request_outbox (event_id, meeting_id, transcript_id, template_id, template_version, "
            "instructions_snapshot, generation, status) "
            "VALUES ('event', 'meeting', 'transcript', 'legacy-plain', 1, $1, 1, 'succeeded')",
            DEFAULT_INSTRUCTIONS,
        )

        async def state() -> dict[str, tuple[str, int]]:
            rows = await connection.fetch("SELECT id, instructions, version FROM summary_templates")
            return {row["id"]: (row["instructions"], row["version"]) for row in rows}

        await asyncio.to_thread(command.upgrade, config, PREVIOUS)
        after_020 = await state()
        seeded = seed_id("seeded", "template")
        assert after_020[seeded] == (DEFAULT_INSTRUCTIONS_V2, 2)
        # Migration 020 skips the legacy id: this is the gap migration 021 closes.
        assert after_020["legacy-plain"] == (DEFAULT_INSTRUCTIONS, 1)

        await asyncio.to_thread(command.upgrade, config, HEAD)
        after = await state()
        assert after["legacy-plain"] == (DEFAULT_INSTRUCTIONS_V2, 2)
        assert await connection.fetchval(
            "SELECT updated_at > created_at FROM summary_templates WHERE id = 'legacy-plain'"
        )
        assert after["legacy-edited"] == ("Personal wording", 2)
        assert after["legacy-renamed"] == (DEFAULT_INSTRUCTIONS, 1)
        assert after["copy-not-default"] == (DEFAULT_INSTRUCTIONS, 1)
        # 020's seeded case is not touched again (version stays 2, not 3).
        assert after[seeded] == (DEFAULT_INSTRUCTIONS_V2, 2)
        # Past summaries keep their own snapshot and template version.
        row = await connection.fetchrow("SELECT instructions_snapshot, template_version FROM summary_request_outbox")
        assert (row["instructions_snapshot"], row["template_version"]) == (DEFAULT_INSTRUCTIONS, 1)

        # Round trip, then replay the data step on already migrated rows: nothing changes (idempotent).
        await asyncio.to_thread(command.downgrade, config, PREVIOUS)
        assert (await state())["legacy-plain"] == (DEFAULT_INSTRUCTIONS, 1)
        await asyncio.to_thread(command.upgrade, config, HEAD)
        assert await state() == after
        await asyncio.to_thread(command.stamp, config, PREVIOUS)
        await asyncio.to_thread(command.upgrade, config, HEAD)
        assert await state() == after

        # A personal edit made after the upgrade survives the downgrade.
        await connection.execute(
            "UPDATE summary_templates SET instructions = 'Later edit', version = 3 WHERE id = 'legacy-plain'"
        )
        await asyncio.to_thread(command.downgrade, config, PREVIOUS)
        restored = await state()
        assert restored["legacy-plain"] == ("Later edit", 3)
        assert restored[seeded] == (DEFAULT_INSTRUCTIONS_V2, 2)
        await connection.execute(
            "UPDATE summary_templates SET instructions = $1, version = 2 WHERE id = 'legacy-plain'",
            DEFAULT_INSTRUCTIONS_V2,
        )

        # Full rollback: 021 restores the legacy row, 020 restores the seeded row, no double decrement.
        await asyncio.to_thread(command.upgrade, config, HEAD)
        await asyncio.to_thread(command.downgrade, config, BEFORE_STRUCTURE)
        rolled_back = await state()
        assert rolled_back["legacy-plain"] == (DEFAULT_INSTRUCTIONS, 1)
        assert rolled_back[seeded] == (DEFAULT_INSTRUCTIONS, 1)
        assert rolled_back["legacy-edited"] == ("Personal wording", 2)
        assert rolled_back["legacy-renamed"] == (DEFAULT_INSTRUCTIONS, 1)
        assert rolled_back["copy-not-default"] == (DEFAULT_INSTRUCTIONS, 1)
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.close()
