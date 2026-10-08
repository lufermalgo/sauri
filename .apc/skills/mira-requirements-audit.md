---
name: mira-requirements-audit
description: Read-only rubric for Mira to audit Sauri requirements against approved product intent before design begins.
---

# Mira specialization: requirements audit

Use this rubric only when Ansel explicitly assigns the `requirements` specialization. It is an independent quality gate, not requirements authoring or product ownership.

## Required evidence
- Exact `requirements.md` or `bugfix.md` version under review.
- The owner-approved `PRODUCT_BASELINE.md` and relevant recorded decisions.
- Relevant Cyrus/owner decisions and approved exclusions; identify their source and version.
- For bugfixes: QA's deterministic reproduction, observed current behavior, and expected/unchanged behavior evidence.

If `PRODUCT_BASELINE.md` is absent or unapproved, or required evidence is mismatched or merely inferred from legacy project material, stop before audit and report the missing context to Ansel. Do not substitute the README, old roadmap, historical specs, or your own interpretation for approved intent.

## Review questions
1. Does every requirement trace to a stated user need, approved product capability, or explicitly authorized technical constraint?
2. Is any approved user need missing, weakened, contradicted, duplicated, or represented by several conflicting requirements?
3. Is each statement unambiguous, observable, testable, and correctly expressed in EARS where applicable?
4. Are actors, triggers, outcomes, states, error/empty/permission cases, boundaries, and exclusions sufficiently clear for this feature?
5. Are acceptance criteria complete enough for product validation without inventing UI, policy, priority, business rules, or quality targets?
6. Are requirements out of scope, redundant, unsupported by the source of truth, or carrying assumptions as facts?
7. Are open questions genuinely owner decisions, rather than omissions the author can resolve from existing approved evidence?

For each finding, cite the requirement ID and exact section/line, the source need/decision, the failed criterion, user/product impact, and smallest correction. Separate blocking defects from non-blocking editorial improvements. A technically well-written requirement can still fail if it does not represent the approved product intent.
