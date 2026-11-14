# #773 — T7 RED / T8 GREEN: initial recovery outbox delivery

## Scope and dependency

- APX delivery: `task_e3101ceaffb14e3f` (historical `task_a7e3ad6bcc2b49e6` unavailable; no duplicate executor).
- Canonical branch/worktree: `bugfix/issue-773-stale-recovery-t-7`, `.worktrees/bugfix-issue-773-stale-recovery-t-7`.
- Base: PR #916, `b85a868b7644fc62e7d7d80bb9833b14c819c287`, branch `bugfix/issue-771-stale-recovery-service`; itself stacked on #913. Existing clean canonical branch was advanced ff-only to that dependency. Neither precursor nor main was modified. #916 remained OPEN/draft at delivery preparation.
- Source: approved `bugfix.md`, `design.md`, `tasks.md`, T7/T8 and issue #773. Work is independent of GPU/performance/speaker-count activities.
- Condition of delivery: draft PR ready for Ansel's review. Fer retains merge. No merge, deployment, live recovery or pilot.

## Behavioral RED preserved before implementation

Commit `3064cf5` contains only T7 tests and exact output `t7-red-20261113.txt`. From `backend/`, using the existing backend dev Python with bytecode disabled:

```bash
SAURI_OUTBOX_TEST_DATABASE_URL=postgresql+asyncpg://synthetic:synthetic@127.0.0.1:<temporary-port>/recovery_773 \
PYTHONDONTWRITEBYTECODE=1 <backend-dev-python> -m pytest -p no:cacheprovider tests/infra/test_recovery_outbox.py -q
```

Observed **1 failed, 4 passed in 2.92s**. `MeetingRecoveryService.recover` really committed an authorized synthetic operation/outbox, then actual `app.worker.main()` ran with isolated queue and PostgreSQL factories/configuration and a controlled real stop event. The failure was `queue.publish.await_count == 1`, observed **0**. No missing imports, `hasattr` checks, production stubs or fake recovery implementation. Empty, disabled, non-owner and commit-rollback cases already passed. An earlier test-double coroutine warning was corrected and the RED rerun cleanly before committing.

## Implementation and file-inventory adjustment

- New `app/infra/recovery_outbox.py:dispatch_pending_recoveries(queue, session_factory)` reads only committed pending outbox rows joined to accepted/dispatch-pending operations, matching generation and `transcribe` topic. It resolves persisted meeting owner/recording identity and verifies the matching recovery claim; uncertain binding is a read-only skip.
- Locks **only outbox rows**, with PostgreSQL `FOR UPDATE OF ... SKIP LOCKED`, across initial publish. Simultaneous startup passes cannot send the same pending row; consumers need not acquire the outbox lock. Acknowledged publish marks the row `published` and increments attempts. Publish failure leaves it pending, reports content-free `dispatch_pending`/`publish_failed`, and never logs exception text.
- Worker startup connects/subscribes and then runs that one delivery pass. It never calls the recovery service, initiates recovery, rewrites a meeting, resets a claim, replays ingestion, arms a gate, or schedules retries. Infrastructure now closes in `finally` on startup failure as well as normal stop; the retention task is cancelled and awaited.
- Payload contains exactly opaque `operation_id`, stable `job_id=operation_id`, `generation`, `meeting_id`, `owner_id`, `recording_id`. No media reference, note, transcript, participant or raw idempotency key is carried.
- **Necessary small technical file addition to inventory:** `app/transcription/worker.py` previously rejected every message lacking `audio_ref` even though it already resolves the canonical reference from the persisted recording. Recovery envelopes must be reference-free under the approved design. The only contract adjustment is allowing omission for messages with an operation identity, **before the existing mandatory persisted owner/recording/operation/generation fence**. Normal ingestion messages retain their existing audio-ref validation. No new product/security policy, replacement engine, or broad worker rewrite. Valid identifier-only delivery, forged operation rejection, and duplicate no-op are tested through the real consumer with a synthetic engine double.
- `queue_rabbitmq.py` changes only two log statements: do not print broker URL/credentials or raw payload. Publish/signature/durability/subscribe/ack APIs and behavior are unchanged. Nevertheless a real disposable RabbitMQ test verifies signed transport and identifier-only payload/logs.
- `queue.py`, schema, routes, pilot settings, other specs, UI and clients are unchanged.

## Tests and controls on code commit `1276147`

All tests use synthetic data. PostgreSQL transaction visibility, rollback and competing dispatcher locks are real. Worker subscriptions/retention are isolated so no actual ASR/diarization/model/media processing occurs. Existing engine doubles are only tests, not a replacement for production functionality.

### Focused

```bash
SAURI_OUTBOX_TEST_DATABASE_URL=<exclusive-local-recovery_773-url> \
SAURI_OUTBOX_TEST_BROKER_URL=<exclusive-local-amqp-url> \
PYTHONDONTWRITEBYTECODE=1 <backend-dev-python> -m pytest -p no:cacheprovider \
tests/infra/test_recovery_outbox.py -q -rs
```

Observed **17 passed in 3.65s**, no skips, with real PostgreSQL16 and RabbitMQ3. Covers startup delivery/restart, no auto-initiation, disabled/non-owner/empty, real service commit-error rollback, uncommitted visibility, stale operation/generation/claim/owner/recording/topic no-ops, publish failure privacy, parallel initial dispatch, identifier-only real consumer/fence, and real signed broker delivery. Runtime recovery arming may be disabled after acceptance: delivery uses already-committed intent, not a new recovery request.

