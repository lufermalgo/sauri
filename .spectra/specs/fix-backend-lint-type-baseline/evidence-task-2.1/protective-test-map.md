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

## Current-base checker recheck and reconciliation

Exact current test-only candidate: `66d5dffea648be4357d251b40812ccc40c9a1f7b`; `origin/main` parent/base remains `576a6a992db4452a653a7112f394e73da5177792`. `git merge-base --is-ancestor a6c74bb92b286e7819602a07e47785ee7ba1f78c 576a6a992db4452a653a7112f394e73da5177792` exited 0, so the old inventory base is an ancestor, not this base. Tool versions from the assigned candidate environment: Python 3.14.7, Ruff 0.17.1, mypy 2.4.0; `import app` resolved to this worktree's `backend/app/__init__.py`.

- From current `backend/`, `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check .` — **exit 1; 190 errors**, 133 fixable and 6 unsafe; this is one more than T1.2's 189.
- From current `backend/`, `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/mypy .` — **exit 1; 303 errors in 31 files** (126 source files checked), 11 more than T1.2's 292.
- Recheck focused on post-T1.2 production changes: `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check app/infra/models.py app/ingestion/router.py app/ingestion/schemas.py app/ingestion/service.py app/meetings/disposition_idempotency.py app/meetings/speaker_review_service.py alembic/versions/009_recording_media_sources.py alembic/versions/009_speaker_review_idempotency_receipts.py` — **exit 1, 7 findings**: `009_recording_media_sources.py` I001; `app/ingestion/router.py` B008 ×3, B904, SIM117; `app/ingestion/schemas.py` UP037. No Ruff findings in the other listed changed files.
- Same eight-file list with `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/mypy` — **exit 1, one error**: `app/meetings/speaker_review_service.py:99`, `[union-attr]`, possible `None` has no attribute `strip`.
- `git diff --name-status a6c74bb92b286e7819602a07e47785ee7ba1f78c..576a6a992db4452a653a7112f394e73da5177792 -- backend/app backend/asr-engine backend/diar-engine backend/alembic` returned: added migrations `009_recording_media_sources.py` and `009_speaker_review_idempotency_receipts.py`; modified `app/infra/models.py`, `app/ingestion/router.py`, `app/ingestion/schemas.py`, `app/ingestion/service.py`; added `app/meetings/disposition_idempotency.py` and `app/meetings/speaker_review_service.py`. The new production paths were not represented by T1.2's production diagnostic inventory; do not mix these post-baseline findings into T1.2 scope without Ansel's ruling. The new migration sequence also intersects the unresolved duplicate-table failure above.

## Exact test collection / node evidence

Current-base collection command: `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest --collect-only -q tests/auth tests/diarization tests/diar_engine tests/infra tests/ingestion tests/meetings tests/transcription tests/speaker_review tests/test_queue.py` — **214 tests collected**. Exact node IDs were emitted by pytest; relevant examples confirmed in that listing include `tests/auth/test_access_control_property.py::test_property_10_access_granted_iff_authorized`, `tests/auth/test_access_control_property.py::test_property_10_every_denial_generates_exactly_one_record`, `tests/diarization/test_assignment_property.py::test_property_9_exactly_one_assignment_per_turn`, `tests/diarization/test_cloud_provider_property.py::test_example_http_error_raises_external_service_error`, `tests/diarization/test_state_property.py::test_property_16_valid_transitions_produce_correct_state`, `tests/diarization/test_worker.py::test_property_20_engine_failure_propagates_without_completed`, `tests/diar_engine/test_contract.py::TestContratoDiarEngine::test_health_endpoint`, and the speaker-review schema node named above. However the executed 213-pass/1-fail invocation was directory-wide, not a separately targeted exact-node run, so it does not meet T2.1's pre-correction per-node evidence criterion. `tests/test_migration.py` exact failing node IDs and details are recorded above. Do not present collection as a test pass.

## Current disposition and remaining work

This ledger remains partial. The full checker REDs are confirmed on exact current test-only candidate and versions. T1.2 inventory base is a proven ancestor, but production code changed after it; current findings on those changed paths must be separated from original T1.2 scope. Per-production-path exact relevant node runs and semantic-equivalence notes remain incomplete, and the migration/speaker-review failures are unresolved. The first next move is Ansel to decide scope and the affected migration baseline; after that, continue exact-node verification and per-path equivalence evidence on the authorized baseline. No PASS/FAIL conclusion is made.

