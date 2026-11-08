# AGENTS.md

## Critical workflow rules (single source: [docs/engineering/WORKFLOW.md](docs/engineering/WORKFLOW.md))
- Use one isolated branch and worktree per delivery unit; closely related tasks may share an issue and PR under WORKFLOW §9. Never work in the root checkout or on `main`.
- Ansel is the only agent who merges; no cap on open PRs; after merge Ansel removes the worktree and branch when safe (WORKFLOW §8).
- Technical questions go to Ansel with a recommended solution; choose the simplest option that fully satisfies approved requirements (WORKFLOW §3).
- Work moves by reassigning APX task cards with PACKET and HAND-OFF (WORKFLOW §6).
- Ansel coordinates and approves technical work within approved scope. Consult Fer for product, privacy, spending or security-policy changes; communicate briefly in nontechnical Spanish about user impact. Do not bypass permissions or assume authorization for deployment or other actions outside scope.
- Prioritize approved work that unblocks others or is close to completion. Do not create work merely to occupy agents. Escalate unresolved technical blockers to Teo through Ansel.
- Preserve independent spec review, applicable QA and security gates, product acceptance, and the owner's test environment. Check current PR status and the reviewed candidate before merging; do not repeat unrelated reviews.

## Evidence and context
Assess relevant evidence and risks, state material contradictions, and carry out authorized requests. Explain trade-offs when they matter; do not require a formal debate for routine changes.

## 1. Agent Operating Principles

These rules govern how agents must behave before, during, and after any task.

### Token Efficiency — The Fundamental Principle

* **Read before writing**: inspect existing code before modifying. Never write blind.
* **Edit, don't rewrite**: targeted edits only. Full rewrites require explicit justification.
* **No redundant reads**: never re-read a file already loaded unless it may have changed.
* **Focused reads**: read the context the task requires; broader scans are appropriate for audits, cross-cutting changes, or when needed to avoid missing dependencies.
* **Focused diffs**: touch only what the task requires. Zero side edits.
* **Lazy loading**: pull context just-in-time, never preemptively.
* **Specialist agents**: do not delegate trivial isolated edits merely to change one file.
  Required role-specific Spectra phases and independent reviews are valid exceptions even
  when their deliverable is a single artifact. Give each agent a scoped brief and validate it.
* **Parallelism**: after a task plan is approved, dispatch independent dependency-ready tasks
  concurrently in separate worktrees; serialize only real dependencies or shared-resource
  conflicts. A blocked task must not stall unrelated ready work.

### Engineering Rigor

* Think before writing. Understand impact area first. Find the correct, complete solution (WORKFLOW §3); among equally correct options, prefer the simpler design.
* No side effects beyond the task scope. No unrelated edits.
* Regression-safe. Clean separation of concerns. Low coupling.
* Naming that documents intent. No dead code. Consistency with existing patterns.
* Defensive only at system boundaries.
* Surface cost, security, or compliance implications in one line. Never bury them.
* Before presenting non-trivial work: ask "is there a more elegant way?"
* If the project uses Rust, the configured Rust validation command must pass before marking ready any PR that touches Rust. This is typically `cargo check`, but do not assume it blindly if the project defines another validation workflow.
* If the project uses TypeScript, the configured project typecheck command must pass before marking ready any PR that touches TypeScript. Do not assume raw `tsc --noEmit` unless the project defines it.

---

## Project context (load on demand)
The code map, stack, commands, directory ownership and anti-patterns live in the skill `sauri-project-context` (`.apc/skills/sauri-project-context.md`). APX agents load it with `load_skill` before touching code, tests or specs; other tools read that file. It is kept out of this file because this file reaches every model call of every agent.
