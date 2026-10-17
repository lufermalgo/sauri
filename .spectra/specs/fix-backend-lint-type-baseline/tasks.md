# Implementation Plan — Restore backend Ruff and mypy baseline

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | Establish an isolated candidate environment and capture the exact pre-correction baseline | 1.1–1.2 | None; 1.2 requires 1.1 |
| 2 | Map and preserve existing behavior before production edits | 2.1 | 1.2 |
| 3 | Correct findings in atomic, file-scoped units with RED evidence transferred before each edit | 3.1.N (one instance per diagnostic-bearing file) | 1.2; matching 2.1 evidence before production-file edits |
| 4 | Validate and hand off the integrated candidate | 4.1–4.2 | Every 3.1.N instance |

The diagnostic-bearing file list is intentionally determined by Task 1.2 on the exact approved implementation base and actual candidate tool versions; upstream artifacts do not enumerate it. Task 1.2 creates one numbered Task 3.1.N instance for each in-scope file with Ruff and/or mypy findings. A single file's Ruff and mypy findings belong to the same atomic correction task, not competing global Ruff and mypy workstreams. Each instance names exactly one path and is independently reviewable. Test-only files are separate instances from production files. No task instance is created for a path without a finding.

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

## Phase 2: Behavior-Preservation Evidence

### Task 2.1: Map and verify protective tests for each affected production path

**Files:** Existing backend test files for affected production paths; add a focused synthetic-data test only where a *behavior-bearing* path's approved unchanged behavior lacks a suitable existing test. A purely static/formatting path gets no new test file: its evidence is the semantic-equivalence record below.
**Action:** Classify every production file in Task 1.2's diagnostic inventory as either *behavior-bearing* (its correction can change executable behavior) or *purely static/formatting* (annotations, import ordering, type hints and other edits that leave executable behavior unchanged), recording the classification and its per-path justification. For a behavior-bearing path, identify the relevant existing focused pytest node(s), or author the smallest focused protective test in a test-only commit before any production edit. For a purely static/formatting path, a new focused test is **not** required: record semantic-equivalence evidence showing executable behavior is unchanged, and still identify and run the existing applicable focused node(s) plus that path's checker RED/GREEN. This mirrors bugfix acceptance criterion 4 and design property 4, which admit documented semantic equivalence in place of a new behavioral test for purely static/formatting changes; it is never a license to skip evidence for a behavior-bearing path, and an unclear classification is routed to Ansel rather than resolved in favor of the cheaper branch. Run the applicable node(s) on the pre-correction implementation base and record exact node IDs, command, exit, and output. A protective test may pass both before and after a behavior-preserving correction; do not invent a behavioral failure. If a test exposes unexpected behavior or the intended unchanged behavior is unclear, stop that path and route it to Ansel.

Before any corresponding production-file edit, transfer to its writer: (a) the exact predecessor test commit and diff, or the base commit and explicit “no new test diff” when existing tests are reused; (b) pre-production base branch and commit; (c) the targeted pre-correction Ruff/mypy RED command, diagnostic, full relevant output, non-zero exit, and expected failure; (d) protective-test node IDs and results; and (e) the authorized integration route and identified candidate worktree. This handoff is required before the first edit, not deferred to final QA. RED must be established on the exact base immediately preceding that edit, after any predecessor test commit has been integrated into it; a Task 1.2 diagnostic captured on a different or earlier base does not satisfy this, and no already-made change is retroactively converted into RED. If test and fix work are in separate worktrees, the writer must receive these exact references before starting; the protective test itself is not required to fail where design specifies unchanged behavior.

**Completion Criteria:** Every production-file correction instance has either mapped and passing pre-correction protective-test evidence (behavior-bearing) or a recorded semantic-equivalence justification (purely static/formatting), plus a complete RED handoff ready before its first production edit. Newly authored tests are in a distinct identified predecessor commit/diff. No production edit begins without the matching handoff, RED on the exact immediately-preceding base, and Ansel-authorized integration route. No evidence is drawn from the paused Imre worktree or its approximately 49 modified paths.

