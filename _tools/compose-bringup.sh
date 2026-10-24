#!/usr/bin/env bash
set -Eeuo pipefail

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
run_compose "creating/verifying object-store bucket" run --rm api python -m app.infra.ensure_bucket
run_compose "applying database migrations" run --rm api alembic upgrade head
run_compose "starting API and worker" up -d api worker
echo "Compose bring-up ready: database migrations applied and object-store bucket verified."
