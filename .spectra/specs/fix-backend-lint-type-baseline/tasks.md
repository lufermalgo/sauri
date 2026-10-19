# Implementation Plan — Restore backend Ruff and mypy baseline

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | Establish an isolated candidate environment and capture the exact pre-correction baseline | 1.1–1.2 | None; 1.2 requires 1.1 |
| 2 | Map and preserve existing behavior before production edits | 2.1 | 1.2 |
| 3 | Correct findings in atomic, file-scoped units with RED evidence transferred before each edit | T-3.1.01–T-3.1.61 (one per current diagnostic-bearing in-scope path) | Historical Task 1.2 evidence plus current-base checker snapshot; matching 2.1 handoff before production-file edits |
| 4 | Validate and hand off the integrated candidate | 4.1–4.2 | Every T-3.1.01–T-3.1.61 instance; Task 4.1 also requires authorized resolution/integration of separate 009 defect card `task_6ccdc76cbc0f4fe9` because current default migration tests fail there |

The frozen Task 1.2 evidence remains historically based on `a6c74bb92b286e7819602a07e47785ee7ba1f78c`; it is not treated as a current-base inventory. Current-base checker output/version and per-path diagnostic inventory are preserved in `evidence-current-base/` for exact base `0d6f2713abcf08d960e98451b04bbdd31b4c8843`. It records 190 Ruff findings across 47 paths and 303 mypy errors across 31 files. Relative to Task 1.2: Ruff added `alembic/versions/009_recording_media_sources.py` and `app/ingestion/schemas.py`, and removed `app/infra/models.py`; mypy added `app/meetings/speaker_review_service.py` and `tests/ingestion/test_playback_source_ingestion.py`, and removed `tests/speaker_review/test_disposition_idempotency.py`. The two new application paths are in the approved bugfix scope, but production edits remain gated by their exact Task 2.1 handoffs. The 009 recording-media migration's I001 is recorded as excluded: the separate migration-lineage defect is tracked by `task_6ccdc76cbc0f4fe9`; do not fold that migration or its behavior repair into this plan. Thus the current materialized correction set is 61 paths after removing that separate 009 file. One file's Ruff and mypy findings are combined into one atomic correction task; test-only paths remain separate. Findings removed from current base receive no correction task.

## Phase 1: Isolated Candidate Environment and Baseline

### Task 1.1: Provision a candidate-only backend environment

**Files:** Environment only; no tracked repository changes.
**Action:** In the assigned clean implementation worktree based on `a753dee72703f3aeaf97c3b163de6b4954ab80e9` (or a later base Ansel explicitly verifies against it), create a fresh Python virtual environment at a unique absolute path outside the worktree's symlinked `backend/.venv`, the shared root `backend/.venv`, and every other existing environment. From the candidate `backend/`, run `python -m venv <candidate-venv-absolute-path>` and then `<candidate-venv-absolute-path>/bin/python -m pip install -e ".[dev]"`. Do not install or upgrade packages in the historical/root shared venv. Record the actual provisioning commands and resolved Python, Ruff, and mypy versions. Before declaring setup complete, verify Ruff resolves to 0.17.x and mypy to 2.4.x, as specified by issue #228; if either resolves outside its specified series, stop and report the exact versions and provisioning evidence to Ansel as blocked. Do not modify project dependency/checker configuration or silently substitute the shared venv to obtain those versions. If the fresh environment cannot be provisioned or lacks a required tool, record the exact command/output as blocked and report to Ansel. The approved `bugfix.md` and `design.md` specify fresh-environment candidate validation, and this task follows that approved requirement.

Task 1.1 also excludes the paused Imre worktree/branch and its approximately 49 already-modified paths from this candidate base: do not touch, merge, cherry-pick, rebase onto, or silently reuse that work, its diffs, or its commits. Its disposition and any authorized source transfer are Ansel's to specify before Phase 3; nothing in this plan authorizes reusing it.

**Completion Criteria:** The fresh environment can import `app` from the assigned worktree and provides pytest, Ruff, and mypy; its unique absolute path, worktree/base identity, import resolution path, provisioning commands/output, and actual tool versions are recorded. Setup is complete only when Ruff resolves to 0.17.x and mypy to 2.4.x. If either is outside its specified series, record that evidence and mark setup blocked for Ansel; do not alter project dependency/checker configuration or use the shared/historical venv to force compliance. The shared/historical venv was not changed, and the candidate base contains none of the paused Imre worktree's approximately 49 modified paths.

**Dependencies:** None

**Tracking:** Issue #262 · Card task_be16b64676d747d2

### Task 1.2: Capture all pre-correction checker and default-test evidence

