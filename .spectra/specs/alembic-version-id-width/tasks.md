# Implementation Plan — Alembic Revision ID Width Bugfix

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | Required pre-GREEN tests for forward migration, atomicity, schema, identity, and downgrade properties | T-1–T-5 | T-1 → T-2 → T-3 → T-4 → T-5 (shared test module) |
| 2 | GREEN migration-local width fix | T-6 | T-1–T-5 (required tests run before changing migration code; T-1, T-2, and T-5 demonstrate the defect, while T-4 is an unchanged-behavior guard expected to pass on baseline) |

## Phase 1: Required Pre-GREEN Tests

### T-1 (RED): Reproduce and specify the 008-to-receipts upgrade

**Type:** Required test (RED)
**Test seam:** `backend/tests/test_migration.py`, `test_speaker_receipt_upgrade_records_full_revision_id`; load and exercise `upgrade()` from `backend/alembic/versions/009_speaker_review_idempotency_receipts.py` through Alembic's migration runner against an isolated synthetic PostgreSQL 16 database.
**Action:** Add a migration integration test that starts at `008_speaker_review_aggregate`, targets exactly `009_speaker_review_idempotency_receipts` (never `head`), and asserts successful upgrade, the exact full revision string in `alembic_version`, `character_maximum_length = 39`, and receipts-table presence. Reuse the isolated PostgreSQL setup and command recorded with QA reproduction `task_79c4eb9f8b6347ab`; do not use shared/live databases. Run the test before implementation and retain evidence that the current candidate fails at version recording.
**Acceptance evidence:** The test fails before T-6 because PostgreSQL rejects the revision ID as too long, and passes after T-6; the isolated database contains the exact target revision and receipts table after success.
**Validation:** From `backend/`, run `.venv/bin/python -m pytest tests/test_migration.py -k speaker_receipt_upgrade_records_full_revision_id` with QA's recorded isolated PostgreSQL 16 setup; then run `.venv/bin/python -m pytest tests/test_migration.py`.
**Dependencies:** None
**Tracking:** Issue #488 · Card task_c6e986eef9e744aa · PR #495

### T-2 (RED): Specify rollback atomicity after widening

**Type:** Required test (RED)
**Test seam:** `backend/tests/test_migration.py`, `test_speaker_receipt_upgrade_failure_rolls_back_width`; migration runner invoking `upgrade()` from `backend/alembic/versions/009_speaker_review_idempotency_receipts.py` on an isolated PostgreSQL 16 database.
**Action:** Add a controlled-failure integration test at revision 008 using a synthetic pre-existing receipts-table collision. Observe migration SQL/DDL to assert that widening `alembic_version.version_num` is attempted before the collision failure; this assertion must fail against the unfixed candidate because no widening occurs. Then assert transaction rollback leaves revision 008, restores `version_num` width to 32, and preserves the collision fixture unchanged. All setup/teardown must be confined to the disposable database.
**Acceptance evidence:** Before T-6, the test fails because the required pre-table widening is absent; after T-6, the controlled failure leaves revision 008, width 32, and the collision fixture unchanged, with no partially-created receipt schema.
**Validation:** From `backend/`, run `.venv/bin/python -m pytest tests/test_migration.py` with QA's recorded isolated PostgreSQL 16 setup.
**Dependencies:** T-1 (both edit `backend/tests/test_migration.py`; serialize to avoid merge conflicts).
**Tracking:** Issue #489 · Card task_768da269dd9d4c81 · PR #496

### T-3 (RED): Lock receipt schema and uniqueness behavior

**Type:** Required test (RED)
**Test seam:** `backend/tests/test_migration.py`, `test_speaker_review_receipt_migration_preserves_persisted_contract`; inspect the migrated PostgreSQL schema created by `upgrade()` in `backend/alembic/versions/009_speaker_review_idempotency_receipts.py`.
**Action:** Add isolated PostgreSQL 16 assertions for the existing receipt table's exact column names, types, and nullability; both cascading foreign keys; and the named unique constraint over `(review_id, idempotency_key)`. Insert synthetic valid rows and verify a duplicate key is rejected. Do not alter the schema contract or use real data. Demonstrate this regression test before T-6.
**Acceptance evidence:** Test assertions cover all specified columns and constraints, and duplicate-key insertion raises the database integrity error; it passes against the fixed migration without changing the existing receipt schema.
**Validation:** From `backend/`, run `.venv/bin/python -m pytest tests/test_migration.py` with QA's recorded isolated PostgreSQL 16 setup.
**Dependencies:** T-2 (both edit `backend/tests/test_migration.py`; serialize to avoid merge conflicts).
**Tracking:** Issue #490 · Card task_3e697f0243b24be2

### T-4: Guard published revision identities and parent links