## Follow-up after Ansel's 14:41 scope direction

- Rebased/check-confirmed against `origin/main` from the assigned worktree: `git fetch origin main && git rebase origin/main` — exit 0, no changes; HEAD remains `1ed326d1387950848c445742a9059a6f987d9c77`, parent lineage includes `576a6a992db4452a653a7112f394e73da5177792`.
- Re-read the approved Task 1.2 inventory. It contains 25 production paths (Ruff diagnostic-bearing) and is based on `a6c74bb...`; the 8 production paths listed above are newer changes and are not silently folded into that scope. Their current static findings remain separately recorded above for Ansel's disposition.
- Re-ran exact collection on the candidate using the focused command shown in “Exact test collection / node evidence”: **214 nodes collected**. The relevant node IDs are the ones pytest emitted; representative exact nodes are recorded there. Current executed focused command previously recorded in this ledger passed **213** and failed only `tests/speaker_review/test_review_state.py::test_review_put_schema_excludes_completion`. The migration-focused command separately passed **19** ingestion nodes and failed all 3 listed source-inventory migration nodes. Thus the applicable test paths are mapped at file/suite level, but exact per-node command/result evidence is still incomplete for every path; collection is not a test pass.
- Ruff and mypy completed on the candidate and environment stated above: full-target `ruff check .` exit 1 with 190 findings; full-target `mypy .` exit 1 with 303 errors/31 files. These are confirmed current-candidate checker REDs, not claimed as clean checks.

## Follow-up after Ansel's 14:43 scope ruling and exact path runs

Ansel ruled that T-2.1 remains within the 25 production paths in the approved T1.2 inventory; newer paths/findings are excluded from #228. For paths overlapping later changes, use current pre-edit base `576a6a992db4452a653a7112f394e73da5177792`. The eight paths added/changed after T1.2 remain out-of-scope; `app/ingestion/router.py` and `app/infra/models.py` were included below because they already belong to T1.2's 25-path inventory and current tests/checkers were rerun on them.

- Test-only candidate commit `5d3079bc0d85e21fbd9eb7cae9952463899010b1`, pushed to the assigned branch. It adds synthetic diar-engine cleanup/status coverage in `backend/tests/diar_engine/test_contract.py`; earlier ASR cleanup tests are in `9b7988fb49dbac249e59b49b55a17c4a69e0cf91`. No production code changed.
- `cd backend && /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check <the exact 25 production paths listed in Task 1.2 above>` — **exit 1, 91 Ruff findings** on the current base. This is the current production-path RED. The full `ruff check .` remains exit 1/190 findings.
- Configured `mypy .` remains exit 1/303 errors across 31 files; T1.2's mypy diagnostic inventory is test-only, not a production-path mypy RED. I also tried one explicit multi-file production mypy invocation; it stopped with `Duplicate module named main` for the two isolated engine directories (exit 2). Corrected by invoking mypy one file at a time: every in-scope production file reported no issues except the excluded engine targets; direct `mypy asr-engine/main.py` reports missing `faster_whisper` stub plus no-untyped-def, and `mypy diar-engine/main.py` reports missing `torch`/`pyannote.audio` stubs plus no-untyped-def. These direct engine errors are outside the configured `mypy .` target and are not added to T1.2 scope.

### Focused test outcomes by T1.2 production path

Each command below was executed as `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q <test-file>` from `backend/`. A separate `--collect-only -q` run enumerated exact node IDs for these test modules (81 nodes); these are actual test executions, not collection-only claims.