**Files:** Complete configured backend target as reported by the checks; no source edits.
**Action:** On the unmodified implementation base and in Task 1.1's environment, run from `backend/`: `ruff check .`, `mypy .`, and `pytest -q`. Preserve exact command, tool version, exit status, and complete output for each. Record the Ruff and mypy diagnostic inventory grouped by exact source path and diagnostic/rule; these non-zero checker diagnostics are the RED evidence for later static corrections. Record the default pytest result, collected/pass/fail/skip summary, and the checked-in pytest testpaths/markers relevant to that default run. Distinguish toolchain/environment failure from source findings. Do not suppress, filter, or edit findings.

**Completion Criteria:** The inventory identifies every configured-target diagnostic by exact file and rule/error, with corresponding reproducible command/output and expected checker non-zero result; the default pytest/marker baseline and all command exits are recorded. A provisioning/tool-run failure is recorded as blocked, never counted as a clean baseline.

**Dependencies:** Task 1.1

**Tracking:** Issue #263 · Card task_c4abf99598f64377 · PR #314

## Phase 2: Behavior-Preservation Evidence

### Task 2.1: Map and verify protective tests for each affected production path

**Files:** Existing backend test files for affected production paths; add a focused synthetic-data test only where a *behavior-bearing* path's approved unchanged behavior lacks a suitable existing test. A purely static/formatting path gets no new test file: its evidence is the semantic-equivalence record below.
**Action:** Classify every production file in Task 1.2's diagnostic inventory as either *behavior-bearing* (its correction can change executable behavior) or *purely static/formatting* (annotations, import ordering, type hints and other edits that leave executable behavior unchanged), recording the classification and its per-path justification. For a behavior-bearing path, identify the relevant existing focused pytest node(s), or author the smallest focused protective test in a test-only commit before any production edit. For a purely static/formatting path, a new focused test is **not** required: record semantic-equivalence evidence showing executable behavior is unchanged, and still identify and run the existing applicable focused node(s) plus that path's checker RED/GREEN. This mirrors bugfix acceptance criterion 4 and design property 4, which admit documented semantic equivalence in place of a new behavioral test for purely static/formatting changes; it is never a license to skip evidence for a behavior-bearing path, and an unclear classification is routed to Ansel rather than resolved in favor of the cheaper branch. Run the applicable node(s) on the pre-correction implementation base and record exact node IDs, command, exit, and output. A protective test may pass both before and after a behavior-preserving correction; do not invent a behavioral failure. If a test exposes unexpected behavior or the intended unchanged behavior is unclear, stop that path and route it to Ansel.

Before any corresponding production-file edit, transfer to its writer: (a) the exact predecessor test commit and diff, or the base commit and explicit “no new test diff” when existing tests are reused; (b) pre-production base branch and commit; (c) the targeted pre-correction Ruff/mypy RED command, diagnostic, full relevant output, non-zero exit, and expected failure; (d) protective-test node IDs and results; and (e) the authorized integration route and identified candidate worktree. This handoff is required before the first edit, not deferred to final QA. RED must be established on the exact base immediately preceding that edit, after any predecessor test commit has been integrated into it; a Task 1.2 diagnostic captured on a different or earlier base does not satisfy this, and no already-made change is retroactively converted into RED. If test and fix work are in separate worktrees, the writer must receive these exact references before starting; the protective test itself is not required to fail where design specifies unchanged behavior.

**Completion Criteria:** Every production-file correction instance has either mapped and passing pre-correction protective-test evidence (behavior-bearing) or a recorded semantic-equivalence justification (purely static/formatting), plus a complete RED handoff ready before its first production edit. Newly authored tests are in a distinct identified predecessor commit/diff. No production edit begins without the matching handoff, RED on the exact immediately-preceding base, and Ansel-authorized integration route. No evidence is drawn from the paused Imre worktree or its approximately 49 modified paths.

**Dependencies:** Task 1.2

**Tracking:** Done · Issue #264 · Card task_9d781cb49f7f4fac · PR #459

## Phase 3: File-Scoped Diagnostic Corrections

### T-3.1.01–T-3.1.61: One correction task per current diagnostic-bearing file

Each row is one separate atomic task, issue, and board card after this exact plan amendment is approved. It authorizes only the exact listed file and the current Ruff/mypy findings shown below. Multiple checker findings for one file stay in one task. Labels are `task` for all; test-only paths also get `test`, and files explicitly named `*_property.py` also get `pbt`. The task's issue/card descriptions must cite this plan version, exact branch/worktree, and dependency IDs. No issue/card exists before Mira approves this amended plan.

