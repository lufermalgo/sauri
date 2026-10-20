# Bugfix — Alembic Revision ID Exceeds Version Column Width

## Bug Description

On a synthetic PostgreSQL 16 database at revision `008_speaker_review_aggregate`, upgrading to `009_speaker_review_idempotency_receipts` fails when Alembic records the 39-character revision identifier in `alembic_version.version_num`, which is `VARCHAR(32)`. The transaction leaves the database at revision 008 and the receipts table absent.

**QA evidence:** Nia reproduced this on candidate `f50e014add142fccc28175d7de07da59efa16ec4` in an assigned clean worktree using an isolated synthetic PostgreSQL 16 database. The upgrade to 008 succeeded; advancing to the receipts revision failed with `value too long for type character varying(32)`. The transaction left the database at 008. The disposable database was removed. See QA subtask `task_79c4eb9f8b6347ab` and its recorded reproduction details. The measured revision ID is 39 characters; earlier packet estimates of 40/31 were corrected.

**Expected-behavior authority and boundary:** No approved width-specific migration contract was found. The approved related source `.spectra/specs/bugfix-migration-009-lineage/bugfix.md` (Mira-approved) requires preserving existing 009 revision identities, but does not define version-column width handling. The forward-upgrade criterion below is therefore explicitly proposed for this bugfix review, not represented as pre-existing approved behavior.

## Reproduction Steps

1. Use an isolated synthetic PostgreSQL 16 database and the assigned candidate `f50e014add142fccc28175d7de07da59efa16ec4`.
2. Apply migrations through `008_speaker_review_aggregate` successfully.
3. Attempt to advance to `009_speaker_review_idempotency_receipts`.
4. Observe PostgreSQL reject the Alembic version update with `value too long for type character varying(32)`; confirm the failed transaction leaves the database at revision 008 and does not create the receipts table.

**Observed reproducibility:** QA reproduced the failure once in a deterministic isolated database. Exact setup and command transcript are recorded on subtask `task_79c4eb9f8b6347ab`.

## Current Behavior (Defect)

WHEN a PostgreSQL 16 database at `008_speaker_review_aggregate` is upgraded to `009_speaker_review_idempotency_receipts`, THEN Alembic fails to persist the 39-character revision identifier because `alembic_version.version_num` is `VARCHAR(32)`, and the migration transaction remains at 008.

## Expected Behavior (Correct)

**Proposed technical criterion for this bugfix; not an existing width-specific approved contract:**

WHEN a supported clean/local PostgreSQL database at `008_speaker_review_aggregate` is upgraded to `009_speaker_review_idempotency_receipts`, THEN the migration SHALL complete and Alembic SHALL persist the full revision identifier without truncation, leaving the database at the intended revision and the migration's receipts table present.

## Unchanged Behavior (Regression Prevention)

WHEN the migration graph encounters either published 009 revision identity, THEN the fix SHALL CONTINUE TO preserve those existing revision identities and SHALL NOT rewrite or falsify persisted Alembic version history. This preservation boundary is supported by the Mira-approved `.spectra/specs/bugfix-migration-009-lineage/bugfix.md`; it does not independently authorize a particular width-handling implementation.

WHEN the receipts migration creates its existing persistence structure, THEN the fix SHALL CONTINUE TO retain the approved receipt schema, fields, key uniqueness, and foreign-key relationships. (Approved source: `.spectra/specs/bugfix-migration-009-lineage/bugfix.md`, unchanged behavior section.)

## Fix Constraints

- Keep this bugfix limited to Alembic's inability to record the observed 009 revision identifier during the forward upgrade; do not expand into unrelated migration-lineage changes.
- Preserve existing published 009 revision identities and their migration effects.
- Use synthetic data and an isolated database for migration validation; do not run destructive migrations against a shared or live database.
- The migration width/upgrading criterion is proposed in this spec for review; do not cite it as already approved behavior.

## Acceptance Criteria

1. WHEN the isolated PostgreSQL 16 upgrade from `008_speaker_review_aggregate` to `009_speaker_review_idempotency_receipts` is run, THE migration SHALL complete and persist the full 39-character revision ID without truncation. (Proposed bugfix criterion; see source-boundary note above.)
2. WHEN the upgrade completes, THE database SHALL record the target revision and contain the receipts table; the failed-at-008 state observed in QA SHALL no longer occur.
3. WHEN either already-published 009 revision identity is encountered, THE fix SHALL CONTINUE TO preserve that exact identity and its migration effect, consistent with the approved lineage bugfix contract.
