# QA Reproduction — Migration 009 Lineage

## Identity and scope

- Worktree: `/Users/lufermalgo/Proyectos/sauri/.worktrees/bugfix-migration-009-lineage-evidence`
- Branch: `bugfix/migration-009-lineage-evidence`
- Tested worktree HEAD: `47a0d6a39f3c949477bfe07f547c8c45156a50ad` (bugfix-spec documentation commit)
- Source baseline / `origin/main`: `0d6f2713abcf08d960e98451b04bbdd31b4c8843`
- Verified with `git diff --quiet 0d6f2713abcf08d960e98451b04bbdd31b4c8843 HEAD -- backend/tests/test_migration.py backend/alembic/versions`: migration/test source files are unchanged from the diagnosed baseline.
- Environment: Python 3.14.7 at `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python`; pytest nodes use the project's isolated SQLite fixture. Alembic SQL generation reports `PostgresqlImpl` and is offline (`--sql`); no live/shared database was used.
- Read-only reproduction only: no application, migration, test, or specification implementation edits. All test data is synthetic.

## Approved behavior authorities

- `.spectra/specs/meeting-review-playback/tasks.md`, T-1/T-2, approved task-plan commit `8537e154ab06680422d8bd42111ca64339bfb4bf`: source inventory migration from `008_speaker_review_aggregate`; exact audio/video backfill rules; unknown legacy presence; preserving refs through downgrade/re-upgrade; duplicate tuple rejection.
- `.spectra/specs/recording-speaker-review/tasks.md`, T-2, approved task-plan commit `576a6a992db4452a653a7112f394e73da5177792`: separate idempotency-write contract; no alteration to its persisted migration behavior is in scope here.

## Commands and results

Commands were run individually from the worktree's `backend/` directory, with the exact interpreter specified in `bugfix.md`.

| Command | Exit | Result |
|---|---:|---|
| `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_migration_backfills_only_explicit_legacy_sources` | 1 | Failed; `sqlite3.OperationalError: table speaker_review_idempotency_receipts already exists`; pytest summary: `1 failed in 0.25s`. Full raw output: [`qa-node1.raw.log`](qa-node1.raw.log). |
| `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_downgrade_preserves_refs_and_reupgrade_backfills` | 1 | Failed with the same duplicate-table error; summary: `1 failed in 0.26s`. Full raw output: [`qa-node2.raw.log`](qa-node2.raw.log). |
| `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_rejects_duplicate_recording_kind_and_reference` | 1 | Failed with the same duplicate-table error; summary: `1 failed in 0.22s`. Full raw output: [`qa-node3.raw.log`](qa-node3.raw.log). |
| `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic heads` | 0 | Listed two heads: `009_recording_media_sources (head)` and `009_speaker_review_idempotency_receipts (head)`. Full raw output: [`qa-heads.raw.log`](qa-heads.raw.log). |
| `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic upgrade head --sql` | 255 | Failed with `Multiple head revisions are present for given argument 'head'`; SQL generation did not run through a unique head. Full raw output: [`qa-upgrade.raw.log`](qa-upgrade.raw.log). |

## Finding

The three isolated test failures reproduce consistently: the selected migration attempts to create `speaker_review_idempotency_receipts`, which already exists in the SQLite test schema. The Alembic graph independently has two heads, so `upgrade head --sql` is ambiguous. This is reproduction evidence, not a fix verification, PASS, product acceptance, security assessment, or release decision. No repair was attempted.
