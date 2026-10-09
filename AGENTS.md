# AGENTS.md

## 1. Agent Operating Principles

These rules govern how agents must behave before, during, and after any task.

### Token Efficiency — The Fundamental Principle

* **Read before writing**: inspect existing code before modifying. Never write blind.
* **Edit, don't rewrite**: targeted edits only. Full rewrites require explicit justification.
* **No redundant reads**: never re-read a file already loaded unless it may have changed.
* **Surgical reads**: only the file being edited, only the relevant lines. No project-wide scans.
* **Focused diffs**: touch only what the task requires. Zero side edits.
* **Lazy loading**: pull context just-in-time, never preemptively.
* **Runtime**: Codex CLI is the only execution runtime for Sauri agents. Launch work through
  APX with `runtime=codex`; do not switch to Claude Code, a direct APX engine, or another provider.
  Use the Codex/APX-native skills and worktree tools where available.
* **Specialist agents**: do not delegate trivial isolated edits merely to change one file.
  Required role-specific Spectra phases and independent reviews are valid exceptions even
  when their deliverable is a single artifact. Give each agent a scoped brief and validate it.
* **Parallelism**: after a task plan is approved, dispatch independent dependency-ready tasks
  concurrently in separate worktrees; serialize only real dependencies or shared-resource
  conflicts. A blocked task must not stall unrelated ready work.

### Engineering Rigor

* Think before writing. Understand impact area first. Find the simplest correct solution.
* No side effects beyond the task scope. No unrelated edits.
* Regression-safe. Clean separation of concerns. Low coupling.
* Naming that documents intent. No dead code. Consistency with existing patterns.
* Defensive only at system boundaries.
* Surface cost, security, or compliance implications in one line. Never bury them.
* Before presenting non-trivial work: ask "is there a more elegant way?"
* If the project uses Rust, the configured Rust validation command must pass before opening any PR that touches Rust. This is typically `cargo check`, but do not assume it blindly if the project defines another validation workflow.
* If the project uses TypeScript, the configured project typecheck command must pass before opening any PR that touches TypeScript. Do not assume raw `tsc --noEmit` unless the project defines it.

---

## 2. Project Execution Model

Features are built from specs, not from ad-hoc prompts. For the product reset, the user and Cyrus establish the approved target in `PRODUCT_BASELINE.md`; until that exists, legacy roadmaps and architecture are historical only. The workflow for approved product work is:

```text
Idea → Spec (requirements + design + tasks) → Implementation → PR → main
```

### Spec-Driven Development (SDD) with Spectra

This project started in the Kiro IDE, whose spec methodology lived under
`.kiro/specs/[module-name]/`. Specs now live under **`.spectra/specs/[slug]/`**.
The `/spectra-req`, `/spectra-design`, `/spectra-tasks`, and `/spectra-bugfix`
commands are provided by Agent Skills from the canonical personal library managed by
Skill-manager and exposed in each
host's native location: `.agents/skills/`, `.claude/skills/`, and `.kiro/skills/`.
`.spectra/` is reserved for specs; do not store or manage Agent Skills there.
All pre-existing specs were migrated from `.kiro/specs/` to `.spectra/specs/`
in one pass — `.kiro/specs/` no longer exists. `.kiro/hooks/` (Kiro IDE
automation) is untouched and unrelated to the spec workflow.

#### Spec location

All specs live in `.spectra/specs/[slug]/`, tracked via a `.config.spectra`
(`specId`, `specType`: `feature`|`bugfix`, `phases`: requirements/design/tasks
status). Each spec folder contains:

| File                          | Purpose                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| `requirements.md` (feature) or `bugfix.md` (bugfix) | What the feature must do, or the bug's current/expected/unchanged behavior |
| `design.md`                    | How it will be built — architecture, data flow, key decisions        |
| `tasks.md`                     | Dependency-aware implementation tasks with status tracking           |
| `product-acceptance.md`        | Cyrus's evidence-based acceptance for the exact tested version         |

### Product baseline and acceptance

* The user and Cyrus establish the approved product baseline in `PRODUCT_BASELINE.md` before
  new product requirements are authored. Until then, previous roadmaps, README product claims,
  specs, and technical architecture describe history/current code only—not approved target scope.
