"""Target preparation against a disposable PostgreSQL (scripts/tests/pg-disposable.sh)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg  # type: ignore[import-untyped]
import pytest
from sauri_migrate import target as tgt  # noqa: E402
from sqlalchemy.engine import make_url

from tests.migrate_from_docker import TOOL_DIR  # noqa: F401  (puts the tool on sys.path)

ADMIN_URL = os.environ.get("SAURI_MIGRATION_TEST_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="needs SAURI_MIGRATION_TEST_ADMIN_URL (pg-disposable.sh)")


@pytest.fixture
async def target() -> AsyncIterator[tgt.PgTarget]:
    assert ADMIN_URL is not None
    name = f"sauri_qa_mig_{uuid.uuid4().hex[:8]}"
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    yield tgt.PgTarget.from_url(url)
    connection = await asyncpg.connect(ADMIN_URL.replace("+asyncpg", ""))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await connection.close()


async def test_missing_target_is_created_empty_and_marked_until_success(target: tgt.PgTarget) -> None:
    state = await tgt.inspect_target(target)
    assert not state.exists and tgt.target_problem(state, False, False) is None
    await tgt.recreate_database(target, state)
    state = await tgt.inspect_target(target)
    assert state.exists and state.table_count == 0 and state.in_progress_mark
    await tgt.clear_in_progress_mark(target)
    assert not (await tgt.inspect_target(target)).in_progress_mark


async def test_a_target_with_meetings_is_never_replaced(target: tgt.PgTarget) -> None:
    await tgt.recreate_database(target, await tgt.inspect_target(target))
    await tgt.clear_in_progress_mark(target)
    connection = await target.connect()
    try:
        await connection.execute("CREATE TABLE meetings (id text); CREATE TABLE users (id text, email text)")
        await connection.execute("INSERT INTO meetings VALUES ('m'); INSERT INTO users VALUES ('u', 'e')")
    finally:
        await connection.close()
    state = await tgt.inspect_target(target)
    assert (state.meetings, state.users) == (1, 1)
    assert tgt.target_problem(state, True, True) is not None
    assert await tgt.row_counts(target) == {"public.meetings": 1, "public.users": 1}
    assert await tgt.user_id_by_email(target, "e") == "u"


async def test_a_fresh_setup_is_replaced_only_with_the_flag(target: tgt.PgTarget) -> None:
    await tgt.recreate_database(target, await tgt.inspect_target(target))
    await tgt.clear_in_progress_mark(target)
    connection = await target.connect()
    try:
        await connection.execute("CREATE TABLE meetings (id text); CREATE TABLE users (id text, email text)")
        await connection.execute("INSERT INTO users VALUES ('local', 'local@sauri.local')")
    finally:
        await connection.close()
    state = await tgt.inspect_target(target)
    assert tgt.target_problem(state, False, False) is not None
    assert tgt.target_problem(state, True, False) is None
    await tgt.recreate_database(target, state)
    assert (await tgt.inspect_target(target)).table_count == 0
    assert await tgt.system_identifier(target) != ""


@pytest.mark.skipif(not os.environ.get("SAURI_QA_POSTGRES_ROOT"), reason="needs the pg-disposable socket folder")
async def test_a_socket_target_like_the_app_restores_and_upgrades(target: tgt.PgTarget) -> None:
    """The app reaches PostgreSQL through a Unix socket folder; alembic must work through it too."""
    socket = os.path.join(os.environ["SAURI_QA_POSTGRES_ROOT"], "socket")
    via_socket = tgt.PgTarget(socket, target.port, target.user, target.password, target.database)
    assert via_socket.is_socket and tgt.PgTarget.from_url(via_socket.asyncpg_url()) == via_socket
    await tgt.recreate_database(via_socket, await tgt.inspect_target(via_socket))
    tgt.alembic_upgrade(via_socket)
    assert await tgt.alembic_revision(via_socket) == tgt.alembic_head()
    assert (await tgt.row_counts(via_socket))["public.job_messages"] == 0
