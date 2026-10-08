---
name: mira-tasks-audit
description: Read-only rubric for Mira to audit Sauri implementation plans for traceability, test readiness, and safe parallel execution.
---

# Mira specialization: implementation-plan audit

Use this rubric only when Ansel explicitly assigns the `tasks` specialization. Audit execution readiness; do not author, reorder, or edit tasks.

## Required evidence
- Exact `tasks.md` version under review.
- APPROVED, exact-version design and requirements/bugfix artifacts.
- Relevant repo/worktree/branch context and known resource constraints.

If required evidence is absent or mismatched, stop before audit and report the missing context to Ansel. Do not treat issues/APX cards as substitutes for approved specs.

## Review questions
1. Does each required design/requirements property map to one or more explicit tasks and acceptance checks?
2. Is each task atomic, actionable in a focused session, scoped to real project-relative files, and independently verifiable?
3. Are dependencies explicit and accurate? Ordering must encode actual prerequisites or shared-resource conflicts, not imply serial execution of independent work.
4. Does the dependency graph expose all safe parallel work while respecting true dependencies and resource limits?
5. Are required test tasks present for each correctness property, and do they enforce RED -> GREEN -> REFACTOR rather than demoting tests to optional?
6. Do tasks identify observable done conditions, validation commands/evidence, and any needed setup or migration/rollback checks?
7. Is the plan free of implementation scope not authorized by the approved design and requirements?

For every finding, cite task ID/section and its source requirement/design element, describe the delivery or correctness risk, and specify the smallest correction. Report only real missing/incorrect dependencies; do not demand artificial task ordering.