**Dependencies:** Task 1.2

## Phase 3: File-Scoped Diagnostic Corrections

### Task 3.1.N: Correct all in-scope findings in one diagnostic-bearing file

**File:** Exactly one path `P`, substituted from Task 1.2's inventory when this task instance is created; no other file is in scope for this instance.
**Action:** For path `P`, fix only its recorded Ruff and/or mypy findings with the smallest semantics-preserving edits. Keep the exact pre-correction checker RED output for `P`, captured on the base immediately preceding this instance's first edit, with the task. Do not source edits, diffs, or RED evidence from the paused Imre worktree or its approximately 49 modified paths; any authorized transfer of that work is Ansel's decision and must be identified in writing before it is used. For a production path, first receive the complete Task 2.1 handoff for `P`; for a test-only path, use the same-path checker RED record and do not edit unrelated production files. Do not modify `backend/pyproject.toml`, dependency declarations, rules, exclusions, markers, or ignores. If `P` is a migration, preserve operations, order, and resulting schema/data semantics and record the equivalence evidence. Stop and report to Ansel if a fix changes runtime/migration behavior, spans another file beyond the approved diagnostic unit, or needs a policy/dependency change.

**Completion Criteria:** The targeted finding(s) for `P` are absent when the relevant configured checker is rerun; its exact diff is limited to `P`; production-path protective tests remain green, or static/format-only equivalence is documented where applicable. Every finding for `P` is either resolved with evidence or explicitly escalated; no finding is silently suppressed or called clean.

**Dependencies:** Task 1.2; for a production path, the matching Task 2.1 handoff must be complete before editing. Instances for distinct paths are dependency-ready in parallel; this plan asserts no numeric concurrency limit, because none was verified in the packet. Ansel schedules ready instances within effective runtime capacity and any real shared-resource conflict he has verified. Each instance works from the same recorded base and transfers its exact commit/diff to the one candidate worktree only through Ansel's authorized integration route; integration into that shared candidate is serialized. Instances targeting the same path are prohibited because Ruff and mypy findings for one path are combined into this single instance.

## Phase 4: Integrated Candidate Validation and Handoff

### Task 4.1: Run complete backend validation after all file-scoped corrections are integrated

**Files:** Full configured backend target in the single Ansel-authorized candidate worktree; no new intended edits.
**Action:** In the fresh environment provisioned in Task 1.1, from `backend/`, run focused protective pytest nodes for each changed production path, then `pytest -q`, `ruff check .`, and `mypy .`. Record actual tool versions, exact commands, exits, full outputs or faithful saved-output references, and any required external-service availability. Compare the default pytest discovery/marker summary to Task 1.2; do not remove/skip tests or weaken markers/checker policy. A service-blocked default test result is blocked, not green.

**Completion Criteria:** Every correction instance is integrated into the identified candidate; focused tests and all full checks have recorded results. An unblocked pass requires `pytest -q`, `ruff check .`, and `mypy .` to exit 0 under unchanged configuration. Any failure, timeout, or unavailable service is recorded as such and cannot be reported as acceptance pass.

**Dependencies:** All Task 3.1.N instances and their authorized integration into the candidate worktree.

### Task 4.2: Transfer the exact candidate and acceptance evidence to Ansel

**Files:** Existing candidate PR/task handoff; no new repository artifact is prescribed.
**Action:** Send Ansel the exact candidate commit, base branch/SHA, worktree, tool versions, Task 1.2 baseline, each path-scoped correction diff and its pre-edit RED handoff, test predecessor commit/diff and pre-production base, per-path protective-test results, final commands/exits/outputs, unchanged-policy evidence, and blocked prerequisites. Identify each file's integration disposition and ensure all test and production changes are delivered together in the candidate lineage. Do not merge, claim independent QA approval, or claim release authorization.

**Completion Criteria:** Ansel can trace every recorded baseline diagnostic to a file-scoped correction or explicit escalation and can evaluate each bugfix criterion against the identified candidate and evidence. No unresolved or blocked item is represented as passed.

**Dependencies:** Task 4.1
