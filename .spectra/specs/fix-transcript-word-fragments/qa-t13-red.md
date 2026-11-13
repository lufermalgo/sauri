# T13 / #652 — API generation contracts (RED)

## Scope and authority

Approved bugfix `9fed8e2`, design `bc18206` §1/§6, tasks `122b6a7`. Base `origin/main` = `8548fcc`. This delivery adds only synthetic tests; it is not a functional release and must not be merged alone. Fer integrates the completed GREEN candidate after Ansel's verification. T14 requires integrated T12; Nahuel is implementing T11/T12 independently. The general task DAG explicitly permits preparing T13 RED without input dependencies; this does not waive the T12 integration requirement for GREEN.

The new module is `backend/tests/speaker_review/test_generation_api.py`, within the approved `tests/speaker_review/` seam, so the exact T13/T19 suite discovers all new cases. It reuses the existing isolated SQLite API fixtures from `tests/meetings/conftest.py`. It executes the real ASGI routes and database-backed service; handlers, selection and persistence are not mocked. SQLite here verifies API behavior, not concurrent reservation guarantees; no concurrency claim is made.

## Coverage

- Latest completed revision remains active across pending, in-progress, failed and not-reconstructible attempts; a newer completed result becomes active.
- No completed generation: null active revision, empty speakers/assignments, explicit attempt state. Positive overlap and legacy null overlap are distinct.
- Active and historical review selection; missing historical revision is not found; a historical read must not change the active revision.
- Complete labels map includes named/corrected choices, confirmed/uncertain current labels and pending speakers; pending items include the full wire metadata.
- PUT named/corrected preserves chosen labels after pending items disappear; replay returns the original aggregate; GET reload preserves labels.
- Direct `record_disposition` receipt preserves the aggregate map and pending items, not merely an item result.
- Owner and authentication boundaries on active/historical reads and PUT; raw engine labels and source text must not leak through diarization.

## Observed validation

Python runner: root `backend/.venv/bin/python` (Python 3.13). Commands below run from this worktree's `backend/`, never from the modified root checkout.

1. Baseline exact command before adding tests: `python -m pytest tests/meetings/test_diarization_endpoint.py tests/speaker_review -q` — collection fails because the pre-existing `test_processing_readiness.py` imports absent `app.transcription.processing_pipeline`. This is not RED evidence and is not fixed/hidden by this delivery.
2. Baseline runnable subset: same command with `--ignore=tests/speaker_review/test_processing_readiness.py` — **28 passed, 1 failed**. Existing failure: `test_review_put_schema_excludes_completion`, missing PUT OpenAPI path.
3. Candidate runnable subset: same explicitly limited command — **31 passed, 16 failed**. Of those, **15 failures are new behavioral expectations**, and one is the unchanged baseline PUT schema failure. Three new GET owner/auth boundary cases pass. Multi-generation GET raises `MultipleResultsFound` in the existing route; single-generation responses lack revision/overlap/attempt fields; historical query is ignored; labels map/aggregate receipt are missing; PUT returns 405 including auth-boundary test. No new setup/fixture/import error occurs.
4. `ruff check tests/speaker_review/test_generation_api.py` — PASS.
5. `ruff format --check tests/speaker_review/test_generation_api.py` — PASS.

Raw logs are attached to the APX task. No production code, models, migration, Compose, shared types or frontend changes. No Docker container/network/volume or native engine was created; existing API fixtures remove their temporary database files. No owner media or persistent data was accessed.

## Exit conditions

Preserve these expectations before T14. Do not close #652 or present this draft as ready for merge; GREEN must satisfy T12 dependency, all new expectations, existing API/review regressions, relevant quality checks and exact-candidate review. The pre-existing collection defect remains explicitly reported and must be resolved or separately accounted for during integrated validation; a limited test run is not the complete T19 suite.
