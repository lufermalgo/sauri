"""Command line: `--dry-run` reports what would be copied; `--run` copies, verifies and writes the report."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import target as tgt
from .checks import Difference, SpaceCheck, SpaceNeed, check_space, compare_objects, compare_rows
from .objects import ObjectCopyError, ObjectRecord, copy_object, etag_md5, scan_tree, target_path
from .source import (
    DockerPostgres,
    S3Source,
    SourceError,
    SourceObject,
    SourceSafetyError,
    SubprocessRunner,
    container_running,
    queue_backlog,
    read_key_file,
)

TOOL_VERSION = 1
HOME = Path.home()
DEFAULT_REPORT_DIR = HOME / "Library" / "Logs" / "Sauri"
DEFAULT_WORK_DIR = HOME / "Library" / "Caches" / "Sauri" / "migrate-from-docker"


def _none_list(value: str) -> list[str]:
    return [] if value.strip().lower() in {"", "none"} else [part.strip() for part in value.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    env = os.environ.get
    parser = argparse.ArgumentParser(
        prog="migrate.py", allow_abbrev=False,
        description="Copy the Docker installation's database and recordings into the desktop app (read-only "
                    "against Docker). Use --dry-run first.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report what would be copied; change nothing")
    mode.add_argument("--run", action="store_true", help="copy, verify and write the report")
    mode.add_argument("--verify", action="store_true",
                      help="compare an earlier migration with the source again; change nothing")
    source = parser.add_argument_group("source (Docker installation, read only)")
    source.add_argument("--source-container", default=env("SAURI_MIGRATE_SOURCE_CONTAINER", "sauri-postgres-1"))
    source.add_argument("--source-database", default="sauri")
    source.add_argument("--source-user", default="sauri")
    source.add_argument("--rabbitmq-container", default=env("SAURI_MIGRATE_RABBITMQ_CONTAINER", "sauri-rabbitmq-1"),
                        help="broker whose processing queues must be empty ('none' to skip)")
    source.add_argument("--writer-containers", default=env("SAURI_MIGRATE_WRITER_CONTAINERS",
                                                           "sauri-api-1,sauri-worker-1"),
                        help="containers that must be stopped so nothing writes during the copy ('none' to skip)")
    source.add_argument("--s3-endpoint", default=env("SAURI_MIGRATE_S3_ENDPOINT", "http://127.0.0.1:9000"))
    source.add_argument("--s3-bucket", default=env("SAURI_MIGRATE_S3_BUCKET", "sauri-recordings"))
    source.add_argument("--s3-access-key-file", type=Path,
                        default=Path(env("SAURI_MIGRATE_S3_ACCESS_KEY_FILE",
                                         str(HOME / ".config/sauri/object_store_access_key"))))
    source.add_argument("--s3-secret-key-file", type=Path,
                        default=Path(env("SAURI_MIGRATE_S3_SECRET_KEY_FILE",
                                         str(HOME / ".config/sauri/object_store_secret_key"))))
    target = parser.add_argument_group("target (the app)")
    target.add_argument("--target-url", default=env("DATABASE_URL"),
                        help="app database URL (default $DATABASE_URL; password from DATABASE_PASSWORD_FILE)")
    target.add_argument("--recordings", type=Path, default=env("SAURI_RECORDINGS_DIR"),
                        help="the app's recordings folder (default $SAURI_RECORDINGS_DIR)")
    target.add_argument("--target-data-dir", type=Path, help="PostgreSQL data folder, for the free-space check")
    target.add_argument("--config", type=Path, help="the app's config.json; receives localUserId after success")
    target.add_argument("--local-user-email", default="admin@sauri.local")
    target.add_argument("--replace-fresh-app-db", action="store_true",
                        help="replace a target that only holds a fresh setup (no meetings, one user at most)")
    target.add_argument("--replace-unfinished", action="store_true",
                        help="replace a target left by an earlier attempt of this tool that did not finish")
    other = parser.add_argument_group("other")
    other.add_argument("--pg-bin", default=env("PG_BIN"), help="PostgreSQL 16 bin folder with pg_restore")
    other.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR, help="where the dump is kept meanwhile")
    other.add_argument("--keep-dump", action="store_true", help="keep the dump file after the run")
    other.add_argument("--report", type=Path, help="report path (default ~/Library/Logs/Sauri/...)")
    return parser


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


@dataclass
class Report:
    mode: str
    data: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    differences: list[Difference] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": "migrate-from-docker", "tool_version": TOOL_VERSION, "mode": self.mode, **self.data,
            "problems": self.problems, "differences": [d.as_dict() for d in self.differences],
        }


def resolve_target_url(raw: str | None) -> str:
    from app.infra.secrets import read_secret, with_password

    if not raw:
        raise tgt.TargetError("give --target-url or set DATABASE_URL")
    if tgt.PgTarget.from_url(raw).password:
        return raw
    return with_password(raw, read_secret("DATABASE_PASSWORD_FILE"))


@dataclass
class Context:
    args: argparse.Namespace
    source: DockerPostgres
    s3: S3Source
    target: tgt.PgTarget
    recordings: Path


@dataclass
class Inventory:
    source_revision: str | None = None
    head: str = ""
    source_rows: dict[str, int] = field(default_factory=dict)
    source_bytes: int = 0
    objects: list[SourceObject] = field(default_factory=list)
    target_state: tgt.TargetState | None = None
    space: list[SpaceCheck] = field(default_factory=list)


def preflight(ctx: Context, report: Report) -> Inventory:
    """Every check that needs no change anywhere; blocking findings go to `report.problems`."""
    args, source, inv = ctx.args, ctx.source, Inventory()
    problems = report.problems
    runner = source.runner
    if not source.running():
        raise SourceError(f"the source container is not running: {source.container}")
    for name in _none_list(args.writer_containers):
        if container_running(runner, name):
            problems.append(f"{name} is running: stop it first so nothing writes during the copy")
    major = source.server_major()
    pg_restore = tgt.find_pg_tool("pg_restore", args.pg_bin)
    if tgt.tool_major(pg_restore) < major:
        problems.append(f"pg_restore is older than the source PostgreSQL {major}")
    inv.head = tgt.alembic_head()
    inv.source_revision = source.alembic_revision()
    if inv.source_revision is None or not tgt.known_revision(inv.source_revision):
        problems.append(f"the source schema revision is not one this code knows: {inv.source_revision}")

    from app.local.inflight import INFLIGHT_QUERY

    inflight = source.inflight(INFLIGHT_QUERY)
    brokers = _none_list(args.rabbitmq_container)
    backlog = queue_backlog(runner, brokers[0] if brokers else None)
    if inflight or backlog:
        listed = [f"{row[0]} {row[1][:8]} {row[2]} (since {row[3]} UTC)" for row in inflight] + backlog
        problems.append("work is in flight in the Docker installation; wait for it to finish: " + "; ".join(listed))
    report.data["inflight"] = {"items": len(inflight), "queue_backlog": len(backlog)}

    if ctx.target.loopback_port is not None and ctx.target.loopback_port in source.published_ports():
        raise SourceSafetyError("the target URL points to the Docker database itself")
    source_id = source.system_identifier()
    if tgt.run_sync(tgt.system_identifier(ctx.target)) == source_id:
        raise SourceSafetyError("the target server is the source server")
    if tgt.run_sync(tgt.server_major(ctx.target)) < major:
        problems.append(f"the target PostgreSQL is older than the source PostgreSQL {major}")
    inv.target_state = tgt.run_sync(tgt.inspect_target(ctx.target))
    problem = tgt.target_problem(inv.target_state, args.replace_fresh_app_db, args.replace_unfinished)
    if problem:
        problems.append(problem)
    if args.config is not None:
        problems.extend(config_problems(args.config, ctx.recordings))

    inv.source_rows = source.row_counts()
    inv.source_bytes = source.database_bytes()
    ctx.s3.check_bucket()
    inv.objects = ctx.s3.list_objects()
    bad_keys = 0
    for item in inv.objects:
        try:
            target_path(ctx.recordings, item.key)
        except ValueError:
            bad_keys += 1
    if bad_keys:
        problems.append(f"{bad_keys} object key(s) cannot be stored as files safely")
    multipart = sum(1 for item in inv.objects if etag_md5(item.etag) is None)
    object_bytes = sum(item.size for item in inv.objects)

    data_dir = args.target_data_dir or tgt.run_sync(tgt.data_directory(ctx.target))
    needs = [SpaceNeed("dump", args.work_dir, inv.source_bytes),
             SpaceNeed("recordings", ctx.recordings, object_bytes)]
    if data_dir is not None:
        needs.append(SpaceNeed("database", data_dir, inv.source_bytes))
    inv.space = check_space(needs)
    for check in inv.space:
        if not check.enough:
            problems.append(
                f"not enough free space on the volume of {check.path} for {', '.join(check.labels)}: needs "
                f"{human(check.required_bytes)}, has {human(check.available_bytes)}")

    report.data.update({
        "source": {"container": source.container, "database": source.database, "postgres_major": major,
                   "bucket": ctx.s3.bucket, "alembic_revision": inv.source_revision,
                   "database_bytes": inv.source_bytes},
        "target": {"database": ctx.target.database, "alembic_head": inv.head,
                   "state": vars(inv.target_state) if inv.target_state else None,
                   "data_directory_checked": data_dir is not None},
        "tables": {name: {"source": count} for name, count in sorted(inv.source_rows.items())},
        "objects": {"source_count": len(inv.objects), "source_bytes": object_bytes,
                    "without_md5_etag": multipart},
        "space": [{"labels": c.labels, "required_bytes": c.required_bytes,
                   "available_bytes": c.available_bytes, "enough": c.enough} for c in inv.space],
    })
    return inv


def config_problems(config: Path, recordings: Path) -> list[str]:
    try:
        data = json.loads(config.expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"cannot read the app configuration at {config}"]
    paths = data.get("paths") if isinstance(data, dict) else None
    configured = paths.get("recordings") if isinstance(paths, dict) else None
    if configured and Path(configured).expanduser().resolve() != recordings.expanduser().resolve():
        return ["--recordings is not the recordings folder in the app configuration"]
    return []


def write_local_user(config: Path, user_id: str) -> None:
    path = config.expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["localUserId"] = user_id
    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".config.", suffix=".tmp",
                                     delete=False, encoding="utf-8") as output:
        json.dump(data, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.chmod(output.name, mode)
    os.replace(output.name, path)


def copy_all(ctx: Context, objects: Sequence[SourceObject], report: Report) -> dict[str, ObjectRecord]:
    expected: dict[str, ObjectRecord] = {}
    written = kept = 0
    last = time.monotonic()
    for index, item in enumerate(objects, 1):
        md5 = etag_md5(item.etag)
        try:
            record, wrote = copy_object(ctx.s3.iter_chunks(item.key), ctx.recordings, item.key, item.size, md5)
        except ObjectCopyError as exc:
            report.differences.append(Difference("object_copy_failed", item.key, str(exc)))
            expected[item.key] = ObjectRecord(item.key, item.size, md5 or "unknown")
            continue
        expected[item.key] = record
        written += wrote
        kept += not wrote
        if time.monotonic() - last > 5 or index == len(objects):
            log(f"  objects: {index}/{len(objects)}")
            last = time.monotonic()
    report.data["objects"].update({"written": written, "already_identical": kept})
    return expected


def run_migration(ctx: Context, inv: Inventory, report: Report) -> None:
    args = ctx.args
    work = args.work_dir.expanduser()
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(work, 0o700)
    dump = work / f"sauri-docker-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.dump"
    try:
        log("1/5 dumping the Docker database (read only)")
        report.data["dump_bytes"] = ctx.source.dump(dump)
        log("2/5 restoring into the app database")
        assert inv.target_state is not None
        tgt.run_sync(tgt.recreate_database(ctx.target, inv.target_state))
        tgt.restore(ctx.target, tgt.find_pg_tool("pg_restore", args.pg_bin), dump)
        restored = tgt.run_sync(tgt.alembic_revision(ctx.target))
        if restored != inv.source_revision:
            report.differences.append(Difference("alembic_revision", "alembic_version", inv.source_revision,
                                                 restored))
        if restored != inv.head:
            log(f"   upgrading the schema {restored} -> {inv.head}")
            tgt.alembic_upgrade(ctx.target)
        final = tgt.run_sync(tgt.alembic_revision(ctx.target))
        report.data["target"].update({"alembic_restored": restored, "alembic_final": final})
        if final != inv.head:
            report.differences.append(Difference("alembic_head", "alembic_version", inv.head, final))
    finally:
        if not args.keep_dump:
            dump.unlink(missing_ok=True)

    log(f"3/5 copying {len(inv.objects)} recordings files")
    ctx.recordings.mkdir(parents=True, exist_ok=True)
    expected = copy_all(ctx, inv.objects, report)

    log("4/5 comparing source and target")
    source_after = ctx.source.row_counts()
    objects_after = ctx.s3.list_objects()
    target_rows = tgt.run_sync(tgt.row_counts(ctx.target))
    report.differences.extend(compare_rows(inv.source_rows, source_after, target_rows))
    found = scan_tree(ctx.recordings)
    report.differences.extend(compare_objects(
        expected, {o.key: (o.size, o.etag) for o in objects_after},
        {o.key: (o.size, o.etag) for o in inv.objects}, found))
    for name in sorted(set(source_after) | set(target_rows)):
        report.data["tables"].setdefault(name, {})["target"] = target_rows.get(name)
    report.data["objects"].update({"target_count": len(found), "target_bytes": sum(r.size for r in found.values())})

    log("5/5 local user")
    user_id = tgt.run_sync(tgt.user_id_by_email(ctx.target, args.local_user_email))
    report.data["local_user_id"] = user_id
    if user_id is None:
        report.differences.append(Difference("local_user_missing", args.local_user_email))
    if not report.differences:
        tgt.run_sync(tgt.clear_in_progress_mark(ctx.target))
        if args.config is not None and user_id is not None:
            write_local_user(args.config, user_id)
            report.data["config_updated"] = str(args.config)


def verify_only(ctx: Context, report: Report) -> None:
    """Compare rows and {key, size, MD5} of an earlier migration with the (unchanged) source."""
    source_rows = ctx.source.row_counts()
    objects = ctx.s3.list_objects()
    target_rows = tgt.run_sync(tgt.row_counts(ctx.target))
    found = scan_tree(ctx.recordings)
    report.differences.extend(compare_rows(source_rows, source_rows, target_rows))
    expected: dict[str, ObjectRecord] = {}
    for item in objects:
        md5 = etag_md5(item.etag)
        # Without an MD5 ETag only the size can be checked against the source.
        fallback = found[item.key].md5 if item.key in found else "unknown"
        expected[item.key] = ObjectRecord(item.key, item.size, md5 or fallback)
    listing = {o.key: (o.size, o.etag) for o in objects}
    report.differences.extend(compare_objects(expected, listing, listing, found))
    report.data["tables"] = {name: {"source": source_rows.get(name), "target": target_rows.get(name)}
                             for name in sorted(set(source_rows) | set(target_rows))}
    report.data["objects"] = {"source_count": len(objects), "source_bytes": sum(o.size for o in objects),
                              "target_count": len(found), "target_bytes": sum(r.size for r in found.values())}


def write_report(report: Report, path: Path) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(report.as_dict(), output, indent=2, sort_keys=True)
        output.write("\n")


def print_summary(report: Report) -> None:
    data = report.data
    tables = data.get("tables", {})
    if tables:
        print("Rows per table (source -> target):")
        for name, counts in tables.items():
            target = counts.get("target")
            print(f"  {name}: {counts.get('source')}" + (f" -> {target}" if "target" in counts else ""))
    objects = data.get("objects")
    if objects:
        print(f"Objects: {objects['source_count']} ({human(objects['source_bytes'])})"
              + (f" -> {objects['target_count']} ({human(objects['target_bytes'])})" if "target_count" in objects
                 else ""))
    for check in data.get("space", []):
        verdict = "ok" if check["enough"] else "NOT ENOUGH"
        print(f"Space for {', '.join(check['labels'])}: needs {human(check['required_bytes'])}, "
              f"free {human(check['available_bytes'])} -> {verdict}")
    if data.get("local_user_id"):
        print(f"Local user id (SAURI_LOCAL_USER_ID): {data['local_user_id']}")
    for problem in report.problems:
        print(f"PROBLEM: {problem}")
    for difference in report.differences:
        print(f"DIFFERENCE: {difference.as_dict()}")
    print(f"Result: {data.get('status')}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = Report("dry-run" if args.dry_run else "verify" if args.verify else "run")
    report.data["started_at"] = datetime.now(UTC).isoformat()
    report_path = args.report or DEFAULT_REPORT_DIR / f"migrate-from-docker-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    code = 1
    try:
        if args.recordings is None:
            raise tgt.TargetError("give --recordings or set SAURI_RECORDINGS_DIR")
        ctx = Context(
            args=args,
            source=DockerPostgres(args.source_container, args.source_database, args.source_user, SubprocessRunner()),
            s3=S3Source(args.s3_endpoint, args.s3_bucket, read_key_file(args.s3_access_key_file),
                        read_key_file(args.s3_secret_key_file)),
            target=tgt.PgTarget.from_url(resolve_target_url(args.target_url)),
            recordings=args.recordings.expanduser().resolve(),
        )
        if args.verify:
            verify_only(ctx, report)
        else:
            inventory = preflight(ctx, report)
            if not report.problems and args.run:
                run_migration(ctx, inventory, report)
        if report.problems:
            report.data["status"] = "refused"
        elif report.differences:
            report.data["status"] = "differences"
        else:
            report.data["status"] = "ready" if args.dry_run else "ok"
            code = 0
    except (SourceError, SourceSafetyError, tgt.TargetError, ObjectCopyError, OSError) as exc:
        report.data["status"] = "error"
        report.data["error"] = f"{type(exc).__name__}: {exc}"
        print(f"ERROR: {exc}", file=sys.stderr)
    except Exception as exc:  # A report must exist even for an unexpected failure.
        report.data["status"] = "error"
        report.data["error"] = f"{type(exc).__name__}"
        print(f"ERROR: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
    report.data["finished_at"] = datetime.now(UTC).isoformat()
    write_report(report, report_path)
    print_summary(report)
    print(f"Report: {report_path}")
    return code
