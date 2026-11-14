#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "${ROOT_DIR}/scripts/engines/ensure-native-engine-credentials.sh"
# The queue signing key is generated once in the private credentials folder; an explicit value wins.
if [[ -z "${QUEUE_MESSAGE_SIGNING_KEY:-}" ]]; then
  QUEUE_MESSAGE_SIGNING_KEY="$(<"${HOME}/.config/sauri/queue_signing_key")"
  export QUEUE_MESSAGE_SIGNING_KEY
fi

run_compose() {
  local step="$1"
  shift
  if ! docker compose "$@"; then
    echo "Compose bring-up failed during: ${step}" >&2
    exit 1
  fi
}

run_compose "stopping existing API/worker before schema changes" stop api worker
run_compose "starting infrastructure (database, broker and object-store volume repair)" up -d postgres minio rabbitmq

# Apply the private credentials to services whose data predates them. Values are read
# inside each container from its mounted secret file and are never printed.
wait_for() {
  local step="$1" deadline=$((SECONDS + 90))
  shift
  until "$@" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Compose bring-up failed during: ${step}" >&2
      exit 1
    fi
    sleep 1
  done
}
wait_for "waiting for the database" docker compose exec -T postgres pg_isready -U sauri -d sauri -q
if ! docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -q -U sauri -d sauri >/dev/null <<'SQL'
\set pw `cat /run/secrets/database_password`
ALTER ROLE sauri WITH PASSWORD :'pw';
SQL
then
  echo "Compose bring-up failed during: applying the database password" >&2
  exit 1
fi
wait_for "waiting for the queue broker" docker compose exec -T rabbitmq rabbitmqctl -q await_startup
# shellcheck disable=SC2016 # expanded inside the container
if ! docker compose exec -T rabbitmq sh -c '
  set -e
  pw="$(cat /run/secrets/queue_password)"
  if rabbitmqctl -q list_users | cut -f1 | grep -qx sauri; then
    rabbitmqctl -q change_password sauri "$pw"
  else
    rabbitmqctl -q add_user sauri "$pw"
  fi
  rabbitmqctl -q set_permissions -p / sauri ".*" ".*" ".*"
  rabbitmqctl -q set_user_tags sauri management
  if rabbitmqctl -q list_users | cut -f1 | grep -qx guest; then
    rabbitmqctl -q delete_user guest
  fi' >/dev/null; then
  echo "Compose bring-up failed during: applying the queue broker user" >&2
  exit 1
fi
run_compose "creating/verifying object-store bucket" run --rm api python -m app.infra.ensure_bucket
run_compose "applying database migrations" run --rm api alembic upgrade head
run_compose "creating the administrator account and retiring legacy seed users" \
  run --rm api python -m app.auth.seed_admin --retire-legacy
run_compose "starting API, worker and portal" up -d api worker portal

# Resolve the selected project's actual binding (including QA overrides), rather
# than guessing from PORTAL_PORT. This does not change or recreate any volumes.
portal_binding="$(run_compose "resolving portal published address" port portal 80)"
if [[ ! "${portal_binding}" =~ ^127\.0\.0\.1:([0-9]+)$ ]]; then
  echo "Compose bring-up failed during: resolving loopback portal address" >&2
  exit 1
fi
portal_url="http://${portal_binding}"
http_deadline=$((SECONDS + 60))

wait_http() {
  local endpoint="$1"
  local remaining attempt_timeout http_status
  while (( SECONDS < http_deadline )); do
    remaining=$((http_deadline - SECONDS))
    attempt_timeout=2
    if (( remaining < attempt_timeout )); then
      attempt_timeout="${remaining}"
    fi
    if http_status="$(curl --fail --silent --output /dev/null --write-out '%{http_code}' \
      --connect-timeout "${attempt_timeout}" --max-time "${attempt_timeout}" \
      "${portal_url}/${endpoint}")" && [[ "${http_status}" == "200" ]]; then
      return 0
    fi
    if (( SECONDS < http_deadline )); then
      sleep 1
    fi
  done
  echo "Compose bring-up failed during: HTTP ${endpoint} (60s shared deadline)" >&2
  exit 1
}

wait_http portal-health
wait_http api-health
echo "Compose bring-up ready: portal and API HTTP reachable; database migrations applied and object-store bucket verified; native engines and inference not verified."
