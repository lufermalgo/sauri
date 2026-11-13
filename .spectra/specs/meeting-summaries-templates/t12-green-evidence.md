# T12 / #280 GREEN candidate — evidence and remaining integration boundary

T12 is stacked on T10 `54f7d1c` (PR #869) and T11 RED `7a7183b` (PR #868; evidence commit `adec2cb`). The merge commit is `b8a9f9e`. No merge into main and no issue closure.

## Implemented

- `start_worker` registers `summarize` and `summarize.failed`; validates the accepted event against its persisted immutable snapshot, marks `running` durably before provider execution, persists result + processed-event claim + `succeeded` in a single transaction, and leaves failures retryable without exposing exception details.
- Repeated completed events do not regenerate, concurrent redelivery cannot create duplicate successful artifacts, and terminal handler leaves earlier successful generation intact.
- Main worker invokes the consumer after diarization. Engine construction is an import of T14's future `app.summaries.factory`; startup raises when absent, deliberately **not** a fake local/cloud engine. No Ollama connectivity, model readiness or real end-to-end generation is claimed.

## Commands and observed results (worktree `feature-issue-280-summary-worker-green`)

- Backend interpreter: `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python`.
- `cd backend && /Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python -m pytest tests/summaries/test_worker.py -q` with `SAURI_QA_POSTGRES_URL=postgresql+asyncpg://qa:***@127.0.0.1:55491/sauri_t11_worker` on dedicated PostgreSQL 16: **6 passed**.
- `cd backend && /Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python -m pytest tests/summaries/test_summary_api.py tests/integration/test_summary_pipeline.py tests/templates tests/test_queue.py tests/infra/test_queue_retries.py -q -rs` with dedicated `sauri_t9_request`, RabbitMQ 3.13 on 127.0.0.1:56891, `SAURI_QA_RABBITMQ_CONTAINER=sauri-t10-mq-<unique PID>`: **62 passed, 0 skipped**, including broker stop/restart. Postgres/Rabbit containers were removed with `docker rm -f -v` in the trap; post-cleanup list empty.
- `cd backend && /Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python -m mypy --config-file pyproject.toml app --no-incremental`: **71 source files, no issues**.
- `cd backend && /Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python -m ruff check app/summaries/repository.py app/summaries/worker.py app/worker.py`: **All checks passed**. `git diff --check`: pass.

## Remaining gap — terminal delivery in the real broker

The RED queue is a contract double and directly invokes the registered terminal handler. The existing `RabbitMQJobQueue.subscribe()` instead retries a failing `summarize` delivery and, when exhausted, calls `nack(requeue=False)`. With default `QUEUE_DLX_EXCHANGE` unset it discards the message; no terminal handler runs, so request status remains `running`. Even with an external DLX, no exchange binding routes the original `summarize` key to `summarize.failed`, and the adapter verifies signatures against the subscribed topic name, rejecting a message signed for `summarize`. This is a real adapter contract gap, not a provider readiness issue. Fix requires an authorized narrow change to `backend/app/infra/queue_rabbitmq.py` and real RabbitMQ exhaustion regression, or an equivalent explicit delivery contract; do not call this draft ready to integrate until done. Do not alter retry policies, defaults, or unrelated queues as a workaround.

D9 no-default response remains gated; T13/T14 Ollama content/provider and T15/T16 API read are excluded. Fer retains integration; Ansel reviews.