| Task | Exact file | Current findings (Ruff / mypy) | Issue labels |
|---|---|---|---|
| T-3.1.01 | `alembic/env.py` | Ruff I001×2 | `task` |
| T-3.1.02 | `alembic/versions/001_initial_schema.py` | Ruff I001×1, UP007×3, UP035×1 | `task` |
| T-3.1.03 | `alembic/versions/002_unique_transcripcion_reunion_id.py` | Ruff UP007×3, UP035×1 | `task` |
| T-3.1.04 | `alembic/versions/003_diarizacion_schema.py` | Ruff I001×1, UP007×3, UP035×1 | `task` |
| T-3.1.05 | `alembic/versions/004_usuarios_schema.py` | Ruff I001×1, UP007×3, UP035×1 | `task` |
| T-3.1.06 | `alembic/versions/005_fix_uuid_columns_to_varchar.py` | Ruff E501×4, UP007×3, UP035×1 | `task` |
| T-3.1.07 | `alembic/versions/006_add_titulo_reunion.py` | Ruff I001×1, UP007×3, UP035×1 | `task` |
| T-3.1.08 | `alembic/versions/007_rename_schema_to_english.py` | Ruff E501×6, UP007×3, UP035×1 | `task` |
| T-3.1.09 | `app/auth/audit.py` | Ruff UP017×1 | `task` |
| T-3.1.10 | `app/auth/authorization.py` | Ruff B008×2, UP035×1 | `task` |
| T-3.1.11 | `app/auth/dependencies.py` | Ruff B008×1, B904×1 | `task` |
| T-3.1.12 | `app/auth/token.py` | Ruff UP017×1 | `task` |
| T-3.1.13 | `app/diarization/assignment.py` | Ruff I001×1 | `task` |
| T-3.1.14 | `app/diarization/cloud_provider.py` | Ruff B904×1 | `task` |
| T-3.1.15 | `app/diarization/state.py` | Ruff I001×1 | `task` |
| T-3.1.16 | `app/diarization/worker.py` | Ruff I001×1, SIM117×1, UP017×1 | `task` |
| T-3.1.17 | `app/ingestion/router.py` | Ruff B008×3, B904×1, SIM117×1 | `task` |
| T-3.1.18 | `app/ingestion/schemas.py` | Ruff UP037×1 | `task` |
| T-3.1.19 | `app/meetings/router.py` | Ruff A002×2, B008×8, B904×2, I001×1, SIM117×4 | `task` |
| T-3.1.20 | `app/meetings/schemas.py` | Ruff UP007×1 | `task` |
| T-3.1.21 | `app/meetings/service.py` | Ruff A002×1 | `task` |
| T-3.1.22 | `app/meetings/speaker_review_service.py` | mypy union-attr×1 | `task` |
| T-3.1.23 | `app/meetings/state_machine.py` | Ruff I001×1 | `task` |
| T-3.1.24 | `app/transcription/cloud_provider.py` | Ruff B904×1 | `task` |
| T-3.1.25 | `asr-engine/main.py` | Ruff B904×2, SIM105×1, SIM115×1 | `task` |
| T-3.1.26 | `diar-engine/main.py` | Ruff B904×2, SIM105×1, SIM115×1 | `task` |
| T-3.1.27 | `tests/auth/conftest.py` | mypy no-untyped-def×1 | `task, test` |
| T-3.1.28 | `tests/auth/test_access_control_property.py` | Ruff B008×1; mypy no-untyped-def×2 | `task, test, pbt` |
| T-3.1.29 | `tests/auth/test_auth_disabled_scope.py` | mypy no-untyped-def×3 | `task, test` |
| T-3.1.30 | `tests/auth/test_login.py` | mypy no-untyped-def×6 | `task, test` |
| T-3.1.31 | `tests/auth/test_user_model.py` | mypy no-untyped-def×2 | `task, test` |
| T-3.1.32 | `tests/conftest.py` | Ruff UP017×1, UP035×1 | `task, test` |
| T-3.1.33 | `tests/diar_engine/test_contract.py` | Ruff I001×1; mypy attr-defined×3, no-untyped-def×7, unused-ignore×1 | `task, test` |
| T-3.1.34 | `tests/diarization/test_assignment_property.py` | Ruff B007×1, B905×2, I001×1 | `task, test, pbt` |
| T-3.1.35 | `tests/diarization/test_cloud_provider_property.py` | Ruff E402×2, I001×2; mypy no-untyped-def×9 | `task, test, pbt` |
| T-3.1.36 | `tests/diarization/test_diarization_engine_property.py` | Ruff I001×1 | `task, test, pbt` |
| T-3.1.37 | `tests/diarization/test_factory_property.py` | mypy arg-type×1, assignment×1, no-untyped-call×3, no-untyped-def×27, var-annotated×1 | `task, test, pbt` |
| T-3.1.38 | `tests/diarization/test_integration.py` | Ruff E501×1, I001×3, SIM117×2, UP017×2; mypy no-untyped-def×11, type-arg×3 | `task, test` |
| T-3.1.39 | `tests/diarization/test_labeling_property.py` | Ruff I001×1 | `task, test, pbt` |
| T-3.1.40 | `tests/diarization/test_local_provider_property.py` | Ruff E402×1, I001×1; mypy arg-type×1, no-untyped-def×6, type-arg×1, var-annotated×1 | `task, test, pbt` |
| T-3.1.41 | `tests/diarization/test_migration.py` | Ruff I001×1; mypy arg-type×1, no-untyped-call×1, no-untyped-def×8, union-attr×2 | `task, test` |
| T-3.1.42 | `tests/diarization/test_repository.py` | Ruff B017×2, I001×1, SIM117×9, UP017×4; mypy no-untyped-def×5, type-arg×5 | `task, test` |
| T-3.1.43 | `tests/diarization/test_state_property.py` | mypy arg-type×1 | `task, test, pbt` |
| T-3.1.44 | `tests/diarization/test_worker.py` | Ruff E501×1, I001×1, SIM117×4, UP017×6; mypy no-untyped-def×10, type-arg×12, var-annotated×1 | `task, test` |
| T-3.1.45 | `tests/infra/test_adaptadores_conformidad_property.py` | mypy no-untyped-def×5, type-arg×10 | `task, test, pbt` |
| T-3.1.46 | `tests/infra/test_queue_retries.py` | Ruff F401×1; mypy no-untyped-def×7 | `task, test` |
| T-3.1.47 | `tests/ingestion/test_playback_source_ingestion.py` | mypy arg-type×5, no-untyped-def×1 | `task, test` |
| T-3.1.48 | `tests/library/conftest.py` | Ruff UP017×3, W292×1 | `task, test` |
| T-3.1.49 | `tests/meetings/test_diarization_endpoint.py` | mypy no-untyped-def×5 | `task, test` |
| T-3.1.50 | `tests/meetings/test_note_management.py` | mypy no-untyped-def×11 | `task, test` |
| T-3.1.51 | `tests/meetings/test_title_history.py` | mypy no-untyped-def×1 | `task, test` |
| T-3.1.52 | `tests/meetings/test_transcript_turn_id.py` | mypy no-untyped-def×1 | `task, test` |
| T-3.1.53 | `tests/test_migration.py` | mypy arg-type×1, no-untyped-call×6, no-untyped-def×7, union-attr×2 | `task, test` |
| T-3.1.54 | `tests/test_queue.py` | Ruff I001×6; mypy attr-defined×4, misc×3, no-untyped-def×28 | `task, test` |
| T-3.1.55 | `tests/transcription/test_cloud_provider.py` | Ruff I001×1, SIM117×2; mypy arg-type×1, no-untyped-def×5, type-arg×1, var-annotated×1 | `task, test` |
| T-3.1.56 | `tests/transcription/test_factory.py` | Ruff I001×1, SIM117×3; mypy arg-type×1, no-untyped-def×9 | `task, test` |
| T-3.1.57 | `tests/transcription/test_integration.py` | Ruff F401×1, I001×1; mypy no-untyped-def×4 | `task, test` |
| T-3.1.58 | `tests/transcription/test_local_provider.py` | Ruff B905×1, I001×1; mypy arg-type×1, no-untyped-def×5, type-arg×2, var-annotated×1 | `task, test` |
| T-3.1.59 | `tests/transcription/test_meeting_capture_property.py` | mypy arg-type×1, no-untyped-def×1, type-arg×3, var-annotated×1 | `task, test, pbt` |
| T-3.1.60 | `tests/transcription/test_repository.py` | Ruff F401×1, I001×1, SIM117×1, UP017×2; mypy no-untyped-def×2, type-arg×2 | `task, test` |
| T-3.1.61 | `tests/transcription/test_worker.py` | Ruff I001×2, SIM117×14, UP017×1; mypy arg-type×2, no-untyped-def×13, type-arg×11, var-annotated×2 | `task, test` |

