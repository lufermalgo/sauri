#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
script="$ROOT/scripts/tests/pg-disposable.sh"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

if [[ -z ${PG_BIN:-} ]]; then
  candidate=$(command -v initdb || true)
  [[ -z $candidate ]] || PG_BIN=$(dirname "$candidate")
fi
if [[ -z ${PG_BIN:-} || ! -x "$PG_BIN/initdb" ]] || ! "$PG_BIN/initdb" --version 2>/dev/null | grep -Eq 'PostgreSQL\)? 16\.'; then
  output=$(PG_BIN="$tmp/missing" "$script" -- true 2>&1) && { echo "expected unavailable PostgreSQL to fail" >&2; exit 1; }
  grep -Eq 'not found|binary missing' <<<"$output" || { echo "unclear PostgreSQL-unavailable error: $output" >&2; exit 1; }
  echo "pg-disposable: missing PostgreSQL 16 diagnostic passed (live lifecycle not run)"
  exit 0
fi

output=$("$script" -- sh -c 'printf "%s\n%s\n%s\n%s\n%s\n" "$SAURI_QA_POSTGRES_URL" "$SAURI_QA_POSTGRES_ROOT" \
  "$SAURI_QA_T9_POSTGRES_URL" "$SAURI_QA_T11_POSTGRES_URL" "$SAURI_MIGRATION_TEST_ADMIN_URL"')
url=$(sed -n 1p <<<"$output")
root=$(sed -n 2p <<<"$output")
server='^postgresql\+asyncpg://postgres:[0-9a-f]{32}@127\.0\.0\.1:[0-9]+/'
[[ $url =~ ${server}sauri_qa$ ]] || { echo "URL missing or malformed in child output" >&2; exit 1; }
[[ $(sed -n 3p <<<"$output") =~ ${server}sauri_t9_qa$ ]] || { echo "T9 URL missing or malformed" >&2; exit 1; }
[[ $(sed -n 4p <<<"$output") =~ ${server}sauri_t11_qa$ ]] || { echo "T11 URL missing or malformed" >&2; exit 1; }
[[ $(sed -n 5p <<<"$output") =~ ${server}postgres$ ]] || { echo "migration admin URL missing or malformed" >&2; exit 1; }
[[ -n $root && ! -e $root ]] || { echo "temporary cluster directory remains: $root" >&2; exit 1; }
if ps -axo command | grep '[p]ostgres.*sauri-qa-pg\.' | grep -q .; then
  echo "temporary postgres process remains after cleanup" >&2; exit 1
fi
echo "pg-disposable: lifecycle and cleanup passed"
