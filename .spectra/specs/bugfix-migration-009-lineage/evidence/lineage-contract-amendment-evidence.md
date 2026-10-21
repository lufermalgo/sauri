# Evidence — the 009-lineage spec contract is stale after `010_speaker_excerpt_reference` landed

Status: **evidence only**. No approved artifact (`bugfix.md`, `design.md`, `tasks.md`) of
`bugfix-migration-009-lineage` is modified by this file. It exists to support an amendment of
that spec, and to unblock whoever picks up T-6 / Issue #407.

- Collected: 2026-10-21
- `origin/main` at collection time: `58abc1e51c87c6ab435a88f792546be187c0f8d1`
- Branch / worktree: `docs/issue-407-migration-009-lineage-contract-amendment` /
  `.worktrees/docs-issue-407-migration-009-lineage-contract-amendment`
- Interpreter used (the one the spec's own validation commands name):
  `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python`
  (Python 3.14.7, Alembic 1.20.0, SQLAlchemy 2.1.5, pytest 9.1.1)
- Database used: a throwaway `postgres:16` container named `sauri-qa-407-postgres` on host port
  55001, created and **removed** by this investigation (`docker ps -a --filter name=sauri-qa-`
  is empty afterwards). No live, shared, or owner's database was touched. All data synthetic.
- No production code, migration file, or approved artifact was edited.

---

## 1. The defect the spec was written against no longer exists in the assumed shape

The approved `bugfix.md` / `design.md` / `tasks.md` of `bugfix-migration-009-lineage` describe a
two-head Alembic graph and prescribe a fix: add a **no-op** merge revision whose `down_revision`
is exactly `009_recording_media_sources` + `009_speaker_review_idempotency_receipts`.

But `backend/alembic/versions/010_speaker_excerpt_reference.py` (commit `6cf4307`, 2026-10-17,
`feat(speaker-review): derive and validate excerpts`) already declares exactly that merge
revision:

```python
# backend/alembic/versions/010_speaker_excerpt_reference.py:13-17
revision: str = "010_speaker_excerpt_reference"
down_revision: tuple[str, str] = (
    "009_recording_media_sources",
    "009_speaker_review_idempotency_receipts",
)
```

It is a mergepoint with real DDL (it adds `speaker_review_items.excerpt_ref`) rather than a no-op,
but it reconciles the same two published 009 branches with the same two parents, and it is
already on `main`.

Consequences that the spec amendment must settle:

1. The graph defect (two heads) is already fixed. `alembic heads` reports exactly one head.
2. The prescribed T-6 deliverable (a *new* merge revision over the same two parents) would
   create a **second** mergepoint over the same parents — a topology the spec never approved and
   that the T-3 test contract does not describe.
3. T-3's RED tests (merged in PR #414) still encode the pre-`010` topology and now fail on
   `main`. See §2.

## 2. Reproduction — the T-3 RED contract from PR #414 fails on `main`

```
$ /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py
...
FAILED tests/test_migration.py::test_head_ancestry_contains_both_009_branches_and_008
FAILED tests/test_migration.py::test_each_009_state_has_a_structural_forward_path_through_sibling_to_head
2 failed, 14 passed, 2 skipped, 5 warnings in 0.42s
```

Failure detail:

```
E  AssertionError: head ancestry must include both 009 branches and 008; found
   {'009_speaker_review_idempotency_receipts', '009_recording_media_sources', '010_speaker_excerpt_reference'}
E  assert {'008_speaker_review_aggregate'} <= {'009_recording_media_sources', ..., '010_speaker_excerpt_reference'}

E  AssertionError: upgrade from 009_recording_media_sources must include missing sibling
   009_speaker_review_idempotency_receipts; planned {'010_speaker_excerpt_reference'}
```

**Root cause of the two failures is a test-side misuse of Alembic's API, not a graph defect.**
`ScriptDirectory.iterate_revisions(upper, lower)` in Alembic 1.20.0 *excludes* the lower
boundary node. Measured on `main`:

| query | result |
|---|---|
| `iterate_revisions(head, "008_speaker_review_aggregate")` | `['009_recording_media_sources', '009_speaker_review_idempotency_receipts', '010_speaker_excerpt_reference']` |
| `iterate_revisions(head, "009_recording_media_sources")` | `['010_speaker_excerpt_reference']` |
| `iterate_revisions(head, "base")` | `['001_initial_schema', ..., '008_speaker_review_aggregate', '009_recording_media_sources', '009_speaker_review_idempotency_receipts', '010_speaker_excerpt_reference']` |
| `script.get_heads()` | `['010_speaker_excerpt_reference']` |
| `script.get_revision(head).down_revision` | `('009_recording_media_sources', '009_speaker_review_idempotency_receipts')` |

- Test 1 asks that `008_speaker_review_aggregate` be *inside* a set that by construction excludes
  the lower bound. It is present in the `base`-bounded ancestry, so the intent is satisfiable with
  a bounded query that is not self-contradictory.
- Test 2 computes the "planned" set with the same self-excluding API and therefore never sees the
  sibling, even though the real upgrade planner does apply it (§4).

The graph itself is correct and converged. **A correct contract for the shipped graph** would
assert: exactly one head; that head's parents are exactly the two published 009 IDs; the head's
full ancestry contains both 009 IDs and `008_speaker_review_aggregate`; and, for each published
009 state, that the *upgrade plan* reaches the head while applying the missing sibling exactly
once.

## 3. Reproduction — the spec's own offline-SQL acceptance command cannot pass

`tasks.md` T-6 lists as acceptance evidence:

```
/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m alembic upgrade 008_speaker_review_aggregate:head --sql
```

On `main` this fails, for a reason unrelated to any merge revision:

```
  File "backend/alembic/versions/009_recording_media_sources.py", line 48, in upgrade
    ).mappings()
AttributeError: 'NoneType' object has no attribute 'mappings'
```

`009_recording_media_sources.upgrade()` runs a data backfill through `op.get_bind()`
(`backend/alembic/versions/009_recording_media_sources.py:45-48`). In Alembic's **offline**
(`--sql`) mode `op.get_bind()` returns `None`, so the published 009 body cannot emit offline SQL.

`design.md` forbids altering the published 009 bodies, so this cannot be repaired by editing
`009_recording_media_sources.py`. Any acceptance criterion that depends on `--sql` output must
be replaced (different executable formulation, a disposable live database, or moving the backfill
into its own revision — a design decision, not an implementation detail).

## 4. Runtime reproduction — the upgrade to head is currently blocked by a *different* known bug

The graph being correct does **not** mean the upgrade runs. Measured on a throwaway PostgreSQL 16
container:

```
$ DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55001/sauri \
    python -m alembic upgrade 008_speaker_review_aggregate
... Running upgrade 007_rename_schema_to_english -> 008_speaker_review_aggregate
$ psql -tAc "select version_num from alembic_version;"
008_speaker_review_aggregate

$ DATABASE_URL=... python -m alembic upgrade head
sqlalchemy.exc.DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error) value too long for type character varying(32)
[SQL: UPDATE alembic_version SET version_num='009_speaker_review_idempotency_receipts' WHERE alembic_version.version_num = '008_speaker_review_aggregate']

$ psql -tAc "select version_num from alembic_version;"
008_speaker_review_aggregate
$ psql -tAc "select table_name from information_schema.tables where table_name like 'speaker_review%';"
speaker_review_items
speaker_reviews
```

The database is left at `008_speaker_review_aggregate` and the receipts table is absent. The
receipts revision id is 39 characters and `alembic_version.version_num` is `VARCHAR(32)`.
This is the already-specified bug of the `alembic-version-id-width` spec
(`.spectra/specs/alembic-version-id-width/bugfix.md`: *"upgrading to
`009_speaker_review_idempotency_receipts` fails when Alembic records the 39-character revision
identifier in `alembic_version.version_num`, which is `VARCHAR(32)`"*), whose GREEN task
T-6 is *"Widen Alembic's version column in the receipts migration"*.

Diagnostic only (throwaway database, manual widening, not a proposed fix):

```
$ psql -c "alter table alembic_version alter column version_num type varchar(64);"
$ python -m alembic upgrade head
... Running upgrade 008_speaker_review_aggregate -> 009_speaker_review_idempotency_receipts
... Running upgrade 008_speaker_review_aggregate -> 009_recording_media_sources
... Running upgrade 009_recording_media_sources, 009_speaker_review_idempotency_receipts -> 010_speaker_excerpt_reference
$ psql -tAc "select version_num from alembic_version;"
010_speaker_excerpt_reference
```

With the column widened, the published graph converges to the single head `010` in one run, and
both branch effects (`recording_media_sources`, `speaker_review_idempotency_receipts`) are applied
exactly once. So the end-to-end upgrade path is sound **once the version-column width is fixed**.

## 5. What the amendment must decide

For Brisa (architecture) / Zoya (requirements) / Mira (audit) of the `bugfix-migration-009-lineage`
spec:

1. **Is T-6 (Issue #407) still a valid deliverable?** Evidence says the merge revision it
   prescribes already exists on `main` as `010_speaker_excerpt_reference`. Options: retire T-6 as
   "already satisfied by the merged `010`", or re-scope it to something the spec actually still
   needs. Adding a second mergepoint over the same parents should not be done.
2. **What should the T-3 RED contract assert?** The current assertions encode a pre-`010`
   topology and misuse `iterate_revisions` boundaries. They need to be rewritten to the shipped
   graph (§2), and the rewrite is a change to an approved artifact, so it needs its own
   authorization and a new Mira verdict.
3. **How is the `--sql` acceptance criterion replaced?** The published 009 backfill makes offline
   SQL generation impossible (§3).
4. **What is the dependency on `alembic-version-id-width`?** Until that spec's GREEN task widens
   `alembic_version.version_num`, no end-to-end upgrade to `010` can be demonstrated (§4). T-6 /
   #407 should declare that dependency explicitly instead of failing on an unrelated error.

## 6. Scope boundary

This evidence does not touch, and must not be used to justify touching:

- `backend/app/**` production code;
- `backend/alembic/versions/009_*.py` and `010_*.py` (published identities, immutable);
- the `recording-speaker-review` spec (its T-6 RED acceptance evidence already records that the
  full backend suite is blocked at collection by the not-yet-implemented
  `app.transcription.processing_pipeline`, owned by Issue #248 / T-15).
