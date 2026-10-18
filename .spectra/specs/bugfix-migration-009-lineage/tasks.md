# Implementation Tasks — Reconcile Migration 009 Lineage and Deterministic Source-Inventory Tests

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | RED tests for deterministic selection and unchanged inventory contracts | T-1 | None |
| 2 | GREEN deterministic migration selection | T-2 | T-1 |
| 3 | RED migration graph tests and receipt-preservation regression | T-3, T-5 | None |
| 4 | GREEN additive merge revision | T-6 | T-3 |

The phase labels group work only. T-1, T-3, and T-5 are independent and may run concurrently in separate worktrees. T-2 and T-6 are independent after their respective RED test prerequisites.

**Plan amendment:** T-4 (Issue #405 · Card `task_5ad97bbfec3147f6`) is retired as a separate RED task. The approved 009 branch effects are each emitted once when explicitly targeting both heads; the only pre-merge failure of the `:head` probe is the multiple-head graph defect already covered by T-3. Retain the exact-once offline SQL check as T-6 acceptance evidence, and reconcile the superseded Issue/card after Mira audits this amendment.

## Phase 1: RED Deterministic Source-Inventory Tests

### T-1: Assert exact source-inventory revision selection and preserved migration contracts (RED)

**Tracking:** Issue #402 · Card `task_686872373b8b442a` · PR #415

**Files:** `backend/tests/test_migration.py`

**Action:** Add or adapt tests at the `_source_inventory_migration()` seam so the loader must resolve revision `009_recording_media_sources` explicitly and fail rather than selecting by shared `down_revision` or enumeration order. Preserve and exercise the three existing regression nodes for explicit legacy backfill, downgrade/re-upgrade reference preservation, and duplicate `(recording_id, kind, object_ref)` rejection. Do not change migration code or fixtures to hide the defect.

**Acceptance evidence:** Before implementation, the relevant test demonstrates the current incorrect/ambiguous selection or fails its exact revision identity assertion; the three existing nodes remain independently runnable. Use only the synthetic SQLite fixture.

**Validation command (from `backend/`, configured interpreter from `qa-reproduction.md`):** `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py`

**Dependencies:** None

## Phase 2: GREEN Deterministic Source-Inventory Selection

### T-2: Resolve the source-inventory migration by exact revision (GREEN)

**Tracking:** Issue #403 · Card `task_c34ba91bb1e34ede` · PR #416

**Files:** `backend/tests/test_migration.py`

**Action:** Replace `_source_inventory_migration()`'s glob-and-first-parent selection with deterministic loading of the exact source-inventory migration and assert that the loaded module's `revision` equals `009_recording_media_sources`. Keep existing three named nodes and their contract assertions; do not edit either published 009 migration or the approved feature behavior.

**Acceptance evidence:** The three named source-inventory pytest nodes each pass independently and the full migration-test module passes; the loader asserts the exact revision identity. Data remains synthetic and isolated.

**Validation commands (from `backend/`, configured interpreter from `qa-reproduction.md`):**
- `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_migration_backfills_only_explicit_legacy_sources`
- `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_downgrade_preserves_refs_and_reupgrade_backfills`
- `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_rejects_duplicate_recording_kind_and_reference`
- `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py`

**Dependencies:** T-1 (mandatory RED-before-GREEN)

## Phase 3: RED Alembic Graph/Upgrade-Plan Tests and Preservation Regression

### T-3: Specify graph identity, single-head ancestry, and either-009 forward paths (RED)

**Tracking:** Task done · Issue #404 · Card `task_4199b13216924823` · PR #414

**Files/test seam:** `backend/tests/test_migration.py`; instantiate Alembic `ScriptDirectory` for the configured script location and use `ScriptDirectory.get_revision()`, `ScriptDirectory.get_heads()`, and `ScriptDirectory.iterate_revisions()` for revision identity, heads, ancestry, and upgrade-path planning.

**Action:** Add focused graph tests that assert both existing 009 revisions retain their IDs and immediate 008 parent; a new reconciliation revision has both exact 009 parents and is the only head; head ancestry includes both 009 IDs and 008; and upgrade-step planning from each existing 009 state reaches convergence via the missing sibling without replacing the existing revision identity. Assert paths structurally; do not claim database-executed PostgreSQL compatibility. Include traversal continuity for revisions before 008 and after the convergence point without changing their definitions.

**Acceptance evidence:** On the unrepaired graph, these assertions fail for the absent merge/single-head and convergence path, while clearly identifying each violated graph property. Tests use no live/shared database.

**Validation command (from `backend/`, configured interpreter from `qa-reproduction.md`):** `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py`

**Dependencies:** None

### T-5: Preserve speaker-review receipt migration contract (regression)

**Tracking:** Issue #406 · Card `task_38233e6f849d4033`

**Files:** `backend/tests/test_migration.py`; use the approved receipt migration at `backend/alembic/versions/009_speaker_review_idempotency_receipts.py` as the test seam.

**Action:** Add a synthetic migration-contract regression test for the existing receipt migration, checking that its approved receipt fields, `(review_id, idempotency_key)` uniqueness, and foreign-key relationships remain represented without changing its approved persisted schema contract. The test must not modify the published migration or claim product behavior beyond that contract.

**Acceptance evidence:** The test states the approved schema contract explicitly and fails if the receipt migration's approved persisted structure is altered. Use only synthetic/disposable test state; no live/shared database.

**Validation command (from `backend/`, configured interpreter from `qa-reproduction.md`):** `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py`

**Dependencies:** None

## Phase 4: GREEN Additive Lineage Reconciliation

### T-6: Add a schema-neutral merge revision for both published 009 branches (GREEN)

**Tracking:** Issue #407 · Card `task_73be9ff83e2242e4`

**Files:** `backend/alembic/versions/<new sequential merge revision>.py`

**Action:** Following the repository's existing Alembic revision naming convention, add a unique revision with `down_revision` containing exactly `009_recording_media_sources` and `009_speaker_review_idempotency_receipts`; provide explicit no-op `upgrade()` and `downgrade()` bodies. Verify the revision identifier is unique. Do not alter, rename, or rewrite either published 009 identity or migration body; do not introduce DDL, data writes, branch labels, dependencies, or feature behavior in the merge.

**Acceptance evidence:** T-3 graph and historical-009 path tests pass; `alembic heads` reports one head; offline SQL generation from `008_speaker_review_aggregate:head` completes and its captured output includes each approved branch effect exactly once, including source-inventory table creation and receipt table creation. The three source-inventory nodes and full migration-test module pass. Evidence must remain offline/synthetic; no live/shared or destructive database operation.

**Validation commands (from `backend/`, configured interpreter from `qa-reproduction.md`):**
- `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py`
- `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic heads`
- `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic upgrade 008_speaker_review_aggregate:head --sql`

**Dependencies:** T-3 (mandatory RED-before-GREEN for graph/lineage repair); T-5 is an independent preservation regression check.