### Regression (final code and test candidate)

```bash
SAURI_OUTBOX_TEST_DATABASE_URL=<exclusive-local-recovery_773-url> \
SAURI_RECOVERY_TEST_DATABASE_URL=<exclusive-local-recovery_771-url> \
SAURI_OUTBOX_TEST_BROKER_URL=<exclusive-local-amqp-url> \
SAURI_RECOVERY_TEST_OBJECT_ENDPOINT=<exclusive-local-s3-endpoint> \
OBJECT_STORE_ENDPOINT=<exclusive-local-s3-endpoint> OBJECT_STORE_BUCKET=sauri-773-test \
MINIO_ROOT_USER=synthetic771 MINIO_ROOT_PASSWORD=synthetic771 \
PLAYBACK_TEST_FRONTEND_ORIGIN=http://localhost:5173 PYTHONDONTWRITEBYTECODE=1 \
<backend-dev-python> -m pytest -p no:cacheprovider \
tests/infra/test_recovery_outbox.py tests/meetings tests/ingestion tests/auth \
tests/transcription tests/diarization tests/infra/test_manual_recovery_persistence.py \
tests/infra/test_queue_retries.py tests/infra/test_adaptadores_conformidad_property.py \
tests/test_queue.py tests/test_migration.py -q -rs --durations=10
```

Observed **457 passed, 3 skipped, 18 deprecation warnings in 38.45s**. Exact output: `t8-green-20261113.txt`. The 3 explicit unconfigured optional checks are legacy-reprocess dedicated PostgreSQL QA (1) and PostgreSQL migration-admin variants (2); no migration/schema was changed. All 17 outbox cases, service transaction cases, worker fences, normal workers/ingestion, broker unit contracts, playback S3 range/CORS and recovery S3 metadata probes passed. This is not a claim that the entire backend or full future recovery feature is verified.

### Static checks

Commands use backend `pyproject.toml` and actual CI scopes from `.github/workflows/ci.yml`:

- `python -m ruff check . --no-cache`: **3 pre-existing errors**, identical complete output against an extracted archive of exact base `b85a868`. Files: `alembic/versions/009_recording_media_sources.py` I001, `app/auth/token.py` UP017, `tests/speaker_review/test_processing_readiness.py` I001. No baseline debt was changed or suppressed.
- `python -m mypy . --cache-dir <scratch>`: **82 pre-existing errors in 8 unchanged files**, 179 files checked. Exact base archive: same **82 errors in the same 8 files**, 177 checked. Full diagnostic diff differs only in checked-file count. No new errors.
- `python -m mypy app --cache-dir <scratch>`: **PASS, 67 source files**.
- `python -m ruff check app/infra/recovery_outbox.py app/infra/queue_rabbitmq.py app/worker.py app/transcription/worker.py tests/infra/test_recovery_outbox.py --no-cache`: **PASS**.
- `python -m mypy app/infra/recovery_outbox.py app/infra/queue_rabbitmq.py app/worker.py app/transcription/worker.py tests/infra/test_recovery_outbox.py --cache-dir <scratch>`: **PASS, 5 source files**.
- `git diff --check`: **PASS**; normal pre-commit and pre-push hooks remain enabled.

## Environment and cleanup

Used installed backend dev Python 3.13.4 (read-only, no dependency/model downloads); no native engine venv or owner's runtime configuration was changed. Scratch scripts/logs/cache/base archive are exclusively under this APX task's temp folder. No builds, benchmarks, acoustic jobs, GPU requests or real media reads.

Only own temporary `sauri-773-pg`, `sauri-773-store`, `sauri-773-mq` resources (label `sauri.task=773`) were created, from cached images. Limits: PostgreSQL 0.5 CPU/256 MiB, RustFS 0.5 CPU/384 MiB/Tokio 2 workers, RabbitMQ 0.5 CPU/256 MiB/Erlang 1 scheduler. Local random loopback ports, synthetic credentials, tmpfs data directories, no new network or persistent volume. Cleanup trap removes only own containers with `docker rm -fv` on success or failure; final verification: **own containers=0, networks=0, volumes=0**. Shared bridge and all unrelated resources were left intact.

Validation setup corrections, not hidden test failures: PostgreSQL readiness initially probed its transient init socket (changed to final TCP readiness); a regression attempt lacked an isolated S3 endpoint (430 PASS/1 environmental FAIL/5 skips, then rerun with own real S3); RustFS's non-root data directory needed writable tmpfs mode; RabbitMQ TCP-listener availability did not prove AMQP readiness (changed to a real successful AMQP handshake before suite). These failures were corrected within the temporary harness and every run cleaned up. The final real-service run above passed without weakening tests or production controls.

## Deferred and readiness

Initial delivery only. T19/T20 still own ambiguous acknowledgement/crash retry and complete deduplication evidence; there is no claim of exactly-once broker transport. Preservation/status, full API/pilot verification, integrated recovery QA/security and explicit Fer pilot authorization remain their own units. A draft PR does not enable operational recovery or authorize deployment. Issue #773 must stay open at publication. Ansel reviews this unit; Fer integrates in dependency order.
