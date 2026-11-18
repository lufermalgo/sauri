"""Property 8 computed WITHOUT the tool's code: rows per table and the {key, size, MD5} set, source vs target.

Usage (rehearsal only): independent_check.py <source-container> <s3-endpoint> <bucket> <access-key-file>
<secret-key-file> <recordings-folder>, with TARGET_URL set. Exits 1 on any difference.
"""

import asyncio
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import boto3
from sqlalchemy.engine import make_url


def source_sql(container: str, sql: str) -> list[str]:
    argv = ["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on", container,
            "psql", "-X", "-U", "sauri", "-d", "sauri", "-tAc", sql]
    return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.split()


async def main() -> int:
    container, endpoint, bucket, access, secret, recordings = sys.argv[1:7]
    url = make_url(os.environ["TARGET_URL"])
    tables = source_sql(container, "SELECT relname FROM pg_stat_user_tables ORDER BY 1")
    connection = await asyncpg.connect(host=url.host, port=url.port, user=url.username, password=url.password,
                                       database=url.database)
    mismatches = []
    try:
        for table in tables:
            source = int(source_sql(container, f'SELECT count(*) FROM "{table}"')[0])
            target = await connection.fetchval(f'SELECT count(*) FROM "{table}"')
            if source != target:
                mismatches.append((table, source, target))
        extra = [r[0] for r in await connection.fetch(
            "SELECT relname FROM pg_stat_user_tables WHERE relname <> ALL($1::text[])", tables)]
        extra_rows = {name: await connection.fetchval(f'SELECT count(*) FROM "{name}"') for name in extra}
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        admin = "SELECT id FROM users WHERE email = 'admin@sauri.local'"
        same_admin = source_sql(container, admin) == [await connection.fetchval(admin)]
    finally:
        await connection.close()
    client = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                          aws_access_key_id=Path(access).read_text().strip(),
                          aws_secret_access_key=Path(secret).read_text().strip())
    source_set = {(o["Key"], o["Size"], o["ETag"].strip('"'))
                  for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket)
                  for o in page.get("Contents", [])}
    root = Path(recordings)
    target_set = {(p.relative_to(root).as_posix(), p.stat().st_size, hashlib.md5(p.read_bytes()).hexdigest())
                  for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")}
    ok = not mismatches and all(v == 0 for v in extra_rows.values()) and same_admin and source_set == target_set
    print(f"independent check: {len(tables)} tables, row mismatches {mismatches}, target-only tables {extra_rows}, "
          f"alembic {revision}, same admin id {same_admin}, objects {len(source_set)} vs {len(target_set)} "
          f"equal {source_set == target_set} -> {'OK' if ok else 'DIFFERENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