| T1.2 production path(s) | Classification from diagnostic type | Focused modules and result |
|---|---|---|
| `alembic/env.py`; migrations `001`–`007` | Static import/type/line-format diagnostics | `tests/test_migration.py`: 6 pre-009 nodes passed, 3 later source-inventory nodes failed (see below); explicit 6-node command passed 6/6. `tests/diarization/test_migration.py`: 4 passed. |
| `app/auth/audit.py`, `token.py` | Static `UP017` | `tests/auth/test_access_control_property.py`, `test_auth_disabled_scope.py`, `test_login.py`, `test_user_model.py`: 11 passed total. Exact audit-relevant nodes include `test_property_10_every_denial_generates_exactly_one_record` and `test_property_10_access_granted_iff_authorized`. |
| `app/auth/authorization.py`, `dependencies.py` | Behavior-bearing `B008` dependency defaults and `B904` exception chaining; `UP035` import is static | Same auth modules: 11 passed total; access-control property nodes above exercise authorization and audit paths. |
| `app/diarization/assignment.py`, `state.py` | Static import-order only | `tests/diarization/test_assignment_property.py`: 4 passed; `test_state_property.py`: 3 passed. Exact nodes include `test_property_9_exactly_one_assignment_per_turn` and `test_property_16_valid_transitions_produce_correct_state`. |
| `app/diarization/cloud_provider.py` | Behavior-bearing `B904` exception conversion | `tests/diarization/test_cloud_provider_property.py`: 7 passed, including `test_example_http_error_raises_external_service_error`. |
| `app/diarization/worker.py` | Mixed: imports/`UP017` static; `SIM117` context-manager/resource semantics behavior-bearing | `tests/diarization/test_worker.py`: 10 passed, including `test_property_20_engine_failure_propagates_without_completed`. |
| `app/infra/models.py` | Static imports | `tests/infra/test_adaptadores_conformidad_property.py` and `test_referential_integrity_property.py`: 6 passed. |
| `app/ingestion/router.py` | Behavior-bearing `B008`, `B904`, `SIM117` | `tests/ingestion/test_playback_source_ingestion.py`: 13 passed (4 Starlette deprecation warnings). Collection includes explicit invalid metadata and no-write-before-rejection nodes. |
| `app/meetings/router.py` | Behavior-bearing `A002` parameter rename may change callable/route API; `B008`, `B904`, `SIM117` can affect dependency/error/resource behavior | `tests/meetings/test_get_meeting_property.py`, `test_join_triggers.py`, `test_register_meeting_property.py`, `test_state_machine_property.py`, `test_title_history.py`, `test_transcript_turn_id.py`, `test_diarization_endpoint.py`: 19 passed. Example nodes include `test_request_join_manual_transitions_and_enqueues`, `test_property_5_failure_cause_present_iff_failed`, and `test_diarization_requires_authentication`. |
| `app/meetings/schemas.py`, `service.py`, `state_machine.py` | `UP007`/imports static; `service.py` `A002` parameter rename is behavior-sensitive until API callers are checked | Same 19 meeting tests passed, including registration, state transition, and transcript-turn contract cases. |
| `app/transcription/cloud_provider.py` | Behavior-bearing `B904` exception conversion | `tests/transcription/test_cloud_provider.py`: 5 passed. Existing timeout test verifies the service error path; exact node `test_example_cloud_timeout_raises_service_error`. |
| `asr-engine/main.py` | Behavior-bearing `B904`, `SIM105` cleanup suppression, `SIM115` file handling | `tests/transcription/test_asr_engine_service.py`: 2 passed. Exact nodes: `test_failed_s3_download_removes_partial_file_and_chains_cause` and `test_transcription_failure_returns_500_and_removes_audio_file`. |
| `diar-engine/main.py` | Behavior-bearing `B904`, `SIM105`, `SIM115` | New explicit run of the three test-only nodes passed 3/3; entire `tests/diar_engine/test_contract.py` then passed 6/6. Added nodes: `test_failed_s3_download_removes_partial_file_and_chains_cause`, `test_diarization_failure_removes_downloaded_temp_file`, `test_download_http_error_preserves_status_and_detail`. |

The focused module commands total 99 passes for selected in-scope test files plus the three source-inventory migration failures (the three newly added diar-engine tests are counted once via the full test-file run; the explicit three-node rerun is duplicate verification). The exact migration isolation command was `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q tests/test_migration.py::test_revision_007_chains_after_006 tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data tests/test_migration.py::test_downgrade_reverses_every_rename tests/test_migration.py::test_orm_schema_uses_english_table_names tests/test_migration.py::test_orm_schema_meetings_has_english_columns tests/test_migration.py::test_orm_schema_users_has_english_columns` — **6 passed**. Full `tests/test_migration.py` is **6 passed, 3 failed**: `test_source_inventory_migration_backfills_only_explicit_legacy_sources`, `test_source_inventory_downgrade_preserves_refs_and_reupgrade_backfills`, `test_source_inventory_rejects_duplicate_recording_kind_and_reference`; each fails as revision 009 attempts to recreate existing `speaker_review_idempotency_receipts`. This satisfies Ansel's narrower 001–007 exercise request; the three 009 interaction failures remain unresolved and untouched.

