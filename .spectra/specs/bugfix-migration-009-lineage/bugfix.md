# Bugfix — Reconcile Migration 009 Lineage and Deterministic Source-Inventory Tests

## Bug Description

The original defect report described nondeterministic source-inventory migration selection and two Alembic heads for the sibling 009 revisions. The graph condition has since been corrected on `main` by the shipped `010_speaker_excerpt_reference` revision, whose parents are exactly the two published 009 revisions. The remaining failures are stale graph-test assertions (T-3 / PR #414) that encode the pre-010 topology, plus an offline-SQL acceptance command that cannot execute the published source-inventory backfill. A separate Alembic version-column-width defect currently blocks an end-to-end database upgrade and is owned by the `alembic-version-id-width` spec.

**Evidence and expected-behavior authority:** The original source-inventory behavior remains bounded by the approved contracts in `meeting-review-playback/tasks.md` T-1/T-2 and `recording-speaker-review/tasks.md` T-2, not new product scope. The original QA reproduction and its raw logs are recorded in [QA reproduction evidence](qa-reproduction.md). Current-state reproductions and exact environment details are in [lineage contract amendment evidence](evidence/lineage-contract-amendment-evidence.md), collected against `origin/main` `58abc1e51c87c6ab435a88f792546be187c0f8d1`. That evidence records the single `010_speaker_excerpt_reference` head, the two failing T-3 assertions, the `--sql` failure at `op.get_bind()`, and the independent `alembic_version.version_num VARCHAR(32)` blocker. With that column widened only in a throwaway diagnostic database, the existing graph upgraded from 008 to 010 and applied both 009 branch effects once; that diagnostic is not authorization to widen the column in this spec.

## Steps to Reproduce

From `backend/` on the evidence snapshot, use the configured interpreter recorded in the evidence file:

1. Run `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py`. The T-3 graph tests fail because their assertions assume an 008-inclusive result from an `iterate_revisions()` query whose lower boundary is excluded, and assume the pre-010 graph.
2. Run `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic heads`. It reports the single head `010_speaker_excerpt_reference`.
3. Run `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic upgrade 008_speaker_review_aggregate:head --sql`. It fails when `009_recording_media_sources.upgrade()` calls `op.get_bind()` in offline mode and attempts to use the absent bind.
4. On a disposable PostgreSQL database, an upgrade through the receipts branch is currently blocked when Alembic records its 39-character revision ID in `alembic_version.version_num VARCHAR(32)`. The independent defect and its owner spec are identified above; do not alter that column as part of this bugfix.

The complete command outputs, interpreter versions, and the throwaway-database diagnostic are captured in the amendment evidence. No live/shared database was used.

## Current Behavior (Defect)

WHEN the T-3 graph tests run against the shipped migration graph, THEN two assertions fail because they describe the pre-010 topology and use revision traversal boundaries that exclude the lower-bound revision they expect to find.

WHEN the offline SQL acceptance command traverses `009_recording_media_sources`, THEN the migration attempts to use `op.get_bind()` even though offline mode provides no bind, and SQL generation fails before producing an upgrade plan.

WHEN a disposable PostgreSQL database upgrades from the common 008 state before the separate version-width defect is fixed, THEN Alembic fails to store the 39-character `009_speaker_review_idempotency_receipts` revision in `alembic_version.version_num VARCHAR(32)`; this failure is not evidence of a broken lineage graph.

## Expected Behavior (Correct)

WHEN the migration graph includes the two published 009 revisions, THEN Alembic SHALL expose exactly one head, `010_speaker_excerpt_reference`, whose immediate parents are exactly `009_recording_media_sources` and `009_speaker_review_idempotency_receipts`, and whose full ancestry includes `008_speaker_review_aggregate` and both 009 revisions.

WHEN graph tests inspect ancestry or upgrade paths, THEN the tests SHALL use Alembic traversal semantics correctly, SHALL assert the shipped 010 topology, and SHALL verify that upgrading from either published 009 state reaches the single head through the missing sibling without changing either historical revision identity. They SHALL NOT require 008 to appear inside a traversal that excludes its lower boundary.

WHEN a database is upgraded from 008 to the single head after the separately owned version-width defect is resolved, THEN both published 009 migration effects and the 010 excerpt-reference effect SHALL be applied exactly once, and the recorded head SHALL be `010_speaker_excerpt_reference`.

WHEN T-6 / Issue #407 is reconciled with this amended contract, THEN its prescribed deliverable of adding a new no-op merge revision SHALL be treated as already satisfied by the existing 010 mergepoint; no second merge revision over the same parents SHALL be added. T-6's remaining obligation SHALL be narrowed to verifying the existing graph and its upgrade-path contract, and the obsolete implementation issue/card SHALL be reconciled by the planning phase rather than implemented as a new migration.

WHEN upgrade validation is specified, THEN it SHALL NOT depend on `alembic upgrade 008_speaker_review_aggregate:head --sql`, because the published 009 backfill is not executable in offline mode. Structural graph tests and `alembic heads` SHALL validate lineage independently. End-to-end upgrade validation SHALL use a disposable PostgreSQL database and SHALL be gated on completion of the version-width fix in `.spectra/specs/alembic-version-id-width/`; that prerequisite's implementation and schema change are outside this spec.

WHEN the source-inventory regression tests select their target migration, THEN they SHALL continue to select `009_recording_media_sources` explicitly and independently of filesystem enumeration order.

## Unchanged Behavior (Regression Prevention)

WHEN legacy recordings have audio and optional video references, THEN the source-inventory migration SHALL CONTINUE TO backfill exactly one audio source per `audio_ref` and a video source only for a non-null `video_ref`, leave unavailable MIME and video offset values null, set legacy video presence to `unknown`, and preserve original references through downgrade and re-upgrade. (Approved source: `meeting-review-playback/tasks.md` T-1/T-2.)

WHEN duplicate `(recording_id, kind, object_ref)` source rows are inserted, THEN the existing uniqueness constraint SHALL CONTINUE TO reject the duplicate. (Approved source: `meeting-review-playback/tasks.md` T-1/T-2.)

WHEN speaker-review disposition writes are retried with the same idempotency key, THEN the receipt migration SHALL CONTINUE TO provide its approved persistence structure and this fix SHALL NOT change receipt fields, key uniqueness, or their foreign-key relationships. (Approved source: `recording-speaker-review/tasks.md` T-2 and `requirements.md` Requirement 3, AC 5.)

WHEN a database already records either historical 009 revision as applied, THEN the graph SHALL CONTINUE TO recognize that same revision identity and SHALL allow the missing sibling to be traversed without falsifying or deleting Alembic history.

WHEN unrelated migrations before 008 or after the 010 convergence point are traversed, THEN their existing schema and data behavior SHALL CONTINUE unchanged.

## Fix Constraints

- This bugfix phase is limited to the source-inventory test selection contract and migration-graph validation contract. Do not modify application code, feature behavior, approved feature specifications, either published 009 revision, or the shipped `010_speaker_excerpt_reference` revision.
- Do not create another merge revision over the two 009 parents; 010 already converges those branches and has real feature DDL.
- Correct the stale graph-test contract to the existing 010 graph; do not weaken the graph checks or retain assertions for a nonexistent second mergepoint.
- Replace offline SQL acceptance with structural graph checks and, only after the separately owned width fix, an end-to-end upgrade on a disposable PostgreSQL database. Do not manually widen a shared or live database, and do not include the version-column fix in this spec.
- Preserve both published 009 revision identities and their effects. Do not drop, recreate, or silently skip existing recording or idempotency data.
- Use only synthetic migration-test rows and disposable infrastructure; never run destructive migrations against a shared or live database.

## Acceptance Criteria

1. WHEN the three named source-inventory pytest nodes run independently, THE tests SHALL select `009_recording_media_sources` deterministically and SHALL pass their backfill, round-trip, and duplicate-rejection assertions.
2. WHEN the graph tests inspect Alembic's script directory, THE graph SHALL have exactly one head (`010_speaker_excerpt_reference`), with immediate parents exactly the two published 009 IDs and full ancestry containing both 009 IDs plus `008_speaker_review_aggregate`; the tests SHALL account for the exclusive lower boundary of `iterate_revisions()`.
3. WHEN graph tests plan an upgrade from either existing 009 revision, THE plan SHALL reach `010_speaker_excerpt_reference` by applying the missing sibling once while retaining the starting revision's identity; test assertions SHALL account for Alembic excluding the starting lower-bound revision from traversal results.
4. WHEN the migration graph is validated, `alembic heads` SHALL report exactly `010_speaker_excerpt_reference`. The offline SQL command SHALL NOT be an acceptance gate because the published backfill requires a live bind.
5. WHEN an end-to-end upgrade is exercised from the common 008 state, it SHALL use a disposable PostgreSQL database after the `alembic-version-id-width` prerequisite is complete; the upgrade SHALL reach 010 and both branch effects SHALL be present exactly once. Until that prerequisite is complete, this criterion is blocked by that independently owned issue, not waived or reported as passing.
6. WHEN the unchanged playback/source-inventory and speaker-review idempotency migration contracts are exercised, THE fix SHALL CONTINUE TO preserve their approved backfill, downgrade/re-upgrade, uniqueness, and receipt-persistence behavior; no feature-scope behavior changes are included.
