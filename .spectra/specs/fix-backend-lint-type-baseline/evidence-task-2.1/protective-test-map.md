# T-2.1 protective-test map (partial; handoff required)

## Identity and scope

- Approved plan: `tasks.md`, blob `a8c45e1dd86739d3756829a21015604cf7d938cfc`.
- Worktree: `/Users/lufermalgo/Proyectos/sauri/.worktrees/feature-issue-264-lint-baseline-protective-tests`; branch `feature/issue-264-lint-baseline-protective-tests`.
- Current production base: `576a6a992db4452a653a7112f394e73da5177792` (`origin/main`). This is newer than Task 1.2's recorded baseline `a6c74bb92b286e7819602a07e47785ee7ba1f78c`; the production diagnostic inventory in `evidence-task-1.2/diagnostic-inventory.md` is therefore inherited evidence, not re-established for current base.
- Test-only commit: `9b7988fb49dbac249e59b49b55a17c4a69e0cf91` (ASR cleanup protective tests). No production edits.
- Tool environment: `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python`.

## Verification performed on current base

1. `cd backend && /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/transcription/test_asr_engine_service.py` — **2 passed** (0.18s). Covers partial S3 download cleanup/cause chaining and transcription-error HTTP 500/temp-file cleanup using synthetic data.
2. `cd backend && /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check tests/transcription/test_asr_engine_service.py` — **passed**.
3. `cd backend && /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m mypy tests/transcription/test_asr_engine_service.py` — **passed**, no issues.
4. `cd backend && /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/ingestion/test_playback_source_ingestion.py tests/test_migration.py` — **19 passed, 3 failed**. The ingestion playback-source tests pass. The three migration tests (`test_source_inventory_migration_backfills_only_explicit_legacy_sources`, `test_source_inventory_downgrade_preserves_refs_and_reupgrade_backfills`, `test_source_inventory_rejects_duplicate_recording_kind_and_reference`) enter `009_speaker_review_idempotency_receipts.py:upgrade` and fail attempting to create `speaker_review_idempotency_receipts`, which already exists in their SQLite fixture (`sqlite3.OperationalError`). Per handoff instruction, no further migration investigation/editing was performed.
5. `cd backend && /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/auth tests/diarization tests/diar_engine tests/infra tests/ingestion tests/meetings tests/transcription tests/speaker_review tests/test_queue.py` — **213 passed, 1 failed** (18.76s). Failure: `tests/speaker_review/test_review_state.py::test_review_put_schema_excludes_completion`, `KeyError` for missing speaker-review PUT path in `app.openapi()`. This is outside production diagnostic paths in Task 1.2; it is a limitation/unrelated RED, not evidence of a defect in the lint/type task. Four Starlette deprecation warnings occurred in ingestion tests.

## Inventory-to-test-area map (initial mapping; exact node selection still needs completion)

Classification is provisional and applies only to the recorded Task 1.2 diagnostics. Import ordering, annotation/typing modernization, naming, and structurally equivalent context-manager rewrites are provisionally static; exception chaining, dependency defaults, and resource cleanup are behavior-observable and need path-specific evidence. Ambiguous cases must be resolved before producer edits.

| Diagnostic production paths | Initial behavior classification | Candidate existing focused test areas |
|---|---|---|
| `alembic/env.py`; `alembic/versions/001_initial_schema.py`–`007_rename_schema_to_english.py` | Static/import/typing/line-length only | `tests/test_migration.py`; per-migration coverage must be selected by exact nodes. Current migration suite anomaly is recorded above and blocks this group pending Ansel. |
| `app/auth/audit.py`, `app/auth/token.py` | Static (`UP017`) | `tests/auth/` (audit/token focused modules still need exact-node mapping). |
| `app/auth/authorization.py`, `app/auth/dependencies.py` | Potentially behavior-bearing (`B008`, `B904`); do not infer semantic equivalence without checking precise edits | `tests/auth/` (exact nodes still needed). |
| `app/diarization/assignment.py`, `app/diarization/state.py` | Static import ordering | `tests/diarization/test_assignment_property.py`, `test_state_property.py`. |
| `app/diarization/cloud_provider.py`, `app/transcription/cloud_provider.py` | Behavior-bearing exception chaining (`B904`) | `tests/diarization/test_cloud_provider_property.py`; `tests/transcription/test_cloud_provider.py`. |
| `app/diarization/worker.py` | Mixed: imports/context-manager style (`I001`, `SIM117`) plus datetime modernization (`UP017`) | `tests/diarization/test_worker.py`; inspect whether cleanup/exception behavior is affected before classifying final. |
| `app/infra/models.py` | Static import ordering | `tests/infra/` and `tests/test_migration.py`; exact model contract nodes still needed. |
| `app/ingestion/router.py` | Behavior-bearing: dependency defaults, exception chaining, and nested context management may affect request/error/resource behavior | `tests/ingestion/test_playback_source_ingestion.py` (all 19 relevant ingestion/migration subset passes on current base); exact node IDs still needed. |
| `app/meetings/router.py` | Potentially behavior-bearing (`B008`, `B904`); remaining findings are naming/import/context-manager form | `tests/meetings/`, `tests/speaker_review/`; exact nodes still needed. |
| `app/meetings/schemas.py`, `app/meetings/service.py`, `app/meetings/state_machine.py` | Static typing/name/import transformations (`UP007`, `A002`, `I001`) | `tests/meetings/` and speaker-review state tests; exact nodes still needed. |
| `asr-engine/main.py` | Behavior-bearing: exception wrapping, suppress/close handling (`B904`, `SIM105`, `SIM115`) | New `tests/transcription/test_asr_engine_service.py` tests cleanup and chaining; 2/2 passed. Review each SIM rewrite against intended semantics before production edit. |
| `diar-engine/main.py` | Behavior-bearing: exception wrapping and file cleanup/context suppression (`B904`, `SIM105`, `SIM115`) | `tests/diar_engine/test_contract.py`; path-specific cleanup/failure coverage not yet identified or authored. |

## Current disposition and remaining work

This ledger is intentionally partial. The affected-path map is not yet exhaustive at test-node granularity, semantic-equivalence evidence is not yet recorded for every static path, and the complete pre-correction focused evidence required immediately before each production edit is not delivered. The mismatch between Task 1.2 baseline `a6c74bb` and current rebased base `576a6a9` must be resolved by Ansel before treating the inventory as authoritative for this candidate. The migration failures need Ansel's disposition before this path can be relied on. No PASS/FAIL conclusion is made.