### Limitations / decisions still required

- The broad focused run previously recorded 213 passed/1 failed at `tests/speaker_review/test_review_state.py::test_review_put_schema_excludes_completion`; this is in a post-T1.2 area and is excluded from the approved inventory. It remains a current-base limitation, not a pass.
- The new test file still has its pre-existing T1.2 Ruff `I001` finding and mypy inventory errors; these are not introduced by the test addition. The targeted run reports the test file's existing Ruff `I001`; mypy reports 11 existing errors consistent with its T1.2 inventory (`attr-defined`, `no-untyped-def`, `unused-ignore`).
- A test-draft assertion that the endpoint's HTTPException must retain `__cause__` failed on the pre-edit base (`__cause__ is None`). I removed that assertion rather than silently treating a B904 exception-chain change as approved unchanged behavior. The replacement test protects the existing 500 status/detail. This is evidence that endpoint cause chaining is observably different; Ansel must direct whether it is accepted as an intended correction before Imre changes that path.
- No production edits have occurred; therefore final semantic equivalence of static corrections cannot yet be proven. Current static-only classification is limited to import sorting, line length, annotation/import modernization; any actual diff must still be checked against executable statements before its writer's handoff. Behavior-sensitive paths are identified above and must receive their exact pre-edit RED/test packet.

T-2.1 remains **incomplete / BLOCKED**, not PASS. Remaining next move: Ansel to decide whether the endpoint B904 cause-chain change is acceptable and confirm next work sequencing; then QA can finish any remaining path-specific test-node/semantic-equivalence record. Migration failures must remain documented, not repaired in this card.

## Bounded follow-up batch: next five in-scope production paths

Ansel's 14:46 instruction was to process only the next five unresolved paths. I selected the next five independent production paths after the isolated migration paths: `app/auth/audit.py`, `app/auth/authorization.py`, `app/auth/dependencies.py`, `app/auth/token.py`, and `app/diarization/assignment.py`. Worktree was fetched/rebased first; `origin/main` remained `576a6a992db4452a653a7112f394e73da5177792`, and no production path was edited. Test-only commit `2818a91fb101dbbe0c3f2f1df171323be879e1b3` adds a synthetic malformed-JWT response-contract node; pushed separately.

### Exact current-path Ruff REDs and per-path evidence

Ran `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check <path>` separately from `backend/` for each exact production path; all five commands exited 1:

| Production path | Exact RED | Classification / reason | Focused node(s), exact command result |
|---|---|---|---|
| `app/auth/audit.py` | UP017 ×1 at `datetime.now(timezone.utc)` | Purely static: use `datetime.UTC`, an alias of the same UTC singleton; same call/result, no control flow or persisted fields changed. | `tests/auth/test_access_control_property.py::test_property_10_every_denial_generates_exactly_one_record` passed; exercises emitted denied AccessLog and adjacent audit path. |
| `app/auth/authorization.py` | UP035 ×1 (`Callable`) and B008 ×2 (`Depends` defaults) | Behavior-bearing due to FastAPI dependency declarations; UP035 import modernization is static. | `tests/auth/test_access_control_property.py::test_property_10_access_granted_iff_authorized` and `::test_property_10_every_denial_generates_exactly_one_record` passed. Covers allow/deny and exactly-one denial audit. |
| `app/auth/dependencies.py` | B008 ×1 (`Depends(_bearer_scheme)`) and B904 ×1 (JWTError→401) | Behavior-bearing: B008 can alter FastAPI dependency interpretation; B904 can change observable exception context. | `tests/auth/test_auth_disabled_scope.py` bypass nodes and new `::test_invalid_token_preserves_unauthorized_error_contract` passed; exact node protects malformed-token 401/detail without assuming cause chaining. |
| `app/auth/token.py` | UP017 ×1 at `datetime.now(timezone.utc)` | Purely static: `datetime.UTC` is the same UTC singleton; generated claims/signature path is unchanged. | `tests/auth/test_login.py::test_login_valid_credentials_issues_jwt` passed; verifies issued token claims and decoding. |
| `app/diarization/assignment.py` | I001 ×1, import order only | Purely static if the correction only reorders the existing two imports. Inspected `labeling.py` and `diarization_engine.py`: module-level code is imports, class/type definitions and dataclass definitions, with no I/O or registration side effects. The import names/set are unchanged; property tests exercise output semantics. | All four nodes passed: `test_property_9_exactly_one_assignment_per_turn`, `test_property_9_assignment_to_speaker_with_maximum_overlap`, `test_property_9_tie_break_by_lower_sequence`, `test_property_10_preservation_of_speech_turns`. |