### Issue/card tracking for T-3.1.01–T-3.1.61

| Task | Tracking |
|---|---|
| T-3.1.01 | Issue #326 · Card task_2c3b6bebf14f4348 · PR #458 · Done |
| T-3.1.02 | Issue #327 · Card task_bf7ecf6142d346e6 |
| T-3.1.03 | Issue #328 · Card task_061bddef35f246a1 |
| T-3.1.04 | Issue #329 · Card task_85e5ee9e158c4f30 |
| T-3.1.05 | Issue #330 · Card task_c3dfb08400df4fb9 |
| T-3.1.06 | Issue #331 · Card task_812a55eb29494c5b |
| T-3.1.07 | Issue #332 · Card task_221e3b81934844ce |
| T-3.1.08 | Issue #333 · Card task_9118c3aeba7f458d |
| T-3.1.09 | Issue #334 · Card task_fc0a88aa3262413e |
| T-3.1.10 | Issue #335 · Card task_16d1a54118dd4590 |
| T-3.1.11 | Issue #336 · Card task_e31207d8cfb042c3 |
| T-3.1.12 | Issue #337 · Card task_4fe91b55210f4902 |
| T-3.1.13 | Issue #338 · Card task_b2894a1b41664ef5 |
| T-3.1.14 | Issue #339 · Card task_d9060c9f79b346ce |
| T-3.1.15 | Issue #340 · Card task_bc422932256d4afd |
| T-3.1.16 | Issue #341 · Card task_b18c2cd83e214a3b |
| T-3.1.17 | Issue #342 · Card task_153535d2f483425e |
| T-3.1.18 | Issue #343 · Card task_b7d536f17b744d05 |
| T-3.1.19 | Issue #344 · Card task_80bb9d30b55d4460 |
| T-3.1.20 | Issue #345 · Card task_debf2ac069c54a40 |
| T-3.1.21 | Issue #346 · Card task_7741f6f73f4744b9 |
| T-3.1.22 | Issue #347 · Card task_a51038580a414fcd |
| T-3.1.23 | Issue #348 · Card task_7547e887bf434b12 |
| T-3.1.24 | Issue #349 · Card task_1663610cd4ed4cff |
| T-3.1.25 | Issue #350 · Card task_d02b6e8c4d814984 |
| T-3.1.26 | Issue #351 · Card task_59aac81ea8054377 |
| T-3.1.27 | Issue #352 · Card task_9f1282d6970a445d |
| T-3.1.28 | Done · Issue #353 · Card task_33bf40d2ec6146e4 · PR #426 |
| T-3.1.29 | Issue #354 · Card task_e34f1f55e38e483b |
| T-3.1.30 | Done · Issue #355 · Card task_a0a08418e19f4cc2 · PR #432 |
| T-3.1.31 | Done · Issue #356 · Card task_432b6ebacc584e3e · PR #388 |
| T-3.1.32 | Done · Issue #357 · Card task_b2193d5a036c4013 · PR #430 |
| T-3.1.33 | Issue #358 · Card task_0f9b0e5cff7441f0 |
| T-3.1.34 | Done · Issue #359 · Card task_4d85d49373ed4e3e · PR #431 |
| T-3.1.35 | Issue #360 · Card task_a0215908954e429b |
| T-3.1.36 | Issue #361 · Card task_679c84ddba6544df |
| T-3.1.37 | Issue #362 · Card task_76c632e57e91477e |
| T-3.1.38 | Done · Issue #363 · Card task_10a2fd0ed4d4439d · PR #435 |
| T-3.1.39 | Issue #364 · Card task_b3822206a07f4e0f |
| T-3.1.40 | Done · Issue #365 · Card task_1897141c7c474c37 · PR #436 |
| T-3.1.41 | Issue #366 · Card task_bafdfcb3bc714299 |
| T-3.1.42 | Issue #367 · Card task_fe35ad6c1d00426a |
| T-3.1.43 | Done · Issue #368 · Card task_e60ecb4fab1b46b0 · PR #438 |
| T-3.1.44 | Issue #369 · Card task_facdc3e0b0154885 |
| T-3.1.45 | Done · Issue #370 · Card task_ef8575211880453f · PR #441 |
| T-3.1.46 | Issue #371 · Card task_69a6cc84820f493d |
| T-3.1.47 | Issue #372 · Card task_53211a4d325048ca · PR #445 · Done |
| T-3.1.48 | Issue #373 · Card task_260190e5c6b34b1d |
| T-3.1.49 | Done · Issue #374 · Card task_ef4387d699c94a33 · PR #442 |
| T-3.1.50 | Issue #375 · Card task_e5accf1b07694b51 |
| T-3.1.51 | Issue #376 · Card task_232217e2a98a41ac |
| T-3.1.52 | Issue #377 · Card task_0859f7811a3349f8 |
| T-3.1.53 | Issue #378 · Card task_4775e29d81b04838 |
| T-3.1.54 | Issue #379 · Card task_f501a3dd376f40a0 |
| T-3.1.55 | Issue #380 · Card task_fd6af56086e14309 |
| T-3.1.56 | Issue #381 · Card task_bcbba7081c3b4c0f |
| T-3.1.57 | Issue #382 · Card task_394594b0b6674985 |
| T-3.1.58 | Issue #383 · Card task_16175357fb414edf |
| T-3.1.59 | Issue #384 · Card task_35ae8fb35e254041 |
| T-3.1.60 | Issue #385 · Card task_9f1912235da941e0 |
| T-3.1.61 | Done · Issue #386 · Card task_be8f43444a0149fb · PR #457 |

