---
name: mira-design-audit
description: Read-only rubric for Mira to audit Sauri technical designs against approved requirements and product constraints.
---

# Mira specialization: design audit

Use this rubric only when Ansel explicitly assigns the `design` specialization. Verify engineering coherence without taking over architecture or revising the design.

## Required evidence
- Exact `design.md` version under review.
- APPROVED, exact-version requirements or bugfix artifact.
- Approved `PRODUCT_BASELINE.md` and relevant owner decisions/constraints.
- Relevant repository sources needed to verify claims, with exact worktree/branch/commit.

If an input is absent or versions do not match, stop before audit and report the missing context to Ansel. Do not infer that a requirement changed or substitute historical architecture for an approved constraint.

## Review questions
1. Is every approved requirement addressed and traceable to a design element, with no silent scope changes or lost acceptance behavior?
2. Are component boundaries, interfaces, data/control flow, state, persistence, and external integrations specific and consistent with the inspected repository and approved constraints?
3. Are normal, failure, retry, timeout, partial, migration/rollback, compatibility, and recovery behaviors addressed where relevant?
4. Are security, privacy, authorization, retention, and sensitive-data boundaries covered where applicable?
5. Are trade-offs, rejected alternatives, assumptions, and unresolved technical decisions explicit and evidence-backed?
6. Can every key correctness property be verified by observable tests or other named evidence?
7. Does the design avoid unsupported architecture claims, accidental scope, and contradictions with the approved product intent?

For every finding, cite the design location and the exact upstream requirement/constraint or repository evidence, explain the implementation or product risk, and state the smallest correction. Distinguish an author-correctable design gap from a genuine owner decision. Do not reject stylistic choices that preserve requirements and correctness.
