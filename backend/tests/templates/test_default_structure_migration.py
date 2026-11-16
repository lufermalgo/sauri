"""Migration 020 moves only unedited seeded defaults to the structured instructions."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.copy.templates_es import DEFAULT_INSTRUCTIONS, DEFAULT_INSTRUCTIONS_V2
from app.templates.seed import seed_id

BACKEND = Path(__file__).parents[2]


def test_v2_text_follows_the_reference_structure_and_forbids_timestamps() -> None:
    for required in (
        "Asunto principal", "Puntos clave y desarrollo de la discusi", "3) Conclusi",
        "Decisi", "ximos pasos y compromisos", "no menciones minutos ni marcas de tiempo",
        "no inventes", "no expandas siglas", "no infieras ausencias",
    ):
        assert required in DEFAULT_INSTRUCTIONS_V2
    assert DEFAULT_INSTRUCTIONS_V2 != DEFAULT_INSTRUCTIONS


def test_revision_chain_has_a_single_head() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["028_auth_refresh_tokens"]  # The refresh-token revision follows.
    assert script.get_revision("022_recording_thumbnail").down_revision == "021_default_summary_legacy_default"
    assert script.get_revision("021_default_summary_legacy_default").down_revision == "020_default_summary_structure"


async def test_postgres_020_updates_only_unedited_seeded_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_qa_default_structure_{uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        target = url.set(drivername="postgresql+asyncpg", database=database)
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        config = Config(str(BACKEND / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, "014_meeting_summaries_templates")
        connection = await asyncpg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False))
        for owner in ("plain", "edited", "lookalike"):
            await connection.execute(
                "INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
                "VALUES ($1::varchar, $2::varchar, 'Synthetic', 'test-only', true, now())",
                owner, f"{owner}@example.test",
            )
        # The real 015 seeds the v1 starter for every owner without a default.
        await asyncio.to_thread(command.upgrade, config, "019_failed_summary_request")
        assert await connection.fetchval("SELECT count(*) FROM summary_templates") == 3
        await connection.execute(
            "UPDATE summary_templates SET instructions = 'Personal wording', version = 2 WHERE owner_user_id = 'edited'"
        )
        # Same text as the old seed but a personal template, not the seeded default.
        await connection.execute(
            "INSERT INTO summary_templates (id, owner_user_id, name, instructions, version, created_at, updated_at) "
            "VALUES ('personal-copy', 'lookalike', 'Copy', $1, 1, now(), now())", DEFAULT_INSTRUCTIONS,
        )
        await connection.execute(
            "INSERT INTO meetings (id, meet_link, origin, process_state, created_by, created_at) "
            "VALUES ('meeting', 'https://meet.example.test', 'link', 'completed', 'plain', now()); "
            "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, created_at) "
            "VALUES ('transcript', 'meeting', 'es', 'synthetic', true, now())"
        )
        await connection.execute(
            "INSERT INTO summary_request_outbox (event_id, meeting_id, transcript_id, template_id, template_version, "
            "instructions_snapshot, generation, status) "
            "VALUES ('event', 'meeting', 'transcript', $1, 1, $2, 1, 'succeeded')",
            seed_id("plain", "template"), DEFAULT_INSTRUCTIONS,
        )

        async def state() -> dict[str, tuple[str, int]]:
            rows = await connection.fetch("SELECT id, instructions, version FROM summary_templates")
            return {row["id"]: (row["instructions"], row["version"]) for row in rows}

        await asyncio.to_thread(command.upgrade, config, "020_default_summary_structure")
        after = await state()
        assert after[seed_id("plain", "template")] == (DEFAULT_INSTRUCTIONS_V2, 2)
        assert after[seed_id("lookalike", "template")] == (DEFAULT_INSTRUCTIONS_V2, 2)
        assert after[seed_id("edited", "template")] == ("Personal wording", 2)
        assert after["personal-copy"] == (DEFAULT_INSTRUCTIONS, 1)
        assert await connection.fetchval("SELECT instructions_snapshot FROM summary_request_outbox") == (
            DEFAULT_INSTRUCTIONS
        )
        assert await connection.fetchval(
            "SELECT updated_at > created_at FROM summary_templates WHERE id = $1", seed_id("plain", "template")
        )

        # Round trip: downgrade then upgrade again reaches the same state (idempotent data step).
        await asyncio.to_thread(command.downgrade, config, "019_failed_summary_request")
        assert (await state())[seed_id("plain", "template")] == (DEFAULT_INSTRUCTIONS, 1)
        await asyncio.to_thread(command.upgrade, config, "020_default_summary_structure")
        assert await state() == after

        # A personal edit made after the upgrade survives the downgrade.
        await connection.execute(
            "UPDATE summary_templates SET instructions = 'Later edit', version = 3 WHERE id = $1",
            seed_id("lookalike", "template"),
        )
        await asyncio.to_thread(command.downgrade, config, "019_failed_summary_request")
        restored = await state()
        assert restored[seed_id("plain", "template")] == (DEFAULT_INSTRUCTIONS, 1)
        assert restored[seed_id("lookalike", "template")] == ("Later edit", 3)
        assert restored[seed_id("edited", "template")] == ("Personal wording", 2)
        assert restored["personal-copy"] == (DEFAULT_INSTRUCTIONS, 1)
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.close()