### Focused RED/test seams for every file task

The exact node/fixture seam is specified per task below; execute its node with `python -m pytest -q <node>` from `backend/` as applicable. These are seam references, not claims that all listed tests were already run: only results explicitly documented in the T-2.1 evidence map are completed evidence. Each writer still captures that task's exact checker RED on the immediate pre-edit base and the matching test result before any production edit. `tests/library/conftest.py` is a fixture-only module with no discovered test consumer; its seam is the `async_engine` fixture lifecycle, and its UP017/W292 corrections are static-only (no behavior test is added). The added `app/ingestion/schemas.py` and `app/meetings/speaker_review_service.py` paths have candidate seams below, but remain production-edit blocked until the T-2.1 per-path classification, test mapping, and handoff are completed on the authorized base.

| Task | Focused test seam (module path + function/route) |
|---|---|
| T-3.1.01 | `tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data`; `::test_downgrade_reverses_every_rename` |
| T-3.1.02 | `tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data`; `::test_orm_schema_uses_english_table_names` |
| T-3.1.03 | `tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data`; `::test_downgrade_reverses_every_rename` |
| T-3.1.04 | `tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data`; `::test_downgrade_reverses_every_rename` |
| T-3.1.05 | `tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data`; `::test_downgrade_reverses_every_rename` |
| T-3.1.06 | `tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data`; `::test_downgrade_reverses_every_rename` |
| T-3.1.07 | `tests/test_migration.py::test_revision_007_chains_after_006`; `::test_upgrade_renames_every_table_without_dropping_data` |
| T-3.1.08 | `tests/test_migration.py::test_revision_007_chains_after_006`; `::test_upgrade_renames_every_table_without_dropping_data` |
| T-3.1.09 | `tests/auth/test_access_control_property.py::test_property_10_every_denial_generates_exactly_one_record` |
| T-3.1.10 | `tests/auth/test_access_control_property.py::test_property_10_access_granted_iff_authorized`; `::test_property_10_every_denial_generates_exactly_one_record` |
| T-3.1.11 | `tests/auth/test_auth_disabled_scope.py::test_invalid_token_preserves_unauthorized_error_contract`; `::test_bypass_active_in_test_environment` |
| T-3.1.12 | `tests/auth/test_login.py::test_login_valid_credentials_issues_jwt` |
| T-3.1.13 | `tests/diarization/test_assignment_property.py::test_property_9_exactly_one_assignment_per_turn`; `::test_property_9_tie_break_by_lower_sequence` |
| T-3.1.14 | `tests/diarization/test_cloud_provider_property.py::test_example_120s_timeout_raises_external_service_error` |
| T-3.1.15 | `tests/diarization/test_state_property.py::test_property_16_valid_transitions_produce_correct_state` |
| T-3.1.16 | `tests/diarization/test_worker.py::test_property_20_engine_failure_propagates_without_completed` |
| T-3.1.17 | `tests/ingestion/test_playback_source_ingestion.py::test_invalid_capture_metadata_returns_422_before_object_storage` |
| T-3.1.18 | `tests/ingestion/test_playback_source_ingestion.py::test_ingestion_contract_preserves_explicit_capture_evidence[overrides0-muxed-None]` |
| T-3.1.19 | `tests/meetings/test_join_triggers.py::test_request_join_manual_transitions_and_enqueues`; `tests/meetings/test_note_management.py::test_rename_200_updates_title` |
| T-3.1.20 | `tests/meetings/test_register_meeting_property.py::test_property_2_accepts_link_input`; `::test_property_2_rejects_invalid_links` |
| T-3.1.21 | `tests/meetings/test_register_meeting_property.py::test_property_2_accepts_link_input`; `::test_property_2_accepts_manual_input` |
| T-3.1.22 | `tests/speaker_review/test_disposition_idempotency.py::test_persistent_replay_returns_original_result_without_second_mutation` |
| T-3.1.23 | `tests/meetings/test_state_machine_property.py::test_property_3_only_valid_transitions_produce_a_new_state` |
| T-3.1.24 | `tests/transcription/test_cloud_provider.py::test_example_cloud_timeout_raises_service_error` |
| T-3.1.25 | `tests/transcription/test_asr_engine_service.py::test_failed_s3_download_removes_partial_file_and_chains_cause`; `::test_transcription_failure_returns_500_and_removes_audio_file` |
| T-3.1.26 | `tests/diar_engine/test_contract.py::test_diarization_failure_removes_downloaded_temp_file`; `::test_download_http_error_preserves_status_and_detail` |
| T-3.1.27 | `tests/auth/conftest.py::api_client` → `tests/auth/test_login.py::test_login_valid_credentials_issues_jwt` |
| T-3.1.28 | `tests/auth/test_access_control_property.py::test_property_10_access_granted_iff_authorized` |
| T-3.1.29 | `tests/auth/test_auth_disabled_scope.py::test_bypass_active_in_test_environment` |
| T-3.1.30 | `tests/auth/test_login.py::test_login_valid_credentials_issues_jwt` |
| T-3.1.31 | `tests/auth/test_user_model.py::test_user_can_be_created_and_read` |
| T-3.1.32 | `tests/conftest.py::async_engine` → `tests/meetings/test_join_triggers.py::test_request_join_manual_transitions_and_enqueues` |
| T-3.1.33 | `tests/diar_engine/test_contract.py::TestContratoDiarEngine::test_health_endpoint` |
| T-3.1.34 | `tests/diarization/test_assignment_property.py::test_property_9_exactly_one_assignment_per_turn` |
| T-3.1.35 | `tests/diarization/test_cloud_provider_property.py::test_example_http_error_raises_external_service_error` |
| T-3.1.36 | `tests/diarization/test_diarization_engine_property.py::test_property_6_diarization_result_ascending_order` |
| T-3.1.37 | `tests/diarization/test_factory_property.py::test_property_1_local_with_capitalization_and_spaces` |
| T-3.1.38 | `tests/diarization/test_integration.py::TestDiarizationWorkerSubscription::test_worker_subscribes_to_diarize_topic` |
| T-3.1.39 | `tests/diarization/test_labeling_property.py::test_property_7_speaker_count_equals_distinct_raw_labels` |
| T-3.1.40 | `tests/diarization/test_local_provider_property.py::test_property_4_faithful_mapping_of_local_diarization_response` |
| T-3.1.41 | `tests/diarization/test_migration.py::test_migration_003_creates_three_tables` |
| T-3.1.42 | `tests/diarization/test_repository.py::test_property_12_diarization_uniqueness_per_meeting` |
| T-3.1.43 | `tests/diarization/test_state_property.py::test_property_16_valid_transitions_produce_correct_state` |
| T-3.1.44 | `tests/diarization/test_worker.py::test_property_20_engine_failure_propagates_without_completed` |
| T-3.1.45 | `tests/infra/test_adaptadores_conformidad_property.py::test_property_13_store_roundtrip_save_get` |
| T-3.1.46 | `tests/infra/test_queue_retries.py::TestReadMaxRetriesDiarize::test_default_when_absent` |
| T-3.1.47 | `tests/ingestion/test_playback_source_ingestion.py::test_ingestion_contract_preserves_explicit_capture_evidence[overrides0-muxed-None]` |
| T-3.1.48 | `tests/library/conftest.py::async_engine` fixture lifecycle; no `tests/library/` consumer test is currently discovered |
| T-3.1.49 | `tests/meetings/test_diarization_endpoint.py::test_diarization_200_with_speakers_and_assignments` |
| T-3.1.50 | `tests/meetings/test_note_management.py::test_rename_200_updates_title` |
| T-3.1.51 | `tests/meetings/test_title_history.py::test_listing_includes_null_title` |
| T-3.1.52 | `tests/meetings/test_transcript_turn_id.py::test_segments_include_the_turn_id` |
| T-3.1.53 | `tests/test_migration.py::test_upgrade_renames_every_table_without_dropping_data` (through migration 007; the separate 009 failing nodes remain outside this task) |
| T-3.1.54 | `tests/test_queue.py::TestRabbitMQJobQueueBehavior::test_ack_on_success` |
| T-3.1.55 | `tests/transcription/test_cloud_provider.py::test_example_integration_https_and_auth_header` |
| T-3.1.56 | `tests/transcription/test_factory.py::test_property_1_absent_or_empty_is_local` |
| T-3.1.57 | `tests/transcription/test_integration.py::TestASREngineContract::test_post_transcribe_response_shape` |
| T-3.1.58 | `tests/transcription/test_local_provider.py::test_property_4_faithful_mapping_of_local_response` |
| T-3.1.59 | `tests/transcription/test_meeting_capture_property.py::test_property_7_temporal_invariant_of_persisted_turns` |
| T-3.1.60 | `tests/transcription/test_repository.py::test_property_13_persistence_roundtrip` |
| T-3.1.61 | `tests/transcription/test_worker.py::test_property_16_invalid_input_does_not_persist` |

