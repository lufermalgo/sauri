# Bugfix — Unify Migration 009 Lineage and Deterministic Source-Inventory Tests

## Bug Description

The migration source-inventory tests select whichever migration file is encountered first with `down_revision == "008_speaker_review_aggregate"`; because both 009 revisions satisfy that predicate, the tests can execute the speaker-review idempotency-receipts migration instead of the source-inventory migration and fail when that migration tries to create an already-existing receipts table. Independently, Alembic sees both 009 revisions as heads and cannot resolve `upgrade head`, leaving no single unambiguous upgrade path that includes both approved changes.

**Evidence and expected-behavior authority:** Nia's independently captured command outputs, interpreter/version, exit statuses, and findings are recorded in the [QA reproduction evidence](qa-reproduction.md), with full raw outputs linked there. The evidence identifies three failing source-inventory test nodes and the duplicate-table error. At baseline `0d6f2713abcf08d960e98451b04bbdd31b4c8843`, each named pytest node failed with `sqlite3.OperationalError: table speaker_review_idempotency_receipts already exists`; `python -m alembic heads` listed both `009_recording_media_sources` and `009_speaker_review_idempotency_receipts` as heads; `python -m alembic upgrade head --sql` exited 255 with `Multiple head revisions are present`. The expected behaviors below are limited to the approved migration contracts in `meeting-review-playback/tasks.md` T-1/T-2 and `recording-speaker-review/tasks.md` T-2, not new product scope.

## Steps to Reproduce

From the `backend/` directory of the stated worktree, run each deterministic node separately with the available project interpreter:

1. `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_migration_backfills_only_explicit_legacy_sources`
2. `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_downgrade_preserves_refs_and_reupgrade_backfills`
3. `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_source_inventory_rejects_duplicate_recording_kind_and_reference`
4. `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic heads`
5. `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic upgrade head --sql`

Observed: all three test nodes currently fail during upgrade with a duplicate `speaker_review_idempotency_receipts` table error; the heads command reports two heads; the SQL upgrade fails because `head` is ambiguous. The test helper in `backend/tests/test_migration.py` scans migration files and returns the first module whose `down_revision` matches `008_speaker_review_aggregate`, without selecting by revision identity. Both current 009 files have that parent.

**Environment:** Worktree branch `bugfix/migration-009-lineage-evidence`, base `0d6f2713abcf08d960e98451b04bbdd31b4c8843`; backend tests use the isolated SQLite fixture. Alembic's SQL-generation command uses the configured PostgreSQL dialect and does not mutate a database. The unqualified shell `python` was unavailable in this environment; the exact configured interpreter above was used successfully instead.

## Current Behavior (Defect)

WHEN the source-inventory regression tests search for a migration after `008_speaker_review_aggregate`, THEN the test helper may load either sibling 009 migration based on filesystem enumeration order rather than selecting the source-inventory revision explicitly.

WHEN the Alembic graph contains both sibling 009 revisions and an operator requests `alembic upgrade head`, THEN Alembic reports multiple heads and does not generate the requested single-head upgrade plan.

## Expected Behavior (Correct)

WHEN the source-inventory regression tests select the migration under test, THEN the tests SHALL deterministically select `009_recording_media_sources`, independent of migration-file enumeration order, and SHALL exercise its existing backfill, downgrade/re-upgrade, and uniqueness behavior.

WHEN the migration graph contains both approved 009 changes, THEN the Alembic revision history SHALL expose one unambiguous upgrade head whose path includes both `009_recording_media_sources` and `009_speaker_review_idempotency_receipts`.

WHEN that single head is upgraded from the common 008 predecessor, THEN both approved migration effects SHALL be present, including the recording media-source schema/backfill and speaker-review idempotency-receipt schema, without either revision's operation being silently omitted or applied twice.

WHEN a previously applied migration history must be reconciled, THEN the fix SHALL preserve the existing migration identities and the data/schema effects of both approved migrations; it SHALL NOT resolve ambiguity by dropping either migration or its persisted data.

## Unchanged Behavior (Regression Prevention)

WHEN legacy recordings have audio and optional video references, THEN the source-inventory migration SHALL CONTINUE TO backfill exactly one audio source per `audio_ref` and a video source only for a non-null `video_ref`, leave unavailable MIME and video offset values null, set legacy video presence to `unknown`, and preserve original references through downgrade and re-upgrade. (Approved source: `meeting-review-playback/tasks.md` T-1/T-2.)

WHEN duplicate `(recording_id, kind, object_ref)` source rows are inserted, THEN the existing uniqueness constraint SHALL CONTINUE TO reject the duplicate. (Approved source: `meeting-review-playback/tasks.md` T-1/T-2.)

WHEN speaker-review disposition writes are retried with the same idempotency key, THEN the receipt migration SHALL CONTINUE TO provide its approved persistence structure and the fix SHALL NOT change receipt fields, key uniqueness, or their foreign-key relationships. (Approved source: `recording-speaker-review/tasks.md` T-2 and `requirements.md` Requirement 3, AC 5.)

WHEN a database already records either historical 009 revision as applied, THEN the repaired graph SHALL CONTINUE TO recognize that same revision identity and SHALL NOT require falsifying or deleting its Alembic version history.

WHEN unrelated migrations before 008 or after the reconciled 009 path are traversed, THEN their existing schema and data behavior SHALL CONTINUE unchanged.

## Fix Constraints

- This bugfix phase specifies the defect only; do not modify application code, feature behavior, or either approved feature specification.
- Keep the two existing 009 revision identities and their approved migration effects. Prefer an additive Alembic merge revision to rewriting an already-published migration lineage; any alternative must demonstrate compatibility with databases that may have either 009 revision recorded.
- Make the source-inventory test choose the exact migration it is meant to validate rather than depending on filesystem order.
- Do not drop, recreate, or silently skip existing recording or idempotency data to make the graph appear linear.
- Use only synthetic migration-test rows; do not run destructive migrations against a shared or live database.

## Acceptance Criteria

1. WHEN the three named source-inventory pytest nodes run independently, THE tests SHALL choose `009_recording_media_sources` deterministically and SHALL pass their backfill, round-trip, and duplicate-rejection assertions.
2. WHEN Alembic inspects the repaired revision graph, THE graph SHALL report one head and that head's ancestry SHALL contain both existing 009 revision IDs.
3. WHEN `alembic upgrade head --sql` is run from the common 008 predecessor, THE generated SQL SHALL include both 009 migration effects exactly once and SHALL complete without a multiple-head error.
4. WHEN the graph is applied to a database already at either existing 009 revision, THE migration plan SHALL preserve that revision's identity and allow the other branch's effect plus the reconciliation to be applied without losing existing schema or data.
5. WHEN the unchanged playback/source-inventory and speaker-review idempotency migration contracts are exercised, THE fix SHALL CONTINUE TO preserve their approved backfill, downgrade/re-upgrade, uniqueness, and receipt-persistence behavior; no feature-scope behavior changes are included.
