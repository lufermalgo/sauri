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
* **Platform capabilities**: use Claude Code's native tools — skills, hooks, worktrees — never
  do manually what the platform can do automatically.
* **Subagents**: use for exploration, research, or parallel independent work. Never for
  single-file edits. Instructions must be self-contained and scoped. Pass only relevant
  excerpts, never full files. Validate result; retry once with a sharper prompt if wrong;
  handle inline if it fails twice.

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

Features are built from specs, not from ad-hoc prompts. The workflow is:

```text
Idea → Spec (requirements + design + tasks) → Implementation → PR → main
```

### Spec-Driven Development (SDD) with Spectra

This project started in the Kiro IDE, whose spec methodology lived under
`.kiro/specs/[module-name]/`. Now that Claude Code is the primary driver, specs
live under **`.spectra/specs/[slug]/`** instead, authored via the `spectra-*`
Claude Code skills (`.spectra/skills/`, invoked as `/spectra-req`,
`/spectra-design`, `/spectra-tasks`, `/spectra-bugfix`). All pre-existing specs
were migrated from `.kiro/specs/` to `.spectra/specs/` in one pass — `.kiro/specs/`
no longer exists. `.kiro/hooks/` (Kiro IDE automation) is untouched and unrelated
to this workflow; it simply isn't used by Claude Code.

#### Spec location

All specs live in `.spectra/specs/[slug]/`, tracked via a `.config.spectra`
(`specId`, `specType`: `feature`|`bugfix`, `phases`: requirements/design/tasks
status). Each spec folder contains:

| File                          | Purpose                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| `requirements.md` (feature) or `bugfix.md` (bugfix) | What the feature must do, or the bug's current/expected/unchanged behavior |
| `design.md`                    | How it will be built — architecture, data flow, key decisions        |
| `tasks.md`                     | Ordered implementation tasks with status tracking                    |

#### How to create a spec with Spectra

1. `/spectra-req <idea>` (feature) or `/spectra-bugfix <description>` (bug) — writes
   `.spectra/specs/[slug]/requirements.md` or `bugfix.md` + `.config.spectra`.
2. `/spectra-design` — reads the pending spec, writes `design.md`.
3. `/spectra-tasks` — reads the approved design, writes `tasks.md`.
4. Work through `tasks.md` in order — one task = one atomic unit of work.

### Spec discipline rules

* **No feature implementation before the spec is validated.** Writing code to "figure out" the design is a token and time sink. Define behavior first.
* **Small exceptions are allowed when appropriate.** Small bugfixes, documentation changes, configuration changes, and explicit technical spikes may proceed without a full spec, but still require scoped validation.
* **One spec per feature/module.** Don't accumulate multiple features in one spec.
* **Tasks must be atomic.** Each task in `tasks.md` should be completable in one focused session without needing to re-read the whole spec.
* **Acceptance criteria before implementation.** Define what "done" looks like before writing a single line of code.
* **Keep specs current.** Update task status as work progresses. A stale spec misleads the next session.

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
* Test failure limit: 3 failed attempts → document the blocker in the task → surface to the human in plain language.
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
each spec/issue gets **its own git worktree**, not just its own branch, as a
sibling directory of the repo (`../sauri-worktrees/<branch-name>`):

```bash
# 1. Create an isolated worktree + branch, fresh off origin/main
_tools/new-worktree.sh feature/issue-{id}-{desc}
cd ../sauri-worktrees/feature-issue-{id}-{desc}   # path is printed by the script

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
| `.spectra/specs/` | Feature/bugfix specs: requirements, design, tasks | Created via `/spectra-req`, `/spectra-design`, `/spectra-tasks`, `/spectra-bugfix` |
| `.spectra/skills/` | Spectra skill definitions (SKILL.md + references) | Not project content — don't hand-edit unless changing the methodology itself |
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

Each module of the product roadmap maps 1:1 to a **Spectra spec** and a **GitHub milestone**:

```text
Spectra Spec (.spectra/specs/{slug}/)  ←→  GitHub Milestone
  requirements.md or bugfix.md              (defines acceptance criteria)
  design.md                                 (defines architecture)
  tasks.md                                  (defines atomic work items)
```

### Lifecycle of a module

1. **Plan (Spectra):** Create the spec → `/spectra-req` or `/spectra-bugfix` → `/spectra-design` → `/spectra-tasks`.
2. **Sync to GitHub:** For each atomic task in tasks.md, create a GitHub issue assigned to the corresponding milestone. Label with `task`. Optional tasks (tests marked `*`) get label `optional`.
3. **Execute:** For each issue, create a worktree + branch (`_tools/new-worktree.sh feature/issue-{id}-{desc}`, see §7), implement, open PR referencing `Closes #{id}`.
4. **Track:** The milestone progress in GitHub reflects the spec progress. When all required issues in a milestone are closed, the milestone is closed.
5. **Bugs:** Bugs discovered during execution are filed as issues with label `bug`, assigned to the relevant milestone.

### Mapping rules

| Spectra artifact             | GitHub artifact                              |
| ----------------------------- | -------------------------------------------- |
| Spec slug                    | Milestone title (numbered: "1. Captura...")   |
| Requirement (user story)     | Referenced in issue body for context          |
| Atomic task from tasks.md    | GitHub issue (label: `task`)                  |
| Bug found during execution   | GitHub issue (label: `bug`)                   |
| Property test task           | GitHub issue (labels: `task`, `test`, `pbt`)  |

### When to create issues

* **From milestone 2 onward:** every atomic task in tasks.md gets a GitHub issue at spec creation time (before implementation starts).
* **Milestone 1 (retroactive):** only bugs and pending items were filed as issues. Completed tasks are tracked in tasks.md only.

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

---
