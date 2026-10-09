---
name: mira-tasks-audit
description: Read-only rubric for Mira to audit Sauri implementation plans for traceability, test readiness, and safe parallel execution.
---

# Mira specialization: implementation-plan audit

Use this rubric only when Ansel explicitly assigns the `tasks` specialization. Audit execution readiness; do not author, reorder, or edit tasks.

## Required evidence
- `tasks.md` snapshot/reference supplied by Ansel. Record the reference once in the report so
  the verdict can be associated with the submitted snapshot; do not require Ansel to repeatedly
  recalculate or re-submit it.
- APPROVED, exact-version design and requirements/bugfix artifacts.
- Relevant repo/worktree/branch context and known resource constraints.

If required evidence is absent or contradictory, report the specific preflight gap to Ansel once
and do not issue an audit verdict. Ansel resolves the source once; if it cannot be recovered,
document the blocker and stop this audit path rather than looping. Do not treat issues/APX cards as
substitutes for approved specs. If the submitted artifact remains unchanged, its completed verdict
stands; only an actual edit to that artifact warrants a targeted new audit under the bounded review
cycle. Unrelated repository edits do not invalidate the verdict.

## Review questions
1. Does each required design/requirements property map to one or more explicit tasks and acceptance checks?
2. Is each task atomic, actionable in a focused session, scoped to real project-relative files, and independently verifiable?
3. Are dependencies explicit and accurate? Ordering must encode actual prerequisites or shared-resource conflicts, not imply serial execution of independent work.
4. Does the dependency graph expose all safe parallel work while respecting true dependencies and resource limits?
5. Are required test tasks present for each correctness property, and do they enforce RED -> GREEN -> REFACTOR rather than demoting tests to optional?
6. Do tasks identify observable done conditions, validation commands/evidence, and any needed setup or migration/rollback checks?
7. Is the plan free of implementation scope not authorized by the approved design and requirements?

For every finding, cite task ID/section and its source requirement/design element, describe the delivery or correctness risk, and specify the smallest correction. Report only real missing/incorrect dependencies; do not demand artificial task ordering.