* For each user-visible feature, approved `requirements.md` contains the observable product
  acceptance criteria. After technical QA, Cyrus evaluates the exact candidate version against
  those frozen criteria and records scenarios, representative-user evidence, limitations, and
  one result (`PRODUCT_ACCEPTED`, `PRODUCT_NOT_ACCEPTED`, or `INSUFFICIENT_USER_EVIDENCE`) in
  `product-acceptance.md` in the same spec folder.
* QA passing is technical evidence, not product acceptance. Do not call a user-visible feature
  or its milestone complete until Cyrus records `PRODUCT_ACCEPTED` for that exact version.
  Infrastructure-only work may mark product acceptance `N/A` with a rationale.

#### How to create a spec with Spectra

1. `/spectra-req <idea>` (feature) or `/spectra-bugfix <description>` (bug) — writes
   `.spectra/specs/[slug]/requirements.md` or `bugfix.md` + `.config.spectra`.
2. `/spectra-design` — reads the pending spec, writes `design.md`.
3. `/spectra-tasks` — reads the approved design, writes `tasks.md`.
4. Work through the approved dependency graph in `tasks.md` — one task = one atomic unit of work.
   Independent ready tasks may run concurrently in separate worktrees; serialize only real dependencies or shared-resource conflicts.

### Spec discipline rules

* **No feature implementation before the spec is validated.** Writing code to "figure out" the design is a token and time sink. Define behavior first.
* **Small exceptions are allowed when appropriate.** Small bugfixes, documentation changes, configuration changes, and explicit technical spikes may proceed without a full spec, but still require scoped validation.
* **One spec per feature/module.** Don't accumulate multiple features in one spec.
* **Tasks must be atomic.** Each task in `tasks.md` should be completable in one focused session without needing to re-read the whole spec.
* **Acceptance criteria before implementation.** Define what "done" looks like before writing a single line of code.
* **Keep specs current.** Update task status as work progresses. A stale spec misleads the next session.

### Independent specification audits

* Mira (`spec-auditor`) independently audits one submitted artifact snapshot at a time. Ansel dispatches an explicit specialization (`requirements`, `design`, `tasks`, or `bugfix`), matching read-only rubric, artifact path and one version reference (commit SHA or a single content digest when uncommitted), worktree/branch, author/review round, approved upstream references, relevant owner decisions, technical constraints, and review scope. This reference identifies the snapshot; it is not a recurring hash-validation task. The corresponding Spectra authoring skill is a reference only; Mira must not write or regenerate artifacts.
* A requirements audit requires the owner-approved `PRODUCT_BASELINE.md` and relevant recorded decisions. A design audit requires approved requirements/bugfix, the baseline, and verified technical constraints. A tasks audit requires approved design and requirements/bugfix plus actual dependency/resource constraints. If required context is missing or contradictory, Mira reports the precise preflight gap once without a verdict; Ansel gets one source-recovery attempt. If the snapshot/context cannot be recovered, document the blocker, contain only dependent work, and continue unrelated ready work. Do not repeatedly recompute hashes, resubmit the same audit, or ask the owner to resolve an orchestration omission.
* A completed audit returns exactly one verdict: `APPROVED`, `REVISE`, or `NEEDS USER INPUT`. Only `APPROVED` advances the dependent phase. `NEEDS USER INPUT` is reserved for a consequential decision/action that truly belongs to the owner; Mira must include a ready-to-send, evidence-backed, specific question set (with useful options/trade-offs and impact), not a bare status. Ansel promptly presents it to the owner, identifies paused and continuing work, records the answer as a durable decision, and routes it back to Mira and the author. A technical uncertainty or correctable document defect is not `NEEDS USER INPUT`.
* A verdict applies to the submitted artifact snapshot. Reuse it while that artifact remains unchanged; unrelated repository edits do not invalidate it. Only an actual edit to the reviewed artifact requires a targeted new audit, within the bounded review cycle; changes to approved requirements may invalidate dependent design/task approvals. Do not trigger repeat reviews by recalculating an unchanged version reference. Non-blocking recommendations do not prevent phase advancement.

### Architecture design assignments

