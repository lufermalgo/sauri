#!/usr/bin/env bash
# Full rehearsal of migrate-from-docker on DISPOSABLE resources with SYNTHETIC data.
#
#   PG_BIN=$HOME/Library/Caches/sauri-runtime-build/runtime-current/pg/bin scripts/migrate-from-docker/rehearsal/rehearse.sh
#
# Never touches the owner's Docker project `sauri`: it creates `sauri-qa-mig-*` containers and `sauri_qa_mig_*`
# volumes on 127.0.0.1 ports that are not the owner's, a disposable target cluster (scripts/tests/pg-disposable.sh)
# and a temporary folder, and removes all of them on exit. PG_IMAGE / S3_IMAGE may name local image ids.
set -Eeuo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
BACKEND=$REPO/backend
SRC=sauri-qa-mig-src
S3=sauri-qa-mig-s3
VOL_PG=sauri_qa_mig_src_pg
VOL_S3=sauri_qa_mig_s3_data
PG_PORT=${PG_PORT:-15433}
S3_PORT=${S3_PORT:-19000}
BUCKET=sauri-recordings

inner() {
  local work=$1
  export TARGET_URL="${SAURI_MIGRATION_TEST_ADMIN_URL%/postgres}/sauri"
  local base="${SAURI_MIGRATION_TEST_ADMIN_URL%/postgres}"
  local migrate=(uv run python "$REPO/scripts/migrate-from-docker/migrate.py")
  common() {  # sets ARGS for a given recordings folder (bash 3.2 has no mapfile)
    ARGS=(--source-container "$SRC" --rabbitmq-container none --writer-containers none
      --s3-endpoint "http://127.0.0.1:$S3_PORT" --s3-access-key-file "$work/keys/s3_access"
      --s3-secret-key-file "$work/keys/s3_secret" --work-dir "$work/dump" --recordings "$1")
  }
  local log="$work/step.log" n=0
  expect() {  # expect <exit code> <grep pattern or -> <command...>
    local want=$1 pattern=$2; shift 2
    n=$((n + 1))
    set +e; "$@" >"$log" 2>&1; local got=$?; set -e
    if [[ $got != "$want" ]] || { [[ $pattern != - ]] && ! grep -q -- "$pattern" "$log"; }; then
      echo "FAIL step $n (exit $got, wanted $want, pattern '$pattern'): $*" >&2; cat "$log" >&2; exit 1
    fi
    echo "ok $n: exit $got${pattern:+, '$pattern'}"
  }
  fingerprint() {
    docker exec "$SRC" pg_dump -U sauri -d sauri --no-sync | grep -Ev '^\\(un)?restrict ' | shasum -a 256 | cut -c1-16
    uv run python - "$S3_PORT" "$work/keys" <<'PY'
import hashlib, sys
import boto3
port, keys = sys.argv[1:3]
c = boto3.client("s3", endpoint_url=f"http://127.0.0.1:{port}", region_name="us-east-1",
                 aws_access_key_id=open(f"{keys}/s3_access").read().strip(),
                 aws_secret_access_key=open(f"{keys}/s3_secret").read().strip())
rows = sorted(f"{o['Key']} {o['Size']} {o['ETag']} {o['LastModified'].isoformat()}"
              for p in c.get_paginator("list_objects_v2").paginate(Bucket="sauri-recordings")
              for o in p.get("Contents", []))
print(len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16])
PY
  }
  cd "$BACKEND"
  local rec="$work/recordings" config="$work/config.json"
  common "$rec"; local main_args=("${ARGS[@]}")
  mkdir -p "$rec" "$work/reports"
  printf '{"schemaVersion":1,"installId":"qa","setupStep":"models","locale":"es","launchAtLogin":false,"autoUpdate":true,"paths":{"recordings":"%s","database":"%s/db","models":"%s/models"},"localUserId":"placeholder"}\n' \
    "$rec" "$work" "$work" >"$config"

  fingerprint >"$work/before"
  echo "source fingerprint before: $(tr '\n' ' ' <"$work/before")"
  expect 0 "Result: ready" "${migrate[@]}" --dry-run "${main_args[@]}" --target-url "$TARGET_URL" --report "$work/reports/dry.json"
  expect 0 "Result: ok" "${migrate[@]}" --run "${main_args[@]}" --target-url "$TARGET_URL" --config "$config" --report "$work/reports/run.json"
  grep -E "^Objects|^Local user" "$log"
  expect 0 "-> OK" uv run python "$HERE/independent_check.py" "$SRC" "http://127.0.0.1:$S3_PORT" "$BUCKET" \
    "$work/keys/s3_access" "$work/keys/s3_secret" "$rec"
  cat "$log"
  fingerprint >"$work/after"
  cmp -s "$work/before" "$work/after" || { echo "FAIL: the source changed" >&2; exit 1; }
  echo "source fingerprint after:  $(tr '\n' ' ' <"$work/after") (unchanged)"
  python3 - "$config" "$work/reports/run.json" <<'PY'