For each task, scope remains only its listed source file. Its dependency is the frozen T1.2 evidence plus the exact current-base snapshot in `evidence-current-base/`; production-file edits additionally require the matching Task 2.1 per-path classification, exact focused-node result, and complete handoff before editing. Task 2.1 remains incomplete, so this table names executable candidate seams but does not assert all evidence or approval is complete. The targeted checker RED must be captured on the exact base immediately before the first edit using `ruff check <path>` and/or `mypy <path>` as applicable, and transferred to the writer with the listed test-node run result. Test-only files use the same-path checker RED and the named focused pytest node; do not modify production files from a test-path task. No source edit or behavior change is authorized by this plan amendment.

**Completion Criteria (each instance):** Only the listed file changes; all listed checker findings are absent on the same targeted checker rerun; applicable focused pytest evidence passes; for production files, the matching Task 2.1 handoff is present and semantics-preserving equivalence is recorded. Migration edits preserve operations, order, resulting schema/data semantics; no exception context, FastAPI injection/body shape, cleanup, or runtime behavior changes without a separate authorized disposition. Findings that cannot be fixed within these bounds are escalated to Ansel, not suppressed.

**Dependencies:** Current-base evidence snapshot and Task 1.2; for each production path, its matching Task 2.1 evidence/handoff before edits. Distinct paths have no invented pairwise dependency; each runs in its own issue worktree. Ansel sequences only real prerequisites and verified shared-resource conflicts. Changes integrate to the single candidate only through Ansel's authorized route. The excluded `009_recording_media_sources.py` I001 remains with separate card `task_6ccdc76cbc0f4fe9`, not among these 61 instances.