* Brisa is the software architect and always uses `spectra-design` to author `design.md` from the exact requirements/bugfix version Mira approved. Ansel selects one or more applicable architecture specializations from `.apc/skills/brisa-design-specialties.md` based only on approved scope and lists the exact Skills to activate in the handoff. Cross-surface work must activate every relevant surface specialty and `cross-surface-integration`.
* Every design handoff includes the approved product baseline and decisions, upstream artifact references/verdicts recorded once, verified technical evidence/constraints, worktree/branch, requested scope, output path, and available Skills. If required context or a Skill cannot be verified in the target runtime, resolve that preflight once with Ansel before design; do not guess or ask the user to repair orchestration.
* Existing repository architecture is evidence of current state, not the target design by default. Reuse it only when it meets approved requirements and constraints; document alternatives and trade-offs. Product behavior ambiguity goes to the requirements author through Ansel; a genuine owner-level decision goes to Ansel with evidence and specific questions for the owner. Brisa does not directly pause with a vague “user input needed.”
* Brisa may author `design.md` and mark the Spectra phase `complete` to mean authored only. Mira's `APPROVED` verdict for the submitted design snapshot is the sole gate to task planning; reuse the verdict while that design is unchanged. Brisa never creates implementation tasks or approves its own design.

### Developer execution and Skills

* Imre implements only the atomic issue/task assigned by Ansel from the approved task plan and design. Each assignment names the active specialization(s), exact Skills to activate, issue, worktree/branch, validation commands, and acceptance evidence. Select specializations from the approved scope—not from the legacy repository shape—and do not infer full-stack scope.
* Project Skill bindings are governed by Ansel through Skills Manager (`plan → link → audit`). Binding exposes a Skill to supported runtimes; Ansel's assignment separately activates the exact Skill(s) needed for that task. Brisa and Imre may use assigned Skills but must not alter bindings, agent metadata, or install/import Skills. They report a missing capability to Ansel once.
* For an absent library Skill, Ansel may discover candidates with `find-skills`, but external download/import requires the owner's selection of the exact source. Inspect in staging without executing, record provenance, then bind and audit. Do not turn missing tool context into a recurring user blocker.
* Imre follows the approved design's architecture boundaries, not legacy boundaries by default. Mandatory RED → GREEN → REFACTOR, issue-scoped worktree, commit, and PR workflow apply without needing a separate reminder.

### Task-plan authoring contract

* Zoya (`pm`) uses `spectra-tasks` together with `.apc/skills/zoya-task-planning.md`. The Sauri rubric and this file override conflicting generic Skill advice; use the shared Skill for its format/workflow only and never edit its canonical contents.
* Ansel supplies the exact spec slug, owner-approved baseline/decisions, approved requirements or bugfix path+verdict+already-recorded version reference, matching approved design path+verdict+version reference, verified technical/test-environment constraints, real shared-resource limits, target worktree/branch, scope, and output path. Record each version reference once; missing context gets one Ansel recovery attempt, not repeated hash checks or a question to the owner.
* Every correctness property has a required RED test task before its GREEN implementation task; tests are never optional. Each task has observable completion evidence and a real validation command/prerequisite. Do not invent requirements, test commands, or dependency edges.
* Task dependencies represent only actual prerequisites, mandatory test-before-code order, or verified shared-resource conflicts. Independent dependency-ready work stays parallelizable; grouping/phase labels do not imply serial execution. Ansel dispatches ready independent tasks concurrently within runtime capacity in separate worktrees.
* Zoya returns the task-plan path and one version reference, dependency graph/rationale, assumptions, constraints/commands, and upstream versions to Ansel. `complete` means authored only. Mira's `APPROVED` verdict for the submitted snapshot is required before Ansel creates runnable implementation issues or dispatches developers; reuse that verdict for the unchanged artifact. If a mismatch cannot be resolved in one recovery attempt, document the blocker instead of looping. Zoya does not approve or implement.
* If a true owner decision remains, Zoya gives Ansel a ready-to-send, evidence-backed set of specific questions with options, trade-offs, impact, and paused versus continuing work. Missing technical/orchestration context goes back to Ansel; never leave the owner with a bare “input needed” status.

### No-silent-stop status contract