Exact selected-node command (all invoked from `backend/`):

```bash
/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q \
 tests/auth/test_access_control_property.py::test_property_10_access_granted_iff_authorized \
 tests/auth/test_access_control_property.py::test_property_10_every_denial_generates_exactly_one_record \
 tests/auth/test_auth_disabled_scope.py::test_bypass_active_in_test_environment \
 tests/auth/test_auth_disabled_scope.py::test_bypass_inactive_outside_test_environment \
 tests/auth/test_auth_disabled_scope.py::test_bypass_inactive_without_app_env \
 tests/auth/test_auth_disabled_scope.py::test_invalid_token_preserves_unauthorized_error_contract \
 tests/auth/test_login.py::test_login_valid_credentials_issues_jwt \
 tests/diarization/test_assignment_property.py::test_property_9_exactly_one_assignment_per_turn \
 tests/diarization/test_assignment_property.py::test_property_9_assignment_to_speaker_with_maximum_overlap \
 tests/diarization/test_assignment_property.py::test_property_9_tie_break_by_lower_sequence \
 tests/diarization/test_assignment_property.py::test_property_10_preservation_of_speech_turns
```

Result: **11 passed in 1.92s**. The added malformed-JWT node was also rerun alone and passed **1/1**. `ruff check tests/auth/test_auth_disabled_scope.py` passed. Targeted `mypy tests/auth/test_auth_disabled_scope.py` exits 1 with the same three existing `no-untyped-def` findings in the three prior functions; the new test has an explicit return type and adds no mypy error. No production mypy findings are in the configured T1.2 inventory.

### Remaining decision in this batch

The behavior-preserving test asserts 401 and the existing detail but intentionally does not choose between `raise ... from err` and `raise ... from None`; both alter the observable exception context relative to the current `except JWTError` behavior. Ansel ruled on 2026-10-17 14:49 that the approved bugfix forbids runtime behavior changes and that the diar-engine B904 correction must remain blocked rather than add explicit chaining. The same constraint means the auth-dependencies B904 correction must remain blocked unless a semantics-preserving disposition is approved. The other four paths now have focused current-base evidence and recorded static/behavior classifications; any implementation diff still needs to stay within the described equivalent transformation, with post-edit checker GREEN and tests rerun.

Test-only commit is `2818a91fb101dbbe0c3f2f1df171323be879e1b3`; current branch HEAD before the next ledger update was `5239adfeaf3f375d367a852b3e2d761475730965`.

## Second bounded independent batch: five current-base paths

Following Ansel's ruling to leave behavior-changing exception-chain work blocked and continue independent T1.2 paths, I verified `app/diarization/state.py`, `app/diarization/worker.py`, `app/infra/models.py`, `app/meetings/schemas.py`, and `app/meetings/state_machine.py` on the unchanged production base `576a6a992db4452a653a7112f394e73da5177792`. No production edits or new tests were needed.

### Current-base checker evidence

From `backend/`, ran `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check <path>` individually:

| Production path | Current Ruff | Classification and evidence |
|---|---|---|
| `app/diarization/state.py` | exit 1, I001 ×1 | Pure import ordering: dataclass import only; no executable body change. |
| `app/diarization/worker.py` | exit 1, I001 ×1, UP017 ×1, SIM117 ×1 | Static-only if kept exact: import order only; `timezone.utc`→`UTC` uses the same UTC singleton; nested `async with session_factory() as session` / `async with session.begin()` to a multi-context `async with` preserves left-to-right enter and reverse exit ordering. Worker tests cover state, timestamps, persistence, and error propagation. |
| `app/infra/models.py` | exit 0, All checks passed | T1.2 recorded I001 on its older base, but current `576a6a9` path is clean; no correction is needed. Referential integrity tests exercise the current model contract. |
| `app/meetings/schemas.py` | exit 1, UP007 ×1 | Behavior-bearing type-alias modernization: changing `typing.Union[...]` to PEP 604 changes the runtime alias representation; existing register-input tests cover all three accepted forms and invalid links. |
| `app/meetings/state_machine.py` | exit 1, I001 ×1 | Pure import ordering only; transition implementation unchanged. |

