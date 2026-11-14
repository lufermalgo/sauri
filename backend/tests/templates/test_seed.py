"""Data-only seed migration is idempotent, owner-scoped and preserves existing preferences."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.copy.templates_es import DEFAULT_CATEGORY, DEFAULT_INSTRUCTIONS, DEFAULT_NAME
from app.infra.models import SummaryTemplate, TemplateCategory, User
from app.templates.seed import ensure_default, seed_id


async def test_seed_migration_and_lazy_new_user(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    for owner in ("new", "custom"):
        db_session.add(User(id=owner, email=f"{owner}@example.test", name="Synthetic", password_hash="test-only",
                            is_sales=True, created_at=now))
    await db_session.flush()
    db_session.add(SummaryTemplate(id="personal", owner_user_id="custom", name="Personal", instructions="Custom",
                                   version=3, created_at=now, updated_at=now))
    await db_session.flush()
    custom = await db_session.get(User, "custom")
    assert custom is not None
    custom.default_summary_template_id = "personal"
    await db_session.commit()
    path = Path(__file__).parents[2] / "alembic/versions/015_seed_summary_default.py"
    spec = importlib.util.spec_from_file_location("seed_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db_session.connection()

    def run(sync_connection: Connection) -> None:
        monkeypatch.setattr(migration.op, "get_bind", lambda: sync_connection)
        migration.upgrade()
        migration.upgrade()
        migration.downgrade()  # Never deletes edited or referenced templates.

    await connection.run_sync(run)
    db_session.expire_all()
    assert await ensure_default(db_session, "custom") == "personal"
    assert await ensure_default(db_session, "new") == seed_id("new", "template")
    template = await db_session.get(SummaryTemplate, seed_id("new", "template"))
    assert template is not None and template.instructions == DEFAULT_INSTRUCTIONS
    assert template.owner_user_id == "new" and template.name == DEFAULT_NAME
    category = await db_session.get(TemplateCategory, template.category_id)
    assert category is not None and category.name == DEFAULT_CATEGORY and category.owner_user_id == "new"
    template.instructions = "Edited"
    assert await ensure_default(db_session, "new") == template.id
    assert template.instructions == "Edited"
    assert await db_session.scalar(select(func.count()).select_from(SummaryTemplate)) == 2
    db_session.add(User(id="later", email="later@example.test", name="Synthetic", password_hash="test-only",
                        is_sales=True, created_at=now))
    await db_session.flush()
    assert await ensure_default(db_session, "later") == seed_id("later", "template")
    assert await db_session.scalar(select(func.count()).select_from(SummaryTemplate)) == 3


async def test_postgres_015_upgrade_and_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import os
    from uuid import uuid4

    import asyncpg
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    from alembic import command

    raw = os.getenv("SAURI_MIGRATION_TEST_ADMIN_URL")
    if not raw:
        pytest.skip("requires disposable PostgreSQL admin URL")
    url = make_url(raw)
    database = f"sauri_u4_seed_{uuid4().hex}"
    admin = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False))
    connection = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        target = url.set(drivername="postgresql+asyncpg", database=database)
        monkeypatch.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
        config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        await asyncio.to_thread(command.upgrade, config, "014_meeting_summaries_templates")
        connection = await asyncpg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False))
        await connection.execute(
            "INSERT INTO users (id, email, name, password_hash, is_sales, created_at) "
            "VALUES ('synthetic', 'synthetic@example.test', 'Synthetic', 'test-only', true, now())"
        )
        await asyncio.to_thread(command.upgrade, config, "015_seed_summary_default")
        assert await connection.fetchval("SELECT default_summary_template_id FROM users") == seed_id(
            "synthetic", "template",
        )
        assert await connection.fetchval("SELECT instructions FROM summary_templates") == DEFAULT_INSTRUCTIONS
        await connection.execute(
            "INSERT INTO meetings (id, meet_link, origin, process_state, created_by, created_at) "
            "VALUES ('meeting', 'https://meet.example.test', 'link', 'completed', 'synthetic', now()); "
            "INSERT INTO transcripts (id, meeting_id, language, provider, supports_turns, created_at) "
            "VALUES ('transcript', 'meeting', 'es', 'synthetic', true, now())"
        )
        await connection.execute(
            "INSERT INTO summary_request_outbox "
            "(event_id, meeting_id, transcript_id, template_id, template_version, instructions_snapshot, "
            "generation, status) VALUES ('event', 'meeting', 'transcript', $1, 1, 'Synthetic', 1, 'pending')",
            seed_id("synthetic", "template"),
        )
        await asyncio.to_thread(command.upgrade, config, "016_summary_failure_cause")
        assert await connection.fetchval("SELECT failure_cause FROM summary_request_outbox") is None
        await connection.execute(
            "UPDATE summary_request_outbox SET status = 'failed', failure_cause = 'summary_invalid'"
        )
        assert await connection.fetchval("SELECT failure_cause FROM summary_request_outbox") == "summary_invalid"
        await connection.execute("UPDATE summary_templates SET instructions = 'Edited synthetic', version = 2")
        await asyncio.to_thread(command.downgrade, config, "014_meeting_summaries_templates")
        assert await connection.fetchval("SELECT instructions FROM summary_templates") == "Edited synthetic"
        assert await connection.fetchval("SELECT default_summary_template_id FROM users") == seed_id(
            "synthetic", "template",
        )
        assert await connection.fetchval("SELECT count(*) FROM template_categories") == 1
        assert await connection.fetchval("SELECT template_id FROM summary_request_outbox") == seed_id(
            "synthetic", "template",
        )
        await asyncio.to_thread(command.upgrade, config, "015_seed_summary_default")
        assert await connection.fetchval("SELECT count(*) FROM summary_templates") == 1
        assert await connection.fetchval("SELECT version FROM summary_templates") == 2
    finally:
        if connection is not None:
            await connection.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.close()