* Every objective turn must end in one user-visible state: `completed` with evidence; `in progress` with the next action and verified active runtime/session when applicable; or `blocked` with an actionable explanation. Never end with only “blocked”, “waiting”, “input needed”, or a recorded APX status the owner cannot see.
* Before calling work blocked, Ansel performs any safe, authorized internal recovery and continues all independent ready work. If none remains or the objective cannot proceed, report in the same turn: what is blocked and its impact, evidence and attempts so far, next responsible actor/action, whether the owner must act (`yes/no`), and the exact event/condition that resumes work.
* If owner action is required, ask the smallest specific question set with useful options/trade-offs and impact in that same message. If no owner action is required, say so explicitly; name the external/runtime event or internal prerequisite and do not imply background monitoring or automatic resumption unless a verified mechanism is active.
* For a running or unknown APX job, state the verified session/task identity and next expected event/check. `unknown` is not success and does not authorize a blind retry. A progress message is not a completion report.

---

## 3. TDD & Quality Discipline

### RED → GREEN → REFACTOR (NON-NEGOTIABLE)

Every behavior change follows strict TDD. No exceptions:

1. **RED (write test first, verify it fails):**
   * Write the test (property-based, example, or integration) that encodes the acceptance criterion.
   * **Run the test.** It MUST fail. If it passes, the test is wrong or the behavior already exists — investigate before proceeding.
   * Record the failing output as evidence that the test correctly targets unimplemented behavior.

2. **GREEN (implement, verify test passes):**
   * Write the minimum implementation to make the failing test pass.
   * **Run the test again.** It MUST pass. If it doesn't, fix the implementation — not the test.
   * Do not move to the next task until the test is green.

3. **REFACTOR (clean up, verify test still passes):**
   * Improve the code (naming, structure, duplication) without changing behavior.
   * **Run the test again.** It MUST still pass. If it regresses, revert the refactor.

### Execution enforcement

* **A task is NOT complete unless its corresponding test has been executed and passes.**
* "Executed" means actually run via the project test runner (e.g. `pytest`), not just syntactically validated.
* If the test runner is unavailable (no venv, no DB, missing deps), the FIRST task in the plan MUST set it up. Implementation tasks CANNOT proceed until the test runner works.
* Static analysis (AST parse, diagnostics) is NOT a substitute for running the test.

### Additional quality rules

* Never say "done" without confirming acceptance criteria pass.
* If tests can't run automatically, document exactly what to verify manually.
* Bug reports: diagnose root cause before touching code. Never patch symptoms.
* Test failure limit: 3 failed attempts → document the blocker in that task and report it plainly; do not pause unrelated dependency-ready work. Ask the human only if the next step needs their decision or action.
* If the project has no test framework yet, state that clearly and recommend the smallest useful future test strategy. Do not invent a test framework unless explicitly asked.
* **No mocks in production code.** The application must be 100% real functionality. Mocks, stubs, and fakes are ONLY acceptable inside test files (`tests/`) to simulate external I/O (HTTP responses, message brokers, databases) when the real infrastructure is not available during test execution. Production code (`app/`, services, workers) must never contain mock objects, conditional test paths, or fake implementations. Every implementation must be the real, deployable version.
* Behavior changes require test consideration. Behavior changes include:

  * business logic
  * data transformation
  * validation rules
  * API behavior
  * UI interaction behavior
  * state management
  * permissions or access control
  * error handling
  * persistence
  * integrations
  * command behavior

---

## 4. Context, Memory & Session Hygiene

### Session Memory & State Management

Session state may live in `_tools/SESSION_STATUS.md` once the project requires persistent multi-session coordination.

Until the project structure is established, do not create or update this file unless explicitly instructed.

When session tracking is enabled, `_tools/SESSION_STATUS.md` becomes the single source of truth for what is currently in progress.

**Read it at the start of every session when it exists and session tracking is enabled.**

**Update it whenever session tracking is enabled and:**

* You start a new branch or issue
* You open a PR
* You finish a rebase
* You go idle

**Required fields when session tracking is enabled:**

* Current branch
* Status: `idle` | `in-progress` | `pr-open` | `awaiting-review` | `blocked`
* Files being touched
* Pending PR number, if any

**Why `_tools/` and not `.kiro/`?**

`_tools/SESSION_STATUS.md` is tracked in git and readable by any tool or agent.
It is the evolved replacement for the old `.kiro/status.md` multi-agent coordination
file, which is now deprecated when Kiro is the sole agent on this project.

### Session Hygiene

