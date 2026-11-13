# T15 / #283 — current successful summary and isolated status reads

- Base before T15: `744ae88510a6a69dd746e6553061c12a64e3c8d6` (T10/#869; T2/T9 preserved).
- RED test commit: `73df389`.
- Current APX task: `task_4d3cdf24ea5443fd`. Historical card `task_abb0a6217a484a7a` remains historical lineage, not a second executor.
- Integration belongs to Fer; no merge or acceptance claimed.

## Observed execution

Using `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python -m pytest tests/summaries/test_summary_api.py -q` from `backend/`, both default SQLite and real disposable PostgreSQL 16 produced **3 failed, 6 passed**. PostgreSQL was selected through `SAURI_QA_SUMMARY_READ_URL`, guarded to a `postgresql+asyncpg` database named `sauri_t15_*` before any connection or cleanup. No skipped tests or fixture/collection errors.

Expected failures, each an HTTP assertion against absent `GET /summary`, not an import failure:

1. `test_current_summary_selects_highest_success_not_later_pending_or_failed`: 404 instead of 200.
2. `test_current_summary_requires_auth_sales_and_meeting_ownership`: 404 instead of 401 for anonymous access.
3. `test_no_successful_summary_returns_404_even_with_a_pending_request`: positive owner-read guard fails 404 instead of 200. The guard prevents a nonexistent route from passing an absence-only test vacuously.

Passing coverage includes T9 request acceptance and immutable snapshots, default selection, ownership and lifecycle statuses; explicit `test_latest_summary_request_route_resolves_before_event_id` selects generation 4 despite earlier successful generations; status reads test auth, sales, foreign owners and a real different meeting owned by the same user.

Four persisted outcomes are seeded through real SQLAlchemy/PostgreSQL after accepted POST requests: successes 1/2, pending 3, failed 4. This is a read-contract fixture, **not generation/provider validation**. T16 must expose generation 2 with its structured content, template lineage/name, timestamps and no instructions. No production code, provider, frontend, security policy or unresolved D9 fallback changed.

## Regression and gates

- T10 integration + templates + queue/retry regression: **58 passed**, including an actual broker stop/start under FastAPI lifespan and eight concurrent requests. Together with the four unchanged T9 API tests: **62 passed**.
- First broker-restart attempt used a Docker auto-assigned host port, which changed on restart; repeated with a fixed binding and passed. This was a QA setup correction, not a product fix.
- `uvx --offline ruff check tests/summaries/test_summary_api.py`: PASS.
- `uvx --offline ruff format --check tests/summaries/test_summary_api.py`: PASS after formatting this touched file; pre-existing assertions retained.
- `git diff --check`: PASS.
- `python -m mypy --config-file backend/pyproject.toml backend/app backend/tests/summaries/test_summary_api.py` from repository root: **4 existing errors in T10 `app/summaries/repository.py`**, no errors reported in this test. Python 3.13.4, mypy 2.1.0, SQLAlchemy 2.0.50. Nahuel independently reproduced these and rectified his earlier mypy-PASS report; T10 task reopened and correction is running. This RED PR is draft, not declared ready until inherited gate is resolved.

## Cleanup

Confirmed zero public tables in the disposable `sauri_t15_reads` database after test teardown. Removed own PostgreSQL and RabbitMQ containers **with volumes** (`docker rm -fv`), verified neither remains. No personal service or persistent project data touched.

## Next

T16 depends on T12 as well as this RED. Preserve `73df389` in the GREEN ancestry, pass all nine read/request tests, and keep D9 plus actual Ollama availability independently gated. No merge requested for this RED-only branch.
