#!/usr/bin/env bash
set -Eeuo pipefail

usage() { echo "Usage: $0 -- command [args...]" >&2; exit 2; }
[[ ${1:-} == -- ]] || usage
shift
(( $# )) || usage

PG_BIN=${PG_BIN:-}
if [[ -z $PG_BIN ]]; then
  initdb_path=$(command -v initdb || true)
  [[ -n $initdb_path ]] || { echo "PostgreSQL 16 initdb not found; set PG_BIN to its bin directory." >&2; exit 1; }
  PG_BIN=$(dirname "$initdb_path")
fi
for binary in initdb pg_ctl postgres; do
  [[ -x "$PG_BIN/$binary" ]] || { echo "PostgreSQL binary missing: $PG_BIN/$binary (set PG_BIN to the PostgreSQL 16 bin directory)." >&2; exit 1; }
done
version=$("$PG_BIN/initdb" --version 2>&1) || { echo "Cannot run PostgreSQL initdb at $PG_BIN." >&2; exit 1; }
[[ $version =~ PostgreSQL\)?\ 16\. ]] || { echo "PostgreSQL 16 required; found: $version" >&2; exit 1; }

root=$(mktemp -d "${TMPDIR:-/tmp}/sauri-qa-pg.XXXXXX")
data="$root/data"
socket="$root/socket"
mkdir -m 700 "$socket"
port=$("${PYTHON:-python3}" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
started=0
cleanup() {
  local rc=$?
  if (( started )); then "$PG_BIN/pg_ctl" -D "$data" -m immediate -w stop >/dev/null 2>&1 || true; fi
  rm -rf "$root"
  exit "$rc"
}
trap cleanup EXIT INT TERM HUP

# Tests require a loopback TCP server, so protect it with a random password instead of trust auth.
password=$(openssl rand -hex 16)
printf '%s\n' "$password" >"$root/pwfile"
chmod 600 "$root/pwfile"
if ! "$PG_BIN/initdb" -D "$data" -A scram-sha-256 --pwfile="$root/pwfile" -U postgres >"$root/initdb.log" 2>&1; then
  if grep -Eqi 'shmget|shared memory|operation not permitted' "$root/initdb.log"; then
    echo "initdb could not reserve shared memory (shmget); run outside this restricted sandbox." >&2
  else
    echo "PostgreSQL initdb failed:" >&2
    cat "$root/initdb.log" >&2
  fi
  exit 1
fi
if ! "$PG_BIN/pg_ctl" -D "$data" -o "-c listen_addresses='127.0.0.1' -c unix_socket_directories='$socket' -p $port" -l "$root/postgres.log" -w start >/dev/null 2>&1; then
  echo "PostgreSQL failed to start; see startup diagnostics:" >&2
  cat "$root/postgres.log" >&2 || true
  exit 1
fi
started=1
# Tests refuse any database outside their dedicated namespace (a guard against touching real data):
# most need "sauri_qa"; the summary pipeline suites need "sauri_t9_*" and "sauri_t11_*".
for database in sauri_qa sauri_t9_qa sauri_t11_qa; do
  if ! PGPASSWORD="$password" "$PG_BIN/createdb" -h 127.0.0.1 -p "$port" -U postgres "$database" >/dev/null 2>&1; then
    echo "Could not create the $database database; see $root/postgres.log" >&2
    exit 1
  fi
done
server="postgresql+asyncpg://postgres:$password@127.0.0.1:$port"
export SAURI_QA_POSTGRES_URL="$server/sauri_qa"
export SAURI_QA_T9_POSTGRES_URL="$server/sauri_t9_qa"
export SAURI_QA_T11_POSTGRES_URL="$server/sauri_t11_qa"
# Migration tests create and drop their own databases through this superuser URL.
export SAURI_MIGRATION_TEST_ADMIN_URL="$server/postgres"
export SAURI_QA_POSTGRES_ROOT="$root"
"$@"