* **Cold start**: if `_tools/SESSION_STATUS.md` exists and session tracking is enabled, read it first. It tells you what was in progress and what the next step is.
* **Before ending a session**: if session tracking is enabled, update `_tools/SESSION_STATUS.md` with current branch, status, and next step. Never leave it stale.
* **Context budget**: when approaching context limits — summarize decisions, update session status if enabled, and tell the user to open a fresh session.
* **Hard rotation triggers** — open a new session immediately:

  * A single response would exceed 2K output tokens
  * A file to load exceeds 500 lines and only part is needed
  * More than 3 subagents ran in this session
  * The task requires loading 3+ large files simultaneously

---

### Canonical Handoff

* The `handoff` skill is the only workflow for creating or updating session handoff state.
* At session start, read `<registered-project-root>/handoff.md` if it exists and resume from
  `7 · Siguiente paso`; do not repeat items recorded under `6 · Qué ha fallado`.
* Before ending or restarting a session, invoke the `handoff` skill from the registered Sauri
  project root and update only `<registered-project-root>/handoff.md` using its seven fields.
* Sauri has exactly one canonical handoff. Never create a `handoff.md` inside a worktree,
  agent folder, or subproject; if an old duplicate is found, do not treat it as authoritative.

## 5. Validation & Quality Gates

Validation must use the project’s actual commands and conventions. Do not assume framework, language, folder structure, package manager, test runner, or build tool before inspecting the repository.

### General validation rules

* Before modifying code, inspect existing project structure and conventions.
* Do not invent file paths, imports, package APIs, scripts, components, functions, configuration names, route names, environment variables, or integration points.
* If creating a new file, check whether the project uses exports, registries, route definitions, dependency wiring, module indexes, configuration manifests, or documentation that must also be updated.
* Match the existing project style instead of introducing a new pattern.
* If the project structure is unclear, inspect nearby files before writing.
* After modifying code, validate the change using the most appropriate existing project mechanism.
* Prefer the narrowest relevant validation first:

  * affected test
  * typecheck/check
  * lint
  * build
  * framework-specific validation
* Do not invent commands.
* Do not filter command output in a way that hides failures.
* If validation fails, do not claim the task is complete. Either fix the failure or report the blocker.
* If no validation command exists yet, state that explicitly and perform the best static verification possible from the files changed.

### Language-specific validation

* If the project uses Rust, the configured Rust validation command must pass before opening any PR that touches Rust. This is typically `cargo check`, but the repository’s actual workflow takes precedence.
* If the project uses TypeScript, the configured project typecheck command must pass before opening any PR that touches TypeScript. Do not assume raw `tsc --noEmit` unless the project defines it.
* If the project uses another language or framework, inspect the repository’s scripts, documentation, configuration files, or CI workflow before choosing a validation command.

---

## 6. Branch Naming

| Type         | Pattern                           | Example                          |
| ------------ | --------------------------------- | -------------------------------- |
| Feature      | `feature/issue-{id}-{short-desc}` | `feature/issue-12-silero-vad`    |
| Bugfix       | `bugfix/issue-{id}-{short-desc}`  | `bugfix/issue-34-paste-timing`   |
| Hotfix       | `hotfix/issue-{id}-{short-desc}`  | `hotfix/issue-56-security-patch` |
| Docs / chore | `feature/{short-desc}`            | `feature/consolidate-agents-md`  |

**NEVER work on `main` or any shared branch directly.**

### Enforcement

This repo is private on the GitHub Free plan, so server-side branch protection /
rulesets are unavailable (they require GitHub Pro or a public repo). The rule above
is therefore enforced **locally, not by GitHub**, via two layers:

1. **Git hooks** (`.githooks/pre-commit`, `.githooks/pre-push`), wired through
   `core.hooksPath .githooks`. This applies regardless of which tool drives git
   (any Claude Code session, another agent, or a human) and to every worktree of
   this repo, since they all share the same `.git`. Auto-installed by `npm install`
   at the repo root (the `prepare` script); run `make setup-hooks` if you never run
   npm at the root (e.g. backend-only work).
2. **A Claude Code `PreToolUse` hook** (`.claude/settings.json` →
   `.claude/hooks/block-main-git.sh`) that blocks `git commit`/`git push` on `main`
   before the command even runs, inside any Claude Code session with this repo open.

Both are bypassable (`--no-verify`, or simply not having the hooks installed in a
given clone) — this is a guardrail against accidental slips, not a security boundary.
If the team later moves to GitHub Pro or makes the repo public, add real branch
protection on top; don't remove the local hooks, since they also cover worktrees.