`/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m mypy app/diarization/state.py app/diarization/worker.py app/infra/models.py app/meetings/schemas.py app/meetings/state_machine.py` — **Success: no issues found in 5 source files**. These five production paths have no mypy diagnostic in the T1.2 inventory.

Exact focused command from `backend/`:

```bash
/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q \
 tests/diarization/test_state_property.py \
 tests/diarization/test_worker.py \
 tests/infra/test_referential_integrity_property.py \
 tests/meetings/test_register_meeting_property.py \
 tests/meetings/test_state_machine_property.py
```

Result: **24 passed in 1.12s**. Exact node IDs collected and run:

- `tests/diarization/test_state_property.py`: `test_property_16_valid_transitions_produce_correct_state`; `test_property_16_terminal_states_are_immutable`; `test_property_16_unrecognized_events_reject_transition`.
- `tests/diarization/test_worker.py`: `test_property_19_invalid_message_does_not_persist`; `test_property_19_nonexistent_meeting_does_not_persist`; `test_property_19_without_transcript_does_not_persist`; `test_property_11_empty_result_completed_diarization`; `test_property_11_without_turns_zero_assignments`; `test_property_20_engine_failure_propagates_without_completed`; `test_property_18_preserves_meeting_process_state`; `test_property_17_utc_timestamp_on_final_state`; `test_example_nonexistent_meeting_acks_without_persisting`; `test_example_without_transcript_acks_without_persisting`.
- `tests/infra/test_referential_integrity_property.py`: `test_property_6_a_meeting_has_at_most_one_recording`; `test_property_6_a_meeting_has_at_most_one_transcript`; `test_example_recording_references_its_meeting`.
- `tests/meetings/test_register_meeting_property.py`: `test_property_1_registration_starts_queued`; `test_property_2_accepts_link_input`; `test_property_2_accepts_calendar_input`; `test_property_2_accepts_manual_input`; `test_property_2_rejects_invalid_links`.
- `tests/meetings/test_state_machine_property.py`: `test_property_3_only_valid_transitions_produce_a_new_state`; `test_property_3_terminal_states_are_immutable`; `test_property_4_transition_to_failed_has_a_valid_cause`.

T-2.1 remains **incomplete / BLOCKED**: this batch advances five paths only. Remaining in-scope paths still need equivalent evidence or a documented blocker; the behavior-changing B904 paths and 009 migration failures remain blocked/unmodified. No full PASS is claimed.

## Third bounded independent batch: five current-base paths

On unchanged production base `576a6a992db4452a653a7112f394e73da5177792`, I verified `app/diarization/cloud_provider.py`, `app/transcription/cloud_provider.py`, `app/ingestion/router.py`, `app/meetings/router.py`, and `app/meetings/service.py`. No production edits or new tests were made. Test coverage is run-only evidence; it does not authorize behavior changes.

### Exact per-path checker REDs

From `backend/`, individually ran `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check <path>`:

| Path | Result | Classification / blocker |
|---|---|---|
| `app/diarization/cloud_provider.py` | exit 1, B904 ×1 (timeout→ExternalServiceError) | Adding cause or suppressing context changes observable exception details; blocked under no-runtime-change ruling. |
| `app/transcription/cloud_provider.py` | exit 1, B904 ×1 (timeout→ExternalServiceError) | Same exception-context behavior risk; blocked pending an approved behavior disposition. |
| `app/ingestion/router.py` | exit 1, B008 ×3, B904 ×1, SIM117 ×1 | B008 can affect FastAPI injection; B904 changes exception context; SIM117 rewrites nested async transaction/session contexts and requires exact cleanup equivalence. Overall path remains behavior-sensitive. |
| `app/meetings/router.py` | exit 1, I001 ×1, A002 ×2, B008 ×8, B904 ×2, SIM117 ×4 (17 total) | I001 is import-only; A002 route parameter rename can change FastAPI body/API shape; B008/B904 and transaction context rewrites are behavior-sensitive. |
| `app/meetings/service.py` | exit 1, A002 ×1 (`input`) | Internal callable parameter rename may break keyword callers; audit all callers and update atomically before classifying as semantics-preserving. |