**Task 3.1.36 tracking:** Done · Issue #361 · Card `task_679c84ddba6544df` · PR #389

### Task 3.1.09: Clear UP017 in `backend/app/auth/audit.py`

**Status:** Done (QA passed; implementation PR open)

**Tracking:** Issue #334 · Card task_fc0a88aa3262413e · PR #392

**Instantiated instance T-3.1.33:** `backend/tests/diar_engine/test_contract.py` — Ruff I001 and recorded mypy findings resolved; file-scoped Ruff, mypy and pytest passed; QA PASS. **Tracking:** Issue #358 · Card `task_0f9b0e5cff7441f0` · PR #391 · Done.

## Phase 4: Integrated Candidate Validation and Handoff

### Task 4.1: Run complete backend validation after all file-scoped corrections are integrated

**Files:** Full configured backend target in the single Ansel-authorized candidate worktree; no new intended edits.
**Action:** In the fresh environment provisioned in Task 1.1, from `backend/`, run focused protective pytest nodes for each changed production path, then `pytest -q`, `ruff check .`, and `mypy .`. Record actual tool versions, exact commands, exits, full outputs or faithful saved-output references, and any required external-service availability. Compare the default pytest discovery/marker summary to Task 1.2; do not remove/skip tests or weaken markers/checker policy. A service-blocked default test result is blocked, not green.

