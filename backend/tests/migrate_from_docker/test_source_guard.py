"""Everything sent to the Docker source is read-only; anything else is refused before it runs."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import IO

import pytest
from sauri_migrate.source import (  # noqa: E402
    FIELD_SEPARATOR,
    RABBITMQ_LIST_QUEUES,
    READ_ONLY_PGOPTIONS,
    DockerPostgres,
    SourceSafetyError,
    guarded_docker_exec,
    queue_backlog,
    row_counts_sql,
)

from tests.migrate_from_docker import TOOL_DIR  # noqa: F401  (puts the tool on sys.path)


def psql(sql: str) -> list[str]:
    return ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-tA", "-F", FIELD_SEPARATOR, "-U", "sauri", "-d",
            "sauri", "-c", "BEGIN TRANSACTION READ ONLY", "-c", sql, "-c", "ROLLBACK"]


class FakeRunner:
    def __init__(self, outputs: dict[str, str] | None = None, running: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.outputs = outputs or {}
        self.running = running

    def run(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        if argv[:2] == ["docker", "inspect"]:
            state = '[{"State": {"Running": %s}}]' % ("true" if self.running else "false")
            return subprocess.CompletedProcess(list(argv), 0, state, "")
        for marker, output in self.outputs.items():
            if any(marker in part for part in argv):
                return subprocess.CompletedProcess(list(argv), 0, output, "")
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    def stream_to(self, argv: Sequence[str], destination: IO[bytes]) -> tuple[int, str]:
        self.calls.append(list(argv))
        destination.write(b"PGDMP-synthetic")
        return 0, ""


def test_read_only_commands_carry_the_read_only_session_option() -> None:
    argv = guarded_docker_exec("sauri-postgres-1", psql("SELECT 1"))
    assert argv[:5] == ["docker", "exec", "-e", f"PGOPTIONS={READ_ONLY_PGOPTIONS}", "sauri-postgres-1"]
    dump = guarded_docker_exec("c", ["pg_dump", "-U", "sauri", "-d", "sauri", "--format=custom", "--no-sync"])
    assert dump[5:] == ["pg_dump", "-U", "sauri", "-d", "sauri", "--format=custom", "--no-sync"]
    assert guarded_docker_exec("rabbit", RABBITMQ_LIST_QUEUES)[-5:] == RABBITMQ_LIST_QUEUES


@pytest.mark.parametrize(
    "argv",
    [
        ["dropdb", "sauri"],
        ["sh", "-c", "rm -rf /var/lib/postgresql/data"],
        psql("DELETE FROM meetings"),
        psql("SELECT 1; DROP TABLE meetings"),
        psql("UPDATE users SET name = 'x'"),
        ["psql", "-U", "sauri", "-d", "sauri", "-c", "SELECT 1"],  # outside a read-only transaction
        ["pg_dump", "-U", "sauri", "-d", "sauri", "--format=custom", "--clean"],
        ["pg_dump", "-U", "sauri", "-d", "sauri", "--format=custom", "-f", "/var/lib/postgresql/data/x"],
        ["pg_dump", "-U", "sauri", "-d", "sauri"],
        ["rabbitmqctl", "delete_queue", "transcribe"],
        ["rabbitmqctl", "-q", "purge_queue", "transcribe"],
    ],
)
def test_anything_that_could_change_the_source_is_refused(argv: list[str]) -> None:
    with pytest.raises(SourceSafetyError):
        guarded_docker_exec("sauri-postgres-1", argv)


def test_container_name_cannot_smuggle_docker_options() -> None:
    with pytest.raises(SourceSafetyError):
        guarded_docker_exec("--privileged", psql("SELECT 1"))


def test_queries_and_dump_go_through_the_guard(tmp_path: Path) -> None:
    runner = FakeRunner({"count(*)": f"public.meetings{FIELD_SEPARATOR}3\npublic.users{FIELD_SEPARATOR}1\n",
                         "pg_class": f"public{FIELD_SEPARATOR}meetings\npublic{FIELD_SEPARATOR}users\n"})
    source = DockerPostgres("sauri-qa", runner=runner)
    assert source.row_counts() == {"public.meetings": 3, "public.users": 1}
    dump = tmp_path / "x.dump"
    assert source.dump(dump) == len(b"PGDMP-synthetic")
    for call in runner.calls:
        assert call[:4] == ["docker", "exec", "-e", f"PGOPTIONS={READ_ONLY_PGOPTIONS}"]


def test_row_counts_use_one_statement_with_quoted_names() -> None:
    sql = row_counts_sql([("public", "meetings"), ("public", 'odd"name')])
    assert sql.count("UNION ALL") == 1 and '"odd""name"' in sql


def test_queue_backlog_counts_only_processing_queues_with_messages() -> None:
    runner = FakeRunner({"list_queues": "transcribe\t2\ntranscribe.retry\t1\nsummarize\t0\njoin\t9\nother\t4\n"})
    assert queue_backlog(runner, "rabbit") == ["queue transcribe: 2 message(s)", "queue transcribe.retry: 1 message(s)"]
    assert queue_backlog(FakeRunner(running=False), "rabbit") == []
    assert queue_backlog(runner, None) == []