import json, sys
config, report = (json.load(open(p)) for p in sys.argv[1:3])
assert config["localUserId"] == report["local_user_id"] and config["installId"] == "qa", "config not updated"
assert report["target"]["alembic_restored"] == "029_meeting_recorded_at"
assert report["target"]["alembic_final"] == report["target"]["alembic_head"]
print("config.json localUserId = admin id; schema", report["target"]["alembic_restored"], "->",
      report["target"]["alembic_final"])
PY
  # The app's own code reads the migrated rows and files.
  expect 0 "app check ok" uv run python - "$TARGET_URL" "$rec" <<'PY'
import asyncio, sys
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.infra import models as m
from app.infra.object_store_fs import FilesystemObjectStore
from app.local.inflight import count_processing
async def main() -> None:
    engine = create_async_engine(sys.argv[1])
    store = FilesystemObjectStore(Path(sys.argv[2]))
    async with async_sessionmaker(engine)() as session:
        recordings = (await session.execute(select(m.SessionRecording))).scalars().all()
        refs = [r for rec in recordings for r in (rec.audio_ref, rec.video_ref, rec.thumbnail_ref) if r]
        states = {await store.inspect(ref) for ref in refs}
        jobs = await session.scalar(select(func.count()).select_from(m.JobMessage))
        busy = await count_processing(session)
    await engine.dispose()
    assert states == {"available"} and jobs == 0 and busy == 0, (states, jobs, busy)
    print(f"app check ok: {len(refs)} recording refs available, job_messages {jobs}, in flight {busy}")
asyncio.run(main())
PY
  cat "$log"

  echo "--- failure: an object corrupted in the target"
  local big; big=$(find "$rec" -name video -size +10M | head -1)
  python3 -c 'import sys; f = open(sys.argv[1], "r+b"); f.seek(5_000_000); b = f.read(1); f.seek(5_000_000); f.write(bytes([b[0] ^ 255]))' "$big"
  expect 1 "object_md5" "${migrate[@]}" --verify "${main_args[@]}" --target-url "$TARGET_URL" --report "$work/reports/tampered.json"
  grep DIFFERENCE "$log"

  echo "--- failure: a different file already in the target during --run, then a retry"
  local rec2="$work/rec2" key
  key=$(cd "$rec" && find recordings -name thumbnail.jpg | head -1)
  mkdir -p "$rec2/$(dirname "$key")"; echo corrupted >"$rec2/$key"
  common "$rec2"; local args2=("${ARGS[@]}")
  expect 1 "object_copy_failed" "${migrate[@]}" --run "${args2[@]}" --target-url "$base/sauri_t2" --report "$work/reports/conflict.json"
  expect 1 "unfinished earlier attempt" "${migrate[@]}" --run "${args2[@]}" --target-url "$base/sauri_t2" --report "$work/reports/conflict2.json"
  rm "$rec2/$key"
  expect 0 "Result: ok" "${migrate[@]}" --run "${args2[@]}" --target-url "$base/sauri_t2" --replace-unfinished --report "$work/reports/conflict3.json"

  echo "--- failure: work in flight in the source"
  uv run python "$HERE/seed_synthetic.py" --inflight --database-url "$SOURCE_URL" --s3-endpoint "http://127.0.0.1:$S3_PORT" \
    --access-key-file "$work/keys/s3_access" --secret-key-file "$work/keys/s3_secret"
  common "$work/rec3"; local args3=("${ARGS[@]}")
  expect 1 "work is in flight" "${migrate[@]}" --dry-run "${args3[@]}" --target-url "$base/sauri_t3" --report "$work/reports/inflight-dry.json"
  expect 1 "work is in flight" "${migrate[@]}" --run "${args3[@]}" --target-url "$base/sauri_t3" --report "$work/reports/inflight-run.json"
  [[ ! -e "$work/rec3" ]] || [[ -z $(ls -A "$work/rec3") ]] || { echo "FAIL: refused run wrote files" >&2; exit 1; }
  docker exec "$SRC" psql -q -U sauri -d sauri -c "DELETE FROM meetings WHERE title = 'synthetic in-flight'"

  echo "--- failure: not enough free space"
  hdiutil create -quiet -size 12m -fs HFS+ -volname sauriqasmall "$work/small.dmg"
  mkdir -p "$work/small"; hdiutil attach -quiet "$work/small.dmg" -mountpoint "$work/small" -nobrowse
  common "$work/small/recordings"; local args4=("${ARGS[@]}")
  expect 1 "not enough free space" "${migrate[@]}" --run "${args4[@]}" --target-url "$base/sauri_t4" --report "$work/reports/space.json"
  [[ ! -e "$work/small/recordings" ]] || { echo "FAIL: refused run wrote files" >&2; exit 1; }
  hdiutil detach -quiet "$work/small"

  echo "--- a freshly set-up app database is replaced only on request"
  local fresh="$base/sauri_fresh"
  PGPASSWORD=$(python3 -c 'import sys; from urllib.parse import urlsplit; print(urlsplit(sys.argv[1]).password)' "$TARGET_URL") \
    "$PG_BIN/createdb" -h 127.0.0.1 -p "$(python3 -c 'import sys; from urllib.parse import urlsplit; print(urlsplit(sys.argv[1]).port)' "$TARGET_URL")" -U postgres sauri_fresh
  DATABASE_URL="$fresh" uv run alembic upgrade head >/dev/null 2>&1
  DATABASE_URL="$fresh" uv run python -m app.local.bootstrap --name "Fresh Owner" >/dev/null
  common "$work/rec5"; local args5=("${ARGS[@]}")
  expect 1 "freshly set-up app" "${migrate[@]}" --dry-run "${args5[@]}" --target-url "$fresh" --report "$work/reports/fresh1.json"
  expect 0 "Result: ok" "${migrate[@]}" --run "${args5[@]}" --target-url "$fresh" --replace-fresh-app-db --report "$work/reports/fresh2.json"
  expect 1 "never replaced" "${migrate[@]}" --dry-run "${args5[@]}" --target-url "$fresh" --replace-fresh-app-db --replace-unfinished --report "$work/reports/fresh3.json"

  echo "--- the source database can never be the target"
  expect 1 "points to the Docker database itself" "${migrate[@]}" --run "${main_args[@]}" --target-url "$SOURCE_URL" --report "$work/reports/self.json"

  echo "--- reports hold no secrets and no meeting content"
  local secret
  for secret in "$(cat "$work/keys/pg_password")" "$(cat "$work/keys/s3_secret")" "$(cat "$work/keys/s3_access")" \
      "$(python3 -c 'import sys; from urllib.parse import urlsplit; print(urlsplit(sys.argv[1]).password)' "$TARGET_URL")" \
      "Synthetic meeting" "alpha bravo"; do
    ! grep -rqF -- "$secret" "$work/reports" || { echo "FAIL: a report holds a secret or content" >&2; exit 1; }
  done
  echo "ok: no secrets or content in $(ls "$work/reports" | wc -l | tr -d ' ') reports"
  echo "REHEARSAL PASSED"
}

