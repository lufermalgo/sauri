"""Read-only access to the Docker installation: PostgreSQL through `docker exec`, objects through S3.

Every command sent to a source container goes through `guarded_docker_exec`, which only lets through
the read-only programs and options this tool needs; the S3 wrapper only exposes listing and reading.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol

READ_ONLY_PGOPTIONS = "-c default_transaction_read_only=on"
FIELD_SEPARATOR = "\x1f"
QUEUE_PREFIXES = ("transcribe", "diarize", "summarize")
RABBITMQ_LIST_QUEUES = ["rabbitmqctl", "-q", "list_queues", "name", "messages"]
PG_DUMP_OPTIONS = frozenset({"--format=custom", "--no-sync"})
_SQL_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


class SourceSafetyError(RuntimeError):
    """A command that could change the source was about to be sent; nothing was run."""


class SourceError(RuntimeError):
    """The source could not be read."""


def guarded_docker_exec(container: str, argv: Sequence[str]) -> list[str]:
    """Build `docker exec` for one of the read-only commands; refuse anything else."""
    if not container or container.startswith("-"):
        raise SourceSafetyError("invalid source container name")
    if not argv:
        raise SourceSafetyError("empty command")
    program, *options = argv
    if program == "psql":
        _check_psql(options)
    elif program == "pg_dump":
        _check_pg_dump(options)
    elif program == "rabbitmqctl":
        if list(argv) != RABBITMQ_LIST_QUEUES:
            raise SourceSafetyError("only `rabbitmqctl -q list_queues name messages` is allowed")
    else:
        raise SourceSafetyError(f"program not allowed against the source: {program}")
    # PGOPTIONS makes every PostgreSQL session read-only, whatever the statement.
    return ["docker", "exec", "-e", f"PGOPTIONS={READ_ONLY_PGOPTIONS}", container, *argv]


def _check_psql(options: Sequence[str]) -> None:
    expected_prefix = ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-tA", "-F", FIELD_SEPARATOR, "-U"]
    if list(options[: len(expected_prefix)]) != expected_prefix or len(options) != len(expected_prefix) + 9:
        raise SourceSafetyError("unexpected psql options")
    user, d_flag, _db, c1, begin, c2, sql, c3, rollback = options[len(expected_prefix):]
    if (d_flag, c1, begin, c2, c3, rollback) != ("-d", "-c", "BEGIN TRANSACTION READ ONLY", "-c", "-c", "ROLLBACK"):
        raise SourceSafetyError("psql must run one statement inside a read-only transaction")
    if not user or user.startswith("-"):
        raise SourceSafetyError("invalid database user")
    if not _SQL_START.match(sql) or ";" in sql:
        raise SourceSafetyError("only a single SELECT statement is allowed")


def _check_pg_dump(options: Sequence[str]) -> None:
    # pg_dump never writes to the database; refusing -f also keeps it from writing inside the container.
    if len(options) < 4 or options[0] != "-U" or options[2] != "-d":
        raise SourceSafetyError("unexpected pg_dump options")
    if options[1].startswith("-") or options[3].startswith("-"):
        raise SourceSafetyError("invalid pg_dump user or database")
    extra = set(options[4:])
    if "--format=custom" not in extra or not extra <= PG_DUMP_OPTIONS:
        raise SourceSafetyError("pg_dump may only write a custom-format dump to stdout")


class Runner(Protocol):
    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]: ...

    def stream_to(self, argv: Sequence[str], destination: IO[bytes]) -> tuple[int, str]: ...


class SubprocessRunner:
    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(list(argv), capture_output=True, text=True, check=False)

    def stream_to(self, argv: Sequence[str], destination: IO[bytes]) -> tuple[int, str]:
        process = subprocess.Popen(list(argv), stdout=destination, stderr=subprocess.PIPE)
        _, stderr = process.communicate()
        return process.returncode, stderr.decode("utf-8", "replace")


def _container_state(runner: Runner, container: str) -> dict[str, Any] | None:
    result = runner.run(["docker", "inspect", "--type", "container", container])
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    return data[0] if data else None


def container_running(runner: Runner, container: str) -> bool:
    state = _container_state(runner, container)
    return bool(state and state.get("State", {}).get("Running"))


def published_ports(runner: Runner, container: str) -> set[int]:
    state = _container_state(runner, container) or {}
    ports: set[int] = set()
    for bindings in (state.get("NetworkSettings", {}).get("Ports") or {}).values():
        for binding in bindings or []:
            if str(binding.get("HostPort", "")).isdigit():
                ports.add(int(binding["HostPort"]))
    return ports


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


TABLES_SQL = (
    "SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
    " AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%' ORDER BY 1, 2"
)


def row_counts_sql(tables: Sequence[tuple[str, str]]) -> str:
    """One statement, so every count comes from the same snapshot."""
    parts = [
        f"SELECT '{schema}.{table}', count(*) FROM {quote_ident(schema)}.{quote_ident(table)}"
        for schema, table in tables
        if "'" not in schema and "'" not in table
    ]
    if len(parts) != len(tables):
        raise SourceError("a table name contains a quote; counting it is not supported")
    return " UNION ALL ".join(parts)


@dataclass
class DockerPostgres:
    container: str
    database: str = "sauri"
    user: str = "sauri"
    runner: Runner = field(default_factory=SubprocessRunner)

    def query(self, sql: str) -> list[list[str]]:
        argv = guarded_docker_exec(self.container, [
            "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-tA", "-F", FIELD_SEPARATOR, "-U", self.user,
            "-d", self.database, "-c", "BEGIN TRANSACTION READ ONLY", "-c", sql, "-c", "ROLLBACK",
        ])
        result = self.runner.run(argv)
        if result.returncode != 0:
            raise SourceError(f"source query failed: {result.stderr.strip()[:500]}")
        return [line.split(FIELD_SEPARATOR) for line in result.stdout.splitlines() if line.strip()]

    def scalar(self, sql: str) -> str:
        rows = self.query(sql)
        if len(rows) != 1 or len(rows[0]) != 1:
            raise SourceError("expected one value from the source")
        return rows[0][0]

    def running(self) -> bool:
        return container_running(self.runner, self.container)

    def published_ports(self) -> set[int]:
        return published_ports(self.runner, self.container)

    def server_major(self) -> int:
        return int(self.scalar("SELECT current_setting('server_version_num')::int / 10000"))

    def system_identifier(self) -> str:
        return self.scalar("SELECT system_identifier::text FROM pg_control_system()")

    def database_bytes(self) -> int:
        return int(self.scalar("SELECT pg_database_size(current_database())"))

    def alembic_revision(self) -> str | None:
        if self.scalar("SELECT to_regclass('public.alembic_version') IS NOT NULL") != "t":
            return None
        rows = self.query("SELECT version_num FROM public.alembic_version")
        if len(rows) != 1:
            raise SourceError("the source has no single alembic revision")
        return rows[0][0]

    def tables(self) -> list[tuple[str, str]]:
        return [(row[0], row[1]) for row in self.query(TABLES_SQL)]

    def row_counts(self) -> dict[str, int]:
        tables = self.tables()
        if not tables:
            return {}
        return {row[0]: int(row[1]) for row in self.query(row_counts_sql(tables))}

    def inflight(self, inflight_query: str) -> list[list[str]]:
        sql = (
            "SELECT kind, meeting_id, state, coalesce(to_char(since AT TIME ZONE 'UTC',"
            f" 'YYYY-MM-DD HH24:MI'), '?') FROM ({inflight_query}) AS inflight ORDER BY 1, 4"
        )
        return self.query(sql)

    def dump(self, destination: Path) -> int:
        """Stream `pg_dump -Fc` from inside the container to a local file; return its size."""
        argv = guarded_docker_exec(self.container, [
            "pg_dump", "-U", self.user, "-d", self.database, "--format=custom", "--no-sync",
        ])
        with destination.open("wb") as output:
            code, stderr = self.runner.stream_to(argv, output)
            output.flush()
            os.fsync(output.fileno())
        if code != 0:
            raise SourceError(f"pg_dump failed: {stderr.strip()[:500]}")
        size = destination.stat().st_size
        if size == 0:
            raise SourceError("pg_dump produced an empty file")
        return size


def queue_backlog(runner: Runner, container: str | None) -> list[str]:
    """Messages waiting in the processing queues; a stopped broker holds none that can be delivered now."""
    if not container or not container_running(runner, container):
        return []
    result = runner.run(guarded_docker_exec(container, RABBITMQ_LIST_QUEUES))
    if result.returncode != 0:
        raise SourceError(f"could not list the broker queues: {result.stderr.strip()[:300]}")
    backlog: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        name, count = parts[0], int(parts[1])
        if count > 0 and any(name == p or name.startswith(p + ".") for p in QUEUE_PREFIXES):
            backlog.append(f"queue {name}: {count} message(s)")
    return backlog


@dataclass(frozen=True)
class SourceObject:
    key: str
    size: int
    etag: str


def read_key_file(path: Path) -> str:
    value = path.expanduser().read_text(encoding="utf-8").strip()
    if not value:
        raise SourceError(f"empty key file: {path}")
    return value


class S3Source:
    """Listing and reading only; the client is private so no write call can be reached from here."""

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, client: Any = None) -> None:
        self.endpoint = endpoint
        self.bucket = bucket
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3", endpoint_url=endpoint, aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}),
                region_name="us-east-1",
            )
        self._client = client

    def check_bucket(self) -> None:
        self._client.head_bucket(Bucket=self.bucket)

    def list_objects(self) -> list[SourceObject]:
        objects: list[SourceObject] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for item in page.get("Contents", []) or []:
                objects.append(SourceObject(str(item["Key"]), int(item["Size"]), str(item.get("ETag", ""))))
        return sorted(objects, key=lambda item: item.key)

    def open(self, key: str) -> IO[bytes]:
        body: IO[bytes] = self._client.get_object(Bucket=self.bucket, Key=key)["Body"]
        return body

    def iter_chunks(self, key: str, size: int = 1024 * 1024) -> Iterator[bytes]:
        body = self.open(key)
        try:
            while chunk := body.read(size):
                yield chunk
        finally:
            body.close()