**Type:** Required unchanged-behavior regression test (pre-GREEN; baseline expected to pass)
**Test seam:** `backend/tests/test_migration.py`, `test_published_009_revision_ids_and_immediate_parent_are_preserved`; import `revision` and `down_revision` from both `backend/alembic/versions/009_speaker_review_idempotency_receipts.py` and `backend/alembic/versions/009_recording_media_sources.py`, and inspect `ScriptDirectory` for the resulting Alembic graph.
**Action:** Add regression assertions that both published revision IDs and their existing parent declarations remain exact and appear in the script graph. Keep the target upgrade explicit; the assertions must not require `alembic upgrade head` to succeed or reconcile the sibling-009 graph.
**Acceptance evidence:** Run this guard before T-6 and retain its passing result for both modules' exact revision/down-revision values and graph entries; it remains passing after T-6. It does not assert `alembic upgrade head` succeeds or that `head` is unambiguous.
**Validation:** From `backend/`, run `.venv/bin/python -m pytest tests/test_migration.py`.
**Dependencies:** T-3 (both edit `backend/tests/test_migration.py`; serialize to avoid merge conflicts).
**Tracking:** Issue #491 · Card task_10bb77d585bc4308

### T-5 (RED): Specify downgrade and re-upgrade behavior

**Type:** Required test (RED)
**Test seam:** `backend/tests/test_migration.py`, `test_speaker_receipt_downgrade_keeps_width_and_allows_reupgrade`; Alembic runner targeting `downgrade()` and `upgrade()` in `backend/alembic/versions/009_speaker_review_idempotency_receipts.py` on an isolated synthetic PostgreSQL 16 database.
**Action:** Add integration assertions that after upgrade then downgrade to `008_speaker_review_aggregate`, the receipts table is removed while `alembic_version.version_num` remains length 39; re-upgrading records the exact 39-character receipts revision and restores the existing receipt schema. Demonstrate the test before T-6; do not test sibling branch reconciliation.
**Acceptance evidence:** Downgrade removes the receipt table without narrowing the version column, and re-upgrade succeeds with the exact target revision and schema.
**Validation:** From `backend/`, run `.venv/bin/python -m pytest tests/test_migration.py` with QA's recorded isolated PostgreSQL 16 setup.
**Dependencies:** T-4 (both edit `backend/tests/test_migration.py`; serialize to avoid merge conflicts).
**Tracking:** Issue #492 · Card task_5d53808ed8a44d90

## Phase 2: GREEN Migration Fix

### T-6 (GREEN): Widen Alembic's version column in the receipts migration

**Type:** Required implementation
**Files:** `backend/alembic/versions/009_speaker_review_idempotency_receipts.py`
**Action:** At the beginning of that migration's `upgrade()`, before receipt-table operations, use `op.alter_column` to widen `alembic_version.version_num` from `sa.String(length=32)` to exactly `sa.String(length=39)`. Keep the widening in the same PostgreSQL migration transaction. Do not change either published 009 revision identity, parent relationship, receipt schema/operations, downgrade behavior (which must not shrink the column), migration graph, or introduce a later migration.
**Acceptance evidence:** On isolated synthetic PostgreSQL 16, T-1, T-2, and T-5 each fail before T-6 for the documented width defect and pass after T-6; T-3 schema assertions pass without schema changes, and T-4's published-identity guard passes both before and after T-6.
**Validation:** From `backend/`, run `.venv/bin/python -m pytest tests/test_migration.py` with QA's recorded isolated PostgreSQL 16 setup.
**Dependencies:** T-1, T-2, T-3, T-4, T-5 (mandatory test-before-code order; the shared `backend/tests/test_migration.py` also serializes these tasks to avoid edit conflicts).
**Tracking:** Issue #493 · Card task_16c458c020924ae0

## Validation Prerequisites and Scope Boundaries

- Use synthetic fixtures and the dedicated isolated PostgreSQL 16 test database/setup recorded by QA subtask `task_79c4eb9f8b6347ab`. Never run migration tests against a shared or live database. New worktrees do not include a backend virtual environment by default; provision/use the configured backend interpreter before running the stated pytest command.
- Target `009_speaker_review_idempotency_receipts` explicitly. `alembic upgrade head` and reconciliation of the sibling `009_recording_media_sources` graph are outside this bugfix.
- The proposed 39-character forward-upgrade criterion is the approved bugfix's proposed criterion, not a claim of an earlier width-specific contract.
- Each approved task will be tracked as one GitHub issue and one APX card under the spec milestone; required test tasks carry `test` and `pbt` labels where applicable. The implementation task proceeds through independent Nia QA after its developer work; add a Zev gate only if the approved issue/card specifies a security review. Issue/card references are recorded in each task's Tracking line.