if [[ ${1:-} == --inner ]]; then
  inner "$2"
  exit 0
fi

for port in "$PG_PORT" "$S3_PORT"; do
  case $port in 5432 | 9000 | 9001 | 5672 | 8000) echo "Refusing: $port is one of the owner's ports." >&2; exit 2 ;; esac
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then echo "Port $port is busy; set PG_PORT/S3_PORT." >&2; exit 2; fi
done
if docker ps -a --format '{{.Names}}' | grep -Eqx "$SRC|$S3"; then
  echo "A rehearsal container already exists ($SRC or $S3); remove it first." >&2; exit 2
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/sauri-qa-mig.XXXXXX")
cleanup() {
  local rc=$?
  [[ -d "$work/small" ]] && hdiutil detach -quiet -force "$work/small" 2>/dev/null || true
  docker rm -f "$SRC" "$S3" >/dev/null 2>&1 || true
  docker volume rm "$VOL_PG" "$VOL_S3" >/dev/null 2>&1 || true
  rm -rf "$work"
  exit "$rc"
}
trap cleanup EXIT INT TERM HUP
mkdir -m 700 "$work/keys"
openssl rand -hex 16 >"$work/keys/pg_password"
openssl rand -hex 10 >"$work/keys/s3_access"
openssl rand -hex 20 >"$work/keys/s3_secret"
chmod 600 "$work/keys"/*
docker volume create "$VOL_PG" >/dev/null
docker volume create "$VOL_S3" >/dev/null
docker run -d --name "$SRC" -p "127.0.0.1:$PG_PORT:5432" -e POSTGRES_DB=sauri -e POSTGRES_USER=sauri \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/pw -v "$work/keys/pg_password:/run/secrets/pw:ro" \
  -v "$VOL_PG:/var/lib/postgresql/data" \
  "${PG_IMAGE:-postgres:16@sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f}" >/dev/null
docker run -d --name "$S3" -p "127.0.0.1:$S3_PORT:9000" --env-file <(
  printf 'RUSTFS_ACCESS_KEY=%s\nRUSTFS_SECRET_KEY=%s\n' "$(cat "$work/keys/s3_access")" "$(cat "$work/keys/s3_secret")") \
  -v "$VOL_S3:/data" \
  "${S3_IMAGE:-rustfs/rustfs@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b}" server /data >/dev/null
for _ in $(seq 60); do docker exec "$SRC" pg_isready -q -U sauri -d sauri 2>/dev/null && break; sleep 1; done
sleep 2
export SOURCE_URL="postgresql+asyncpg://sauri:$(cat "$work/keys/pg_password")@127.0.0.1:$PG_PORT/sauri"
cd "$BACKEND"
# Same schema as the owner's Docker database today (head 029), then synthetic rows and objects.
DATABASE_URL="$SOURCE_URL" uv run alembic upgrade 029_meeting_recorded_at >/dev/null 2>&1
uv run python "$HERE/seed_synthetic.py" --database-url "$SOURCE_URL" --s3-endpoint "http://127.0.0.1:$S3_PORT" \
  --access-key-file "$work/keys/s3_access" --secret-key-file "$work/keys/s3_secret"
export SRC S3_PORT
"$REPO/scripts/tests/pg-disposable.sh" -- "$HERE/rehearse.sh" --inner "$work"
