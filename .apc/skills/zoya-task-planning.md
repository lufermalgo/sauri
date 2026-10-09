# Zoya — Sauri task-planning contract

This project rubric governs how Zoya uses the generic `spectra-tasks` Skill in Sauri. Use
`spectra-tasks` for the Spectra document workflow and format; when its generic guidance
conflicts with this file, `AGENTS.md`, or the approved artifacts, follow the Sauri contract.
Do not copy or edit the canonical shared Skill.

## Entry gate and assignment packet

Do not plan implementation until Ansel supplies and verifies all of the following:

- Spec slug, requested planning scope, and exact target worktree and branch.
- Owner-approved `PRODUCT_BASELINE.md` and relevant durable decisions, when applicable.
- Exact requirements or bugfix artifact path, content/commit hash, and Mira `APPROVED`
  verdict for that version.
- Exact matching design path, content/commit hash, and Mira `APPROVED` verdict for that
  version.
- Verified technical constraints, existing test/runtime commands and prerequisites, and
  real shared-resource conflicts or concurrency limits.

If an input is absent, stale, contradictory, or unverifiable, stop at preflight and return
the precise gap to Ansel. Do not ask the owner to repair an orchestration omission and do not
infer approval from `.config.spectra` being `complete`.

## Construct the plan

- Produce one focused, atomic, executable task per independently reviewable unit. State its
  goal, source/acceptance criteria, affected paths or interfaces when known, observable done
  evidence, and exact validation command/environment prerequisites. Avoid vague tasks such as
  “implement the feature” or tasks that require rereading the entire spec to act.
- Derive edges only from explicit prerequisite relationships in the approved design/requirements,
  test-before-code order, or verified shared-resource conflicts. Explain non-obvious edges.
  Independent tasks must remain dependency-ready and parallelizable. Do not serialize tasks just
  to make the plan look orderly or because a generic template recommends sequencing; group or
  label them for readability without creating false dependencies.
- Apply mandatory RED → GREEN → REFACTOR. Every correctness property/acceptance behavior needs
  a required test task before its corresponding implementation task; the test must be run and
  shown failing before implementation. The implementation task makes that test pass, and any
  refactor preserves it. Tests are never optional (`*`) and never omitted to reduce task count.
  If a test environment prerequisite is genuinely missing, create the smallest enabling task
  first and state the evidence needed to consider it ready.
- Do not invent requirements, product acceptance criteria, technical constraints, test commands,
  or shared-resource conflicts. Point out an unsupported or contradictory upstream detail rather
  than silently resolving it.
- Keep the actual dependency DAG distinct from phase labels, task grouping, or suggested launch
  batches. Ansel schedules all ready independent tasks concurrently within runtime capacity and
  uses separate worktrees; tasks are serial only for a real edge or resource conflict.

## Owner input and output gate

- Context/version gaps and technical questions return to Ansel. A genuine product/business
  decision is returned as a concise, evidence-backed question set with useful answer options,
  trade-offs, consequences, and which work pauses versus continues. Never emit only “needs user
  input” or leave the user waiting without specific questions.
- Write/update only `.spectra/specs/<slug>/tasks.md` and its `.config.spectra` task-phase state
  as authorized. `complete` means authored, not approved.
- Return the exact path and content/commit hash, ordered task list, dependency graph and rationale,
  validation prerequisites/commands, assumptions or unresolved questions, and upstream artifact
  hashes/verdicts to Ansel. Ansel assigns Mira the exact version using
  `.apc/skills/mira-tasks-audit.md` and the `spectra-tasks` Skill as read-only reference.
- Do not self-approve, create/launch implementation tasks, or tell anyone to begin coding. Only
  Mira `APPROVED` for the exact task-plan hash allows Ansel to reconcile implementation issues
  and dispatch developers.