---

## 7. Git Workflow — one worktree per spec/issue

Multiple sessions (Claude Code or otherwise) may work on this repo concurrently.
Branch isolation alone isn't enough for that — two sessions on the same branch
name in the same checkout still stomp on each other's index and working tree. So
each spec/issue gets **its own git worktree**, not just its own branch, inside
the registered project root at `.worktrees/<branch-name>`. This lets APX inspect
the active worktree without widening access to sibling projects:

```bash
# 1. Create an isolated worktree + branch, fresh off origin/main
_tools/new-worktree.sh feature/issue-{id}-{desc}
cd .worktrees/feature-issue-{id}-{desc}   # path is printed by the script

# 2. Implement, then commit
git add <specific files>
git commit -m "feat(scope): description

Closes #{id}"

# 3. Rebase before push — never merge
git fetch origin main
git rebase origin/main

# 4. Push and open PR → main
git push -u origin feature/issue-{id}-{desc}
gh pr create --title "feat: description" --body "Closes #{id}"

# 5. After the PR merges, clean up
cd ../..  # back to the main checkout
_tools/remove-worktree.sh feature/issue-{id}-{desc}
```

Claude Code's own background-session isolation (`EnterWorktree`, `--worktree`) uses
the same underlying mechanism and is configured in `.claude/settings.json`
(`worktree.symlinkDirectories` symlinks `node_modules`/`backend/.venv` into new
worktrees so they don't need a full reinstall each time).

### Git rules

* Stage specific files — never `git add .` blindly.
* Rebase before push — never merge.
* Do not work directly on `main` — use a worktree (see above), not a branch in the
  shared checkout.
* If `main` is broken, stop and fix it first.
* Clean up branches **and worktrees** after merge (`_tools/remove-worktree.sh`).

---

## 8. Commit Format — Conventional Commits

```text
<type>(<scope>): <description>

Closes #<issue-id>
```

Types:

* `feat`
* `fix`
* `refactor`
* `docs`
* `test`
* `chore`

---

## 9. PR Rules

* Every change requires a PR — no direct pushes to `main`.
* PRs always target `main` directly.
* One issue = one branch = one PR → merge to `main`.
* Reference the issue: `Closes #id`.
* If the PR depends on another: `Depends on: #id`.
* If the project uses Rust, the configured Rust validation command must pass before opening a Rust PR.
* If the project uses TypeScript, the configured project typecheck command must pass before opening a TypeScript PR.
* Stage specific files — never `git add .` blindly.

---

## 10. Directory Structure & Ownership

| Directory         | Purpose                                        | Rule                                                         |
| ----------------- | ----------------------------------------------- | ------------------------------------------------------------ |
| `.spectra/` | Feature/bugfix specs: requirements, design, tasks | Reserved for `.spectra/specs/`; create specs via `/spectra-req`, `/spectra-design`, `/spectra-tasks`, `/spectra-bugfix` |
| `.agents/skills/`, `.claude/skills/`, `.kiro/skills/` | Agent Skills exposed from the canonical library | Manage bindings with Skill-manager; do not copy skills into `.spectra/` |
| `.kiro/hooks/`    | Legacy Kiro IDE automation hooks                | Historical; unused by Claude Code, kept as-is                |
| `_tools/`         | Optional session state and tooling notes        | Use only when persistent session state is explicitly enabled |

---

## 11. Anti-Patterns

* **Coding without a spec** → undefined behavior, wasted tokens, rework.
* **Full file rewrites** when a targeted edit suffices → token waste, merge conflicts.
* **Patching symptoms** instead of diagnosing root cause → compounding bugs.
* **Skipping the configured validation command** before a PR → broken `main`.
* **Direct push to `main`** → blocked by branch protection, and wrong by design.
* **Commits without issue reference** → untraceable changes.
* **Starting new work while `main` is broken** → compounding problems.
* **Leaving `_tools/SESSION_STATUS.md` stale when session tracking is enabled** → next session starts blind.
* **Loading full files when only a section is needed** → context budget waste.
* **Preemptive context loading** → loads files that may never be needed.
* **Using subagents for single-file edits** → overhead without benefit.
* **Merging PRs into feature branches** instead of `main` → hidden divergence.
* **Inventing commands, paths, APIs, imports, or framework conventions** → false progress and broken implementation.
* **Filtering validation output to force success** → false confidence.
* **Creating project structure before it is needed** → premature architecture and avoidable maintenance.

---

## 12. Coordination Rules

These rules apply once the project has a repository, a default branch, and a PR workflow.

1. **`main` must always compile or pass the configured project validation workflow.**

2. **Never merge a PR to a feature branch and call it done.** PRs go to `main`.

3. **Before starting any task, sync with main:**

   ```bash
   git fetch origin main
   git rebase origin/main
   ```

4. **If `main` is broken, stop and fix it first.**

5. **Clean up branches after merge.** Delete remote branches once their PR is merged.

6. **Read `_tools/SESSION_STATUS.md` before every task only when session tracking is enabled.**

7. **Keep session state accurate when session tracking is enabled.** A stale session file is worse than no session file.

---

## 13. Spec → GitHub Traceability Workflow

Each approved product module maps 1:1 to a **Spectra spec** and a **GitHub milestone**. Do not revive legacy roadmap modules or milestones unless the approved `PRODUCT_BASELINE.md` adopts them:

```text
Spectra Spec (.spectra/specs/{slug}/)  ←→  GitHub Milestone
  requirements.md or bugfix.md              (defines acceptance criteria)
  design.md                                 (defines architecture)
  tasks.md                                  (defines atomic work items)
```

### Lifecycle of a module

1. **Plan (Spectra):** Create the spec → `/spectra-req` or `/spectra-bugfix` → `/spectra-design` → `/spectra-tasks`.
2. **Sync to GitHub:** Only after Mira approves the exact `tasks.md` version, create a GitHub issue assigned to the corresponding milestone for each atomic required task. Label with `task` and the relevant test labels. Tests are never optional and must not receive an `optional` label.
3. **Execute:** For each issue, create a worktree + branch (`_tools/new-worktree.sh feature/issue-{id}-{desc}`, see §7), implement, open PR referencing `Closes #{id}`.
4. **Track:** The milestone progress in GitHub reflects the spec progress. When all required issues in a milestone are closed, the milestone is closed.
5. **Bugs:** Bugs discovered during execution are filed as issues with label `bug`, assigned to the relevant milestone.

After the tasks plan is approved, Ansel schedules its dependency graph: launch ready, independent
tasks concurrently up to APX/runtime capacity, each in its own worktree. Start tasks serially only
when an explicit dependency or shared-resource constraint requires it. A blocked task does not stop
unrelated ready tasks.

### Mapping rules

| Spectra artifact             | GitHub artifact                              |
| ----------------------------- | -------------------------------------------- |
| Spec slug                    | Milestone title (numbered: "1. Captura...")   |
| Requirement (user story)     | Referenced in issue body for context          |
| Atomic task from tasks.md    | GitHub issue (label: `task`)                  |
| Bug found during execution   | GitHub issue (label: `bug`)                   |
| Property test task           | GitHub issue (labels: `task`, `test`, `pbt`)  |

### When to create issues

* For milestones created from the approved baseline, every atomic task in `tasks.md` gets a GitHub issue before implementation starts.
* The former “milestone 1 retroactive” convention is historical and does not govern new baseline work.

### TDD execution order (NON-NEGOTIABLE)

Test tasks are **NOT optional** in the execution plan. They follow strict TDD order:

1. Write the test (property, example, or integration) — it must FAIL (red).
2. Write the implementation — the test must PASS (green).
3. Refactor if needed — the test must still pass.

In `tasks.md`, test tasks are **never marked with `*` (optional)**. They are
regular required tasks sequenced BEFORE their corresponding implementation task
in the dependency graph. The task plan generator must produce pairs:
`test (red)` → `implementation (green)`.

If the test infrastructure is not yet available (no venv, no DB, etc.), the FIRST
task in any implementation plan must set it up. Tests that cannot run due to
external blockers (missing CI, hardware, etc.) are documented as blocked — not
skipped.

### Milestone closure criteria

A milestone is **closed** when:
* All task issues (including tests) are closed.
* The spec's tasks.md reflects all tasks as completed.
* No open `bug` issues block the module's acceptance criteria.
* All property tests pass with the configured minimum examples (≥100).
* For user-visible product work, Cyrus records `PRODUCT_ACCEPTED` in the spec's
  `product-acceptance.md` for the exact candidate version; technical QA alone is insufficient.

---
