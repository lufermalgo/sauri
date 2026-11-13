# T16 / #284 — Summary reads and request status GREEN

## Scope and lineage

- Approved `meeting-summaries-templates` requirements R1/R5 and design D13 / summary API ownership rules; implementation plan T16.
- Candidate starts at T12 `9589adf0e84f3ce21052945443c9a2b54ac69bde` and merges T15 branch `d371338b69105287f71d12a58235e99206e8d1ed`, preserving RED commit `73df389` and the T9/T10/T11/T12 ancestry. T15's committed evidence records the three expected missing-route HTTP failures before implementation.
- Add GET `/api/v1/meetings/{meeting_id}/summary` using an owner-scoped query over persisted successful artifacts ordered by generation descending. Return D13 snake_case projection including template name, topic, key points, and timestamps; never expose instructions.
- Existing latest/event status queries already implement T16's highest-accepted-generation, meeting association and non-disclosure contract. Keep them with unchanged URLs and literal `latest` registered before event lookup. Reuse `require_sales` and existing router registration; no redundant service wrapper or main registration needed.
- Only backend route/query behavior changes. No UI, provider integration, fallback/default policy, migration or merge.

## Observed validation (2026-11-13)

Python below is `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python`, run from candidate `backend/` with project `pyproject.toml`.

1. `python -m pytest tests/summaries/test_summary_api.py -q`: **9 passed**, SQLite.
2. With disposable PostgreSQL 16 (`sauri_t15_read` for API, `sauri_t11_worker` for worker) and RabbitMQ 3.13: `python -m pytest tests/summaries/test_summary_api.py tests/summaries/test_worker.py tests/summaries/test_worker_broker.py tests/infra/test_queue_retries.py -q`: **25 passed, no skips**. Checks successful generation 2 survives later pending/failed attempts, required payload, no-success 404, auth/sales/owner denial, latest ordering and cross-meeting event isolation. Also repeats T12's real broker exhaustion/authenticated terminal delivery and retention of previous successful summary.
3. `python -m pytest tests/integration/test_summary_pipeline.py -q`: **14 passed, no skips** with `sauri_t9_pipeline` and exclusively owned `sauri-t10-mq-1039`. Includes actual broker stop/start and application lifespan outbox recovery. Earlier run with a non-matching container name skipped that one test; corrected name plus fixed port binding removed the skip.
4. `python -m mypy app tests/summaries/test_summary_api.py --no-incremental`: **success, 72 source files**.
5. `python -m ruff check app/summaries/router.py app/summaries/repository.py tests/summaries/test_summary_api.py`: pass. `python -m ruff format --check app/summaries/router.py app/summaries/repository.py`: pass. `git diff --check`: pass.

An exploratory broader mypy run including unchanged `tests/integration/test_summary_pipeline.py` exposed seven inherited errors from reusing a broker `connection` variable for SQL connections in that fixture. App + T16 test gate passes. T13/T14 owns the pipeline test file in another isolated worktree; do not concurrently edit it here. This broader test-typing gap must be reconciled in the accumulated candidate, not represented as passing.

## Limits and closure

Real PostgreSQL and RabbitMQ validate API/persistence/delivery; synthetic engine doubles in worker tests are not evidence of real Ollama generation or accuracy. T14's adapter/runtime gate is separate. Fer retains integration; this is a reviewed/tested candidate, not integrated functionality or product acceptance. Disposable containers and their anonymous volumes are removed after validation; owner services and persistent data are untouched.