**Completion Criteria:** Every correction instance is integrated into the identified candidate; focused tests and all full checks have recorded results. An unblocked pass requires `pytest -q`, `ruff check .`, and `mypy .` to exit 0 under unchanged configuration. Any failure, timeout, or unavailable service is recorded as such and cannot be reported as acceptance pass.

**Dependencies:** All T-3.1.01–T-3.1.61 instances and their authorized integration into the candidate worktree, plus completion and authorized integration of the separate migration 009 lineage defect tracked by `task_6ccdc76cbc0f4fe9`. The current-base map records three default migration-test failures in that separate defect; this phase is not green until they are resolved or explicitly reported as blocked.

**Tracking:** Issue #265 · Card task_f6e79b01ba8a4ea0

### Task 4.2: Transfer the exact candidate and acceptance evidence to Ansel

**Files:** Existing candidate PR/task handoff; no new repository artifact is prescribed.
**Action:** Send Ansel the exact candidate commit, base branch/SHA, worktree, tool versions, Task 1.2 baseline, each path-scoped correction diff and its pre-edit RED handoff, test predecessor commit/diff and pre-production base, per-path protective-test results, final commands/exits/outputs, unchanged-policy evidence, and blocked prerequisites. Identify each file's integration disposition and ensure all test and production changes are delivered together in the candidate lineage. Do not merge, claim independent QA approval, or claim release authorization.

**Completion Criteria:** Ansel can trace every recorded baseline diagnostic to a file-scoped correction or explicit escalation and can evaluate each bugfix criterion against the identified candidate and evidence. No unresolved or blocked item is represented as passed.

**Dependencies:** Task 4.1

**Tracking:** Issue #266 · Card task_7d757a86d38a4385
