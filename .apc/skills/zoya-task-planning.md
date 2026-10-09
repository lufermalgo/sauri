# Zoya — Sauri task-planning contract

This project rubric governs how Zoya uses the generic `spectra-tasks` Skill in Sauri. Use
`spectra-tasks` for the Spectra document workflow and format; when its generic guidance
conflicts with this file, `AGENTS.md`, or the approved artifacts, follow the Sauri contract.
Do not copy or edit the canonical shared Skill.

## Entry gate and assignment packet

Do not plan implementation until Ansel supplies and verifies all of the following:

- Spec slug, requested planning scope, and exact target worktree and branch.
- Owner-approved `PRODUCT_BASELINE.md` and relevant durable decisions, when applicable.
- Approved requirements or bugfix path and Mira `APPROVED` verdict; Ansel supplies its
  already-recorded version reference (commit SHA, or one content digest if it is uncommitted).
- Matching approved design path and Mira `APPROVED` verdict, with its already-recorded version
  reference. These references identify the snapshots; they are not recurring validation tasks.
- Verified technical constraints, existing test/runtime commands and prerequisites, and
  real shared-resource conflicts or concurrency limits.

Loading this rubric and the `spectra-tasks` Skill is not a gate for unrelated work: Ansel/Zoya
may read them in parallel with input/context verification. They must be available before Zoya
authors `tasks.md`; this does not require serializing other dependency-ready tasks.

If an input is absent, contradictory, or unavailable, return the precise gap to Ansel once. Do
not poll, recompute hashes, or relaunch the same audit while waiting. Ansel resolves the source
snapshot once; if it cannot be recovered, record the concrete blocker, contain only dependent
work, and continue unrelated ready work. Do not ask the owner to repair an orchestration omission
or infer approval from `.config.spectra` being `complete`.

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
- Return the artifact path and one version reference (commit SHA, or a single content digest for
  an uncommitted artifact), ordered task list, dependency graph and rationale, validation
  prerequisites/commands, assumptions or unresolved questions, and upstream version references/
  verdicts to Ansel. Ansel passes this same snapshot reference to Mira using
  `.apc/skills/mira-tasks-audit.md` and the `spectra-tasks` Skill as read-only reference.
- Do not self-approve, create/launch implementation tasks, or tell anyone to begin coding. Only
  Mira `APPROVED` for the submitted task-plan snapshot allows Ansel to reconcile implementation
  issues and dispatch developers. Record and reuse that verdict; do not re-hash or re-audit an
  unchanged snapshot. If its contents actually change, send the changed artifact for one targeted
  audit within the bounded review cycle. A version mismatch Ansel cannot resolve in one recovery
  attempt is a documented blocker, not a reason to repeat the same validation loop.
