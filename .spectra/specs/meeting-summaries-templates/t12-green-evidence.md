# T12 / #280 GREEN candidate — broker terminal-delivery correction and evidence

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

## Broker terminal delivery — correction after RED

The initial candidate discarded exhausted `summarize` deliveries without a configured DLX. Added real RabbitMQ 3.13 + PostgreSQL 16 regression `test_worker_broker.py`: initial successful generation followed by a provider failure and broker retry (one configured retry), then the terminal event must mark the second request `failed` while the first success remains intact. Before the adapter change the test failed after 20 seconds, with the broker log `Message discarded (no DLX configured)` and status stuck `running`. The corrected adapter confirms a separately signed `summarize.failed` message on its destination topic before acknowledging the original; it retains pre-existing DLX nacking when configured. If terminal publication is not confirmed, the original is requeued; if the terminal handler fails with no DLX, its durable event is retained for recovery rather than discarded. Forged terminal delivery carrying the original topic's signature is rejected on the real broker before the genuine terminal event is accepted.

**Post-correction validation:** dedicated disposable `sauri_t11_worker` PostgreSQL 16 and RabbitMQ 3.13: `python -m pytest tests/summaries/test_worker.py tests/summaries/test_worker_broker.py -q -rs` **9 passed, 0 skipped**. Dedicated `sauri_t9_request` and RabbitMQ 3.13: `python -m pytest tests/summaries/test_summary_api.py tests/integration/test_summary_pipeline.py tests/templates tests/infra/test_queue_retries.py tests/test_queue.py -q -rs` **62 passed, 0 skipped**, including broker restart. `python -m ruff check app/summaries/repository.py app/summaries/worker.py app/worker.py app/infra/queue_rabbitmq.py tests/summaries/test_worker_broker.py` passed; `python -m mypy --config-file pyproject.toml app tests/summaries/test_worker.py tests/summaries/test_worker_broker.py --no-incremental` passed **73 source files**. Interpreter is the root `backend/.venv/bin/python` and commands ran in this worktree's `backend/`. The test engine is synthetic; no provider accuracy or Ollama availability is claimed. T14 factory remains a startup gate, so this stacked draft must not be merged independently before its dependency is ready. A persistent `summarize.failed` handler outage with no DLX can cause rapid requeues; broker operational delay/backoff was not modified in this scoped change.

D9 no-default response remains gated; T13/T14 Ollama content/provider and T15/T16 API read are excluded. Fer retains integration; Ansel reviews.