### Exact tests and result

Collected 54 exact node IDs, then ran this command from `backend/`:

```bash
/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m pytest -q \
 tests/diarization/test_cloud_provider_property.py \
 tests/transcription/test_cloud_provider.py \
 tests/ingestion/test_playback_source_ingestion.py \
 tests/meetings
```

Result: **54 passed, 4 Starlette deprecation warnings in 13.10s**. Nodes:

- `tests/diarization/test_cloud_provider_property.py`: `test_property_3_rejects_unencrypted_endpoint`; `test_property_5_speaker_segment_validity`; `test_example_missing_api_key_raises_valueerror`; `test_example_empty_api_key_raises_valueerror`; `test_example_120s_timeout_raises_external_service_error`; `test_example_http_error_raises_external_service_error`; `test_example_response_without_valid_segments_returns_empty`.
- `tests/transcription/test_cloud_provider.py`: `test_property_3_rejects_unencrypted_endpoint`; `test_property_5_only_valid_segments_in_result`; `test_example_missing_api_key_raises_valueerror`; `test_example_cloud_timeout_raises_service_error`; `test_example_integration_https_and_auth_header`.
- `tests/ingestion/test_playback_source_ingestion.py`: `test_ingestion_contract_preserves_explicit_capture_evidence[overrides0-muxed-None]`; `[overrides1-absent-None]`; `[overrides2-separate--125]`; `[overrides3-separate-250]`; `test_inconsistent_or_incomplete_capture_metadata_is_rejected[overrides0]`; `[overrides1]`; `[overrides2]`; `[overrides3]`; `[overrides4]`; `test_invalid_capture_metadata_returns_422_before_object_storage`; `test_upload_rejects_video_evidence_inconsistent_with_object_path_before_storage_or_persistence[muxed-True-None]`; `[absent-True-None]`; `[separate-False-40]`.
- `tests/meetings/test_diarization_endpoint.py`: `test_diarization_200_with_speakers_and_assignments`; `test_diarization_404_nonexistent_meeting`; `test_diarization_404_without_diarization`; `test_diarization_requires_authentication`.
- `tests/meetings/test_get_meeting_property.py`: `test_property_5_failure_cause_present_iff_failed`; `test_example_get_nonexistent_meeting_raises_error`.
- `tests/meetings/test_join_triggers.py`: `test_request_join_manual_transitions_and_enqueues`; `test_request_join_nonexistent_meeting_does_not_publish`; `test_schedule_join_by_calendar_fires_when_the_time_arrives`.
- `tests/meetings/test_note_management.py`: `test_rename_200_updates_title`; `test_rename_404_nonexistent_meeting`; `test_rename_404_meeting_of_another_user`; `test_rename_422_empty_title`; `test_rename_requires_authentication`; `test_delete_204_removes_the_meeting`; `test_delete_404_nonexistent_meeting`; `test_delete_404_meeting_of_another_user`; `test_delete_requires_authentication`; `test_delete_with_full_diarization_does_not_violate_fk`.
- `tests/meetings/test_register_meeting_property.py`: `test_property_1_registration_starts_queued`; `test_property_2_accepts_link_input`; `test_property_2_accepts_calendar_input`; `test_property_2_accepts_manual_input`; `test_property_2_rejects_invalid_links`.
- `tests/meetings/test_state_machine_property.py`: `test_property_3_only_valid_transitions_produce_a_new_state`; `test_property_3_terminal_states_are_immutable`; `test_property_4_transition_to_failed_has_a_valid_cause`.
- `tests/meetings/test_title_history.py`: `test_listing_includes_null_title`.
- `tests/meetings/test_transcript_turn_id.py`: `test_segments_include_the_turn_id`.

`/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/python -m mypy app/diarization/cloud_provider.py app/transcription/cloud_provider.py app/ingestion/router.py app/meetings/router.py app/meetings/service.py` — **Success: no issues found in 5 source files**.

T-2.1 remains **incomplete / BLOCKED**. Tests map current behavior, but B904 cause/context behavior remains unapproved, FastAPI dependency/body changes require explicit semantic-equivalence review, and paths not yet accounted for remain. The 009 migration failures remain untouched; do not report PASS.
