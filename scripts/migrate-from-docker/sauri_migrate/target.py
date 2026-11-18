"""The app's PostgreSQL: connection details, preparing an empty database, restoring and migrating it."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy.engine import make_url

from .source import TABLES_SQL, row_counts_sql

BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
# Marks a database this tool is filling; a later attempt may replace it only while the mark is there.
IN_PROGRESS_MARK = "sauri migrate-from-docker: in progress"


class TargetError(RuntimeError):
    """The target cannot receive the migration as it is."""


@dataclass(frozen=True)
class PgTarget:
    host: str
    port: int
    user: str
    password: str | None
    database: str

    @classmethod
    def from_url(cls, url: str) -> PgTarget:
        parsed = make_url(url)
        if not parsed.drivername.startswith("postgresql"):
            raise TargetError("the target must be a PostgreSQL URL")
        host = parsed.host or str(parsed.query.get("host") or "")
        port = parsed.port or int(str(parsed.query.get("port") or 5432))
        if not host or not parsed.username or not parsed.database:
            raise TargetError("the target URL must name a host (or socket folder), a user and a database")
        return cls(host, port, parsed.username, parsed.password, parsed.database)

    @property
    def is_socket(self) -> bool:
        return self.host.startswith("/")

    @property
    def loopback_port(self) -> int | None:
        return self.port if self.host in {"127.0.0.1", "localhost", "::1"} else None

    def asyncpg_url(self) -> str:
        """The URL alembic's env.py expects (password included; it travels only in the child's environment)."""
        from sqlalchemy.engine import URL

        query = {"host": self.host} if self.is_socket else {}
        return URL.create(
            "postgresql+asyncpg", username=self.user, password=self.password,
            host=None if self.is_socket else self.host, port=self.port,
            database=self.database, query=query,
        ).render_as_string(hide_password=False)

    def libpq_args(self, database: str | None = None) -> list[str]:
        return ["-h", self.host, "-p", str(self.port), "-U", self.user, "-d", database or self.database]

    def libpq_env(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        if self.password:
            env["PGPASSWORD"] = self.password
        return env

    async def connect(self, database: str | None = None) -> Any:
        return await asyncpg.connect(
            host=self.host, port=self.port, user=self.user, password=self.password,
            database=database or self.database, timeout=15,
        )


async def _fetch(target: PgTarget, sql: str, *args: Any, database: str | None = None) -> list[Any]:
    connection = await target.connect(database)
    try:
        return list(await connection.fetch(sql, *args))
    finally:
        await connection.close()


def run_sync(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


@dataclass(frozen=True)
class TargetState:
    exists: bool
    table_count: int
    meetings: int | None
    users: int | None
    in_progress_mark: bool


async def inspect_target(target: PgTarget) -> TargetState:
    rows = await _fetch(
        target, "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = $1",
        target.database, database="postgres",
    )
    if not rows:
        return TargetState(False, 0, None, None, False)
    mark = rows[0][0] == IN_PROGRESS_MARK
    connection = await target.connect()
    try:
        tables = [(r[0], r[1]) for r in await connection.fetch(TABLES_SQL)]
        names = {f"{schema}.{table}" for schema, table in tables}
        meetings = await connection.fetchval("SELECT count(*) FROM public.meetings") if (
            "public.meetings" in names) else None
        users = await connection.fetchval("SELECT count(*) FROM public.users") if "public.users" in names else None
    finally:
        await connection.close()
    return TargetState(True, len(tables), meetings, users, mark)


def target_problem(state: TargetState, replace_fresh_app: bool, replace_unfinished: bool) -> str | None:
    """Why the target cannot be used as it is, or None when it is empty, missing or replaceable."""
    if not state.exists or state.table_count == 0:
        return None
    if state.in_progress_mark:
        return None if replace_unfinished else (
            "the target holds an unfinished earlier attempt; run again with --replace-unfinished")
    if (state.meetings or 0) == 0 and (state.users or 0) <= 1:
        return None if replace_fresh_app else (
            "the target holds a freshly set-up app without meetings; run again with --replace-fresh-app-db")
    return "the target database already holds data (meetings or several users); it is never replaced"


async def system_identifier(target: PgTarget) -> str:
    rows = await _fetch(target, "SELECT system_identifier::text FROM pg_control_system()", database="postgres")
    return str(rows[0][0])


async def server_major(target: PgTarget) -> int:
    rows = await _fetch(target, "SELECT current_setting('server_version_num')::int / 10000", database="postgres")
    return int(rows[0][0])


async def data_directory(target: PgTarget) -> Path | None:
    try:
        rows = await _fetch(target, "SELECT current_setting('data_directory')", database="postgres")
    except asyncpg.PostgresError:
        return None
    return Path(rows[0][0]) if rows else None


async def recreate_database(target: PgTarget, state: TargetState) -> None:
    """Create the target database empty, dropping it first only in the cases `target_problem` allows."""
    connection = await target.connect("postgres")
    name = '"' + target.database.replace('"', '""') + '"'
    try:
        drop = state.exists and state.table_count > 0
        if drop:
            await connection.execute(f"DROP DATABASE {name} WITH (FORCE)")
        if drop or not state.exists:
            await connection.execute(f"CREATE DATABASE {name} TEMPLATE template0 ENCODING 'UTF8'")
        await connection.execute(f"COMMENT ON DATABASE {name} IS '{IN_PROGRESS_MARK}'")
    finally:
        await connection.close()


async def clear_in_progress_mark(target: PgTarget) -> None:
    connection = await target.connect("postgres")
    try:
        name = '"' + target.database.replace('"', '""') + '"'
        await connection.execute(f"COMMENT ON DATABASE {name} IS NULL")
    finally:
        await connection.close()


async def row_counts(target: PgTarget) -> dict[str, int]:
    connection = await target.connect()
    try:
        tables = [(r[0], r[1]) for r in await connection.fetch(TABLES_SQL)]
        if not tables:
            return {}
        return {str(r[0]): int(r[1]) for r in await connection.fetch(row_counts_sql(tables))}
    finally:
        await connection.close()


async def alembic_revision(target: PgTarget) -> str | None:
    connection = await target.connect()
    try:
        if not await connection.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL"):
            return None
        rows = await connection.fetch("SELECT version_num FROM public.alembic_version")
    finally:
        await connection.close()
    return str(rows[0][0]) if len(rows) == 1 else None


async def user_id_by_email(target: PgTarget, email: str) -> str | None:
    rows = await _fetch(target, "SELECT id FROM public.users WHERE email = $1", email)
    return str(rows[0][0]) if rows else None


def find_pg_tool(name: str, pg_bin: str | None) -> Path:
    if pg_bin:
        candidate = Path(pg_bin).expanduser() / name
        if not os.access(candidate, os.X_OK):
            raise TargetError(f"{name} not found in {pg_bin}")
        return candidate
    found = shutil.which(name)
    if not found:
        raise TargetError(f"{name} not found; set PG_BIN to the PostgreSQL 16 bin folder")
    return Path(found)


def tool_major(tool: Path) -> int:
    output = subprocess.run([str(tool), "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"\b(\d+)\.\d+", output)
    if not match:
        raise TargetError(f"cannot read the version of {tool}")
    return int(match.group(1))


def restore(target: PgTarget, pg_restore: Path, dump: Path) -> None:
    """Restore in one transaction: a failure leaves the target database empty."""
    argv = [str(pg_restore), "--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction",
            *target.libpq_args(), str(dump)]
    result = subprocess.run(argv, capture_output=True, text=True, env=target.libpq_env(), check=False)
    if result.returncode != 0:
        raise TargetError(f"pg_restore failed: {result.stderr.strip()[:800]}")


def alembic_script() -> Any:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config)


def alembic_head() -> str:
    heads: Sequence[str] = alembic_script().get_heads()
    if len(heads) != 1:
        raise TargetError(f"expected one alembic head, found {len(heads)}")
    return heads[0]


def known_revision(revision: str) -> bool:
    try:
        return alembic_script().get_revision(revision) is not None
    except Exception:
        return False


def alembic_upgrade(target: PgTarget) -> None:
    env = {key: value for key, value in os.environ.items() if key not in {"DATABASE_URL", "DATABASE_PASSWORD_FILE"}}
    env["DATABASE_URL"] = target.asyncpg_url()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(BACKEND_DIR / "alembic.ini"), "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise TargetError(f"alembic upgrade head failed: {result.stderr.strip()[-800:]}")
