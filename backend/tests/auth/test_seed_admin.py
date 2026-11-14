"""Single administrator account seed against a real PostgreSQL.

The module creates its own throwaway database next to the one in
SAURI_QA_POSTGRES_URL (a disposable ``sauri_qa`` database), builds the schema
with ``alembic upgrade head`` and drops the database afterwards. Passwords are
synthetic and generated per test.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.auth.passwords import hash_password, verify_password
from app.auth.seed_admin import LEGACY_SEED_EMAILS, run
from app.infra.models import AccessLog, Meeting, MeetingRecoveryOperation, SummaryTemplate, TemplateCategory, User

BACKEND = Path(__file__).resolve().parents[2]
ADMIN_EMAIL = "admin@sauri.local"


def _asyncpg_args(url: str) -> dict[str, str | int]:
    parsed = make_url(url)
    args: dict[str, str | int] = {"user": parsed.username or "", "database": parsed.database or ""}
    if parsed.password is not None:
        args["password"] = parsed.password
    if parsed.host is not None:
        args["host"] = parsed.host
    if parsed.port is not None:
        args["port"] = parsed.port
    return args


@pytest.fixture(scope="module")
def migrated_url() -> Iterator[str]:
    url = os.environ.get("SAURI_QA_POSTGRES_URL")
    if not url:
        pytest.skip("requires disposable PostgreSQL URL in SAURI_QA_POSTGRES_URL")
    assert url.startswith("postgresql+asyncpg://") and "sauri_qa" in url
    db_name = f"sauri_qa_admin_{uuid.uuid4().hex}"
    admin_args = _asyncpg_args(url)

    async def admin(sql: str) -> None:
        connection = await asyncpg.connect(**admin_args)
        try:
            await connection.execute(sql)
        finally:
            await connection.close()

    asyncio.run(admin(f'CREATE DATABASE "{db_name}"'))
    target = make_url(url).set(database=db_name).render_as_string(hide_password=False)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = target
    try:
        command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
        yield target
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))


@pytest.fixture
async def factory(
    migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    engine = create_async_engine(migrated_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text(
            "TRUNCATE users, meetings, access_log, meeting_recovery_operations, "
            "template_categories, summary_templates CASCADE"
        ))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def password_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "admin_password"
    path.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("SAURI_ADMIN_PASSWORD_FILE", str(path))
    return path


def _secret(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


async def _admin(factory: async_sessionmaker[AsyncSession]) -> User | None:
    async with factory() as session:
        return await session.scalar(select(User).where(User.email == ADMIN_EMAIL))


async def _add_user(factory: async_sessionmaker[AsyncSession], email: str) -> str:
    user_id = str(uuid.uuid4())
    async with factory() as session, session.begin():
        session.add(User(
            id=user_id, email=email, name=email, password_hash=hash_password("synthetic-other-password"),
            is_sales=True, created_at=datetime.now(UTC),
        ))
    return user_id


async def _login(email: str, password: str) -> int:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.status_code


async def test_creates_admin_from_password_file_and_login_works(
    factory: async_sessionmaker[AsyncSession], password_file: Path,
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    assert await run([]) == 0

    admin = await _admin(factory)
    assert admin is not None and admin.is_sales and admin.name == "Administrador"
    assert verify_password(_secret(password_file), admin.password_hash)
    assert await _login(ADMIN_EMAIL, _secret(password_file)) == 200
    assert await _login(ADMIN_EMAIL, "wrong-password-wrong-password") == 401
    captured = capsys.readouterr()
    assert "created" in captured.out
    assert _secret(password_file) not in captured.out + captured.err + caplog.text


@pytest.mark.parametrize("content", [None, "", "\n", "short-password-19ch"])
async def test_refuses_missing_empty_or_short_password_file(
    factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], content: str | None,
) -> None:
    path = tmp_path / "admin_password"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SAURI_ADMIN_PASSWORD_FILE", str(path))

    assert await run([]) == 2
    assert await _admin(factory) is None
    captured = capsys.readouterr()
    assert "admin password file" in captured.err.lower()
    if content and content.strip():
        assert content.strip() not in captured.out + captured.err


async def test_is_idempotent_and_reset_password_replaces_it(
    factory: async_sessionmaker[AsyncSession], password_file: Path,
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    original = _secret(password_file)
    assert await run([]) == 0
    first = await _admin(factory)
    assert first is not None

    password_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    replacement = _secret(password_file)
    assert await run([]) == 0
    kept = await _admin(factory)
    assert kept is not None and kept.id == first.id and kept.password_hash == first.password_hash
    assert await _login(ADMIN_EMAIL, original) == 200

    assert await run(["--reset-password"]) == 0
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 1
    assert await _login(ADMIN_EMAIL, replacement) == 200
    assert await _login(ADMIN_EMAIL, original) == 401
    captured = capsys.readouterr()
    assert "password reset" in captured.out
    for secret in (original, replacement):
        assert secret not in captured.out + captured.err + caplog.text


async def test_retire_legacy_moves_ownership_deletes_legacy_and_is_a_noop_afterwards(
    factory: async_sessionmaker[AsyncSession], password_file: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_one = await _add_user(factory, LEGACY_SEED_EMAILS[0])
    legacy_two = await _add_user(factory, LEGACY_SEED_EMAILS[1])
    other = await _add_user(factory, "other@example.test")
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        for owner, meeting_id in ((legacy_one, "m-legacy-1"), (legacy_two, "m-legacy-2"), (other, "m-other")):
            session.add(Meeting(id=meeting_id, origin="manual", process_state="completed", created_by=owner,
                                created_at=now))
            session.add(AccessLog(id=str(uuid.uuid4()), user_id=owner, resource=meeting_id, result="allowed",
                                  occurred_at=now))
        await session.flush()
        session.add(MeetingRecoveryOperation(
            id="op-legacy", meeting_id="m-legacy-1", actor_id=legacy_one, idempotency_key="k" * 64,
            processing_generation=1, status="accepted", created_at=now, updated_at=now,
        ))
        for owner, suffix in ((legacy_two, "legacy"), (other, "other")):
            session.add(TemplateCategory(id=f"cat-{suffix}", owner_user_id=owner, name="General", created_at=now))
            await session.flush()
            session.add(SummaryTemplate(
                id=f"tpl-{suffix}", owner_user_id=owner, category_id=f"cat-{suffix}", name="Plantilla",
                instructions="synthetic", version=1, created_at=now, updated_at=now,
            ))
        await session.flush()
        legacy_user = await session.get(User, legacy_two)
        assert legacy_user is not None
        legacy_user.default_summary_template_id = "tpl-legacy"
    other_before = await _snapshot_user(factory, other)

    assert await run(["--retire-legacy"]) == 0
    first_output = capsys.readouterr().out
    assert "legacy_users_deleted=2" in first_output and "meetings=2" in first_output

    admin = await _admin(factory)
    assert admin is not None
    assert admin.default_summary_template_id == "tpl-legacy"
    async with factory() as session:
        emails = set((await session.scalars(select(User.email))).all())
        assert emails == {ADMIN_EMAIL, "other@example.test"}
        owners = dict((await session.execute(select(Meeting.id, Meeting.created_by))).all())
        assert owners == {"m-legacy-1": admin.id, "m-legacy-2": admin.id, "m-other": other}
        log_users = sorted((await session.scalars(select(AccessLog.user_id))).all(), key=str)
        assert log_users == sorted([admin.id, admin.id, other], key=str)
        assert await session.scalar(select(MeetingRecoveryOperation.actor_id)) == admin.id
        template_owners = dict((await session.execute(
            select(SummaryTemplate.id, SummaryTemplate.owner_user_id))).all())
        assert template_owners == {"tpl-legacy": admin.id, "tpl-other": other}
        category_owners = dict((await session.execute(
            select(TemplateCategory.id, TemplateCategory.owner_user_id))).all())
        assert category_owners == {"cat-legacy": admin.id, "cat-other": other}
    assert await _snapshot_user(factory, other) == other_before
    assert _secret(password_file) not in first_output

    assert await run(["--retire-legacy"]) == 0
    assert "legacy_users_deleted=0" in capsys.readouterr().out
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 2
    assert await _snapshot_user(factory, other) == other_before


async def _snapshot_user(factory: async_sessionmaker[AsyncSession], user_id: str) -> tuple[object, ...]:
    async with factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        return (user.email, user.name, user.password_hash, user.is_sales, user.default_summary_template_id)
