---
name: mira-bugfix-audit
description: Read-only rubric for Mira to audit Sauri bugfix specifications against reproducible QA evidence.
---

# Mira specialization: bugfix audit

Use only when Ansel explicitly assigns the `bugfix` specialization. This is a quality gate, not root-cause authoring or implementation.

## Required evidence
- Exact `bugfix.md` version under review.
- QA's deterministic reproduction and observed current behavior.
- Expected behavior source and explicit unchanged behavior/regression boundaries.
- Repository/worktree/branch evidence needed to verify claims.

If evidence is missing, mismatched, or not reproducible, stop before audit and request the missing evidence from Ansel/QA; do not frame a technical evidence gap as an owner decision.

## Review questions
1. Are current, expected, and unchanged behaviors clearly separated and supported by evidence?
2. Are reproduction steps deterministic, minimal, and tied to an observable failure?
3. Is the root-cause hypothesis evidence-backed, with confidence and alternatives stated rather than presented as fact?
4. Does the proposed fix address the cause rather than mask a symptom, and remain within approved product scope?
5. Are regression properties and tests specified for the failure and every important unchanged behavior?
6. Are unresolved product decisions distinguished from technical unknowns that QA/developer can investigate?

For findings, cite exact artifact locations and evidence, explain impact, and state the smallest correction. Do not invent expected behavior or approve a fix plan whose basis is an unverified hypothesis.
