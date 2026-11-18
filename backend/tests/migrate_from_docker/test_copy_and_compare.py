"""Object copy, inventory, free space and the property-8 comparison, without any service."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from sauri_migrate import target as tgt  # noqa: E402
from sauri_migrate.checks import SpaceNeed, check_space, compare_objects, compare_rows  # noqa: E402
from sauri_migrate.cli import build_parser, config_problems, write_local_user  # noqa: E402
from sauri_migrate.objects import ObjectCopyError, ObjectRecord, copy_object, etag_md5, scan_tree  # noqa: E402

from tests.migrate_from_docker import TOOL_DIR  # noqa: F401  (puts the tool on sys.path)

KEY = "recordings/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222/audio"


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def chunks(data: bytes, size: int = 7) -> list[bytes]:
    return [data[i:i + size] for i in range(0, len(data), size)]


def test_etag_md5_only_for_single_part_uploads() -> None:
    assert etag_md5('"9E107D9D372BB6826BD81D3542A419D6"') == "9e107d9d372bb6826bd81d3542a419d6"
    assert etag_md5('"9e107d9d372bb6826bd81d3542a419d6-3"') is None
    assert etag_md5("") is None


def test_copy_writes_the_exact_bytes_at_the_app_path(tmp_path: Path) -> None:
    data = os.urandom(1000)
    record, wrote = copy_object(chunks(data), tmp_path, KEY, len(data), md5(data))
    assert wrote and record == ObjectRecord(KEY, len(data), md5(data))
    assert (tmp_path / KEY).read_bytes() == data
    assert scan_tree(tmp_path) == {KEY: record}


def test_a_mismatch_leaves_no_file_and_no_partial(tmp_path: Path) -> None:
    data = b"synthetic audio"
    with pytest.raises(ObjectCopyError):
        copy_object(chunks(data), tmp_path, KEY, len(data), md5(b"other"))
    with pytest.raises(ObjectCopyError):
        copy_object(chunks(data), tmp_path, KEY, len(data) + 1, None)
    assert not (tmp_path / KEY).exists()
    assert list((tmp_path / KEY).parent.iterdir()) == []


def test_an_identical_file_is_kept_and_a_different_one_never_overwritten(tmp_path: Path) -> None:
    data = b"synthetic video"
    copy_object(chunks(data), tmp_path, KEY, len(data), md5(data))
    _, wrote = copy_object(chunks(data), tmp_path, KEY, len(data), md5(data))
    assert not wrote
    (tmp_path / KEY).write_bytes(b"something else")
    with pytest.raises(ObjectCopyError):
        copy_object(chunks(data), tmp_path, KEY, len(data), md5(data))
    assert (tmp_path / KEY).read_bytes() == b"something else"


@pytest.mark.parametrize("key", ["../escape", "/abs/key", "recordings//x", "recordings/./x", ""])
def test_keys_cannot_escape_the_recordings_folder(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        copy_object([b"x"], tmp_path / "root", key, 1, None)


def test_scan_skips_markers_and_partial_writes(tmp_path: Path) -> None:
    (tmp_path / ".sauri-folder").write_text("id")
    (tmp_path / "recordings" / "m").mkdir(parents=True)
    (tmp_path / "recordings" / "m" / ".audio.abc.part").write_bytes(b"partial")
    (tmp_path / "recordings" / "m" / "audio").write_bytes(b"a")
    assert list(scan_tree(tmp_path)) == ["recordings/m/audio"]


def test_needs_on_the_same_volume_add_up(tmp_path: Path) -> None:
    gib = 1024 ** 3
    needs = [SpaceNeed("dump", tmp_path / "work", gib), SpaceNeed("recordings", tmp_path / "rec", 2 * gib)]
    (check,) = check_space(needs, free_bytes=lambda _: 3 * gib, device=lambda _: 1)
    assert check.labels == ["dump", "recordings"] and not check.enough
    (tmp_path / "work").mkdir()
    (tmp_path / "rec").mkdir()
    checks = check_space(needs, free_bytes=lambda _: 3 * gib, device=lambda path: {"work": 1, "rec": 2}[path.name])
    assert [c.labels for c in checks] == [["dump"], ["recordings"]] and all(c.enough for c in checks)


def test_rows_must_match_and_new_tables_must_be_empty() -> None:
    source = {"public.meetings": 3, "public.users": 1, "public.alembic_version": 1}
    target = {**source, "public.job_messages": 0}
    assert compare_rows(source, source, target) == []
    kinds = {d.kind for d in compare_rows(source, {**source, "public.meetings": 4},
                                          {**target, "public.users": 0, "public.job_messages": 2})}
    assert kinds == {"source_changed_rows", "row_count", "new_table_not_empty"}
    assert [d.kind for d in compare_rows(source, source, {"public.users": 1, "public.alembic_version": 1})] == [
        "table_missing_in_target"]


def test_objects_must_match_on_key_size_and_md5() -> None:
    expected = {"a": ObjectRecord("a", 1, "x"), "b": ObjectRecord("b", 2, "y"), "c": ObjectRecord("c", 3, "z")}
    listing = {"a": (1, "x"), "b": (2, "y"), "c": (3, "z")}
    assert compare_objects(expected, listing, listing, dict(expected)) == []
    found = {"a": ObjectRecord("a", 1, "tampered"), "b": ObjectRecord("b", 5, "y"), "d": ObjectRecord("d", 1, "w")}
    kinds = [d.kind for d in compare_objects(expected, {**listing, "c": (3, "new")}, listing, found)]
    assert kinds == ["source_changed_object", "object_md5", "object_size", "object_missing_in_target",
                     "object_extra_in_target"]


@pytest.mark.parametrize(
    ("state", "fresh", "unfinished", "allowed"),
    [
        (tgt.TargetState(False, 0, None, None, False), False, False, True),
        (tgt.TargetState(True, 0, None, None, False), False, False, True),
        (tgt.TargetState(True, 30, 0, 1, False), False, False, False),
        (tgt.TargetState(True, 30, 0, 1, False), True, False, True),
        (tgt.TargetState(True, 30, 5, 2, True), False, False, False),
        (tgt.TargetState(True, 30, 5, 2, True), False, True, True),
        (tgt.TargetState(True, 30, 1, 1, False), True, True, False),
        (tgt.TargetState(True, 30, 0, 2, False), True, True, False),
    ],
)
def test_the_target_is_replaced_only_when_it_holds_nothing_of_value(
    state: tgt.TargetState, fresh: bool, unfinished: bool, allowed: bool,
) -> None:
    assert (tgt.target_problem(state, fresh, unfinished) is None) is allowed


def test_app_socket_url_is_understood() -> None:
    target = tgt.PgTarget.from_url("postgresql+asyncpg://sauri:pw@/sauri?host=/Users/x/Library/Sauri/run")
    assert (target.host, target.port, target.user, target.database) == ("/Users/x/Library/Sauri/run", 5432,
                                                                         "sauri", "sauri")
    assert target.loopback_port is None
    assert target.libpq_env()["PGPASSWORD"] == "pw"
    assert "pw" not in " ".join(target.libpq_args())
    assert tgt.PgTarget.from_url(target.asyncpg_url()) == target
    tcp = tgt.PgTarget.from_url("postgresql+asyncpg://postgres:pw@127.0.0.1:5432/sauri")
    assert tcp.loopback_port == 5432 and tgt.PgTarget.from_url(tcp.asyncpg_url()) == tcp


def test_local_user_is_written_without_losing_other_settings(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"schemaVersion": 1, "installId": "i", "paths": {"recordings": str(tmp_path)},
                                  "localUserId": "old"}))
    config.chmod(0o600)
    write_local_user(config, "new-id")
    data = json.loads(config.read_text())
    assert data == {"schemaVersion": 1, "installId": "i", "paths": {"recordings": str(tmp_path)},
                    "localUserId": "new-id"}
    assert config.stat().st_mode & 0o777 == 0o600
    assert config_problems(config, tmp_path) == []
    assert config_problems(config, tmp_path / "elsewhere") != []


def test_cli_needs_exactly_one_mode_and_knows_no_other_options() -> None:
    parser = build_parser()
    for argv in ([], ["--dry-run", "--run"], ["--run", "--drop-source"], ["--run", "--pg-dump-args", "--clean"]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
    assert parser.parse_args(["--verify"]).verify
