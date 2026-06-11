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
* **Platform capabilities**: use Kiro's native tools — specs, hooks, steering files — never
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

### Spec-Driven Development (SDD) with Kiro

#### Spec location

All specs live in `.kiro/specs/[module-name]/`. Each spec folder contains:

| File              | Purpose                                                              |
| ----------------- | -------------------------------------------------------------------- |
| `requirements.md` | What the feature must do — user-facing behavior, acceptance criteria |
| `design.md`       | How it will be built — architecture, data flow, key decisions        |
| `tasks.md`        | Ordered implementation tasks with status tracking                    |

#### How to create a spec in Kiro

1. Open the Kiro Spec panel, or use the command palette → "New Spec".
2. Describe the feature in natural language — Kiro generates the initial spec.
3. Iterate on `requirements.md` until behavior is fully defined.
4. Review `design.md` — validate technical approach before any code is written.
5. Work through `tasks.md` in order — one task = one atomic unit of work.

### Spec discipline rules

* **No feature implementation before the spec is validated.** Writing code to "figure out" the design is a token and time sink. Define behavior first.
* **Small exceptions are allowed when appropriate.** Small bugfixes, documentation changes, configuration changes, and explicit technical spikes may proceed without a full spec, but still require scoped validation.
* **One spec per feature/module.** Don't accumulate multiple features in one spec.
* **Tasks must be atomic.** Each task in `tasks.md` should be completable in one focused session without needing to re-read the whole spec.
* **Acceptance criteria before implementation.** Define what "done" looks like before writing a single line of code.
* **Keep specs current.** Update task status as work progresses. A stale spec misleads the next session.

---

## 3. TDD & Quality Discipline

* Define acceptance tests before writing implementation code when the change affects application behavior.
* Never say "done" without confirming acceptance criteria pass.
* If tests can't run automatically, document exactly what to verify manually.
* Bug reports: diagnose root cause before touching code. Never patch symptoms.
* Test failure limit: 3 failed attempts → document the blocker in the task → surface to the human in plain language.
* If the project has no test framework yet, state that clearly and recommend the smallest useful future test strategy. Do not invent a test framework unless explicitly asked.
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

---

## 7. Git Workflow

```bash
# 1. Always start from latest main
git fetch origin main
git checkout -b feature/issue-{id}-{desc} origin/main

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
```

### Git rules

* Stage specific files — never `git add .` blindly.
* Rebase before push — never merge.
* Do not work directly on `main`.
* If `main` is broken, stop and fix it first.
* Clean up branches after merge. Delete remote branches once their PR is merged.

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

| Directory      | Purpose                                        | Rule                                                         |
| -------------- | ---------------------------------------------- | ------------------------------------------------------------ |
| `.kiro/specs/` | Feature specs: requirements, design, and tasks | Created and maintained by Kiro                               |
| `.kiro/hooks/` | Agent automation hooks                         | Created and maintained by Kiro                               |
| `_tools/`      | Optional session state and tooling notes       | Use only when persistent session state is explicitly enabled |

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

Each module of the product roadmap maps 1:1 to a **Kiro spec** and a **GitHub milestone**:

```text
Kiro Spec (.kiro/specs/{module}/)  ←→  GitHub Milestone
  requirements.md                       (defines acceptance criteria)
  design.md                             (defines architecture)
  tasks.md                              (defines atomic work items)
```

### Lifecycle of a module

1. **Plan (Kiro):** Create the spec → requirements.md → design.md → tasks.md.
2. **Sync to GitHub:** For each atomic task in tasks.md, create a GitHub issue assigned to the corresponding milestone. Label with `task`. Optional tasks (tests marked `*`) get label `optional`.
3. **Execute:** For each issue, create a branch (`feature/issue-{id}-{desc}`), implement, open PR referencing `Closes #{id}`.
4. **Track:** The milestone progress in GitHub reflects the spec progress. When all required issues in a milestone are closed, the milestone is closed.
5. **Bugs:** Bugs discovered during execution are filed as issues with label `bug`, assigned to the relevant milestone.

### Mapping rules

| Kiro artifact               | GitHub artifact                              |
| --------------------------- | -------------------------------------------- |
| Spec module name            | Milestone title (numbered: "1. Captura...")   |
| Requirement (user story)    | Referenced in issue body for context          |
| Atomic task from tasks.md   | GitHub issue (label: `task`)                  |
| Optional task (`*`)         | GitHub issue (labels: `task`, `optional`)     |
| Bug found during execution  | GitHub issue (label: `bug`)                   |
| Property test task          | GitHub issue (labels: `task`, `test`, `pbt`)  |

### When to create issues

* **From milestone 2 onward:** every atomic task in tasks.md gets a GitHub issue at spec creation time (before implementation starts).
* **Milestone 1 (retroactive):** only bugs and pending items were filed as issues. Completed tasks are tracked in tasks.md only.

### Milestone closure criteria

A milestone is **closed** when:
* All required (non-optional) task issues are closed.
* The spec's tasks.md reflects all tasks as completed.
* No open `bug` issues block the module's acceptance criteria.

Optional tasks (property tests, e2e tests) may remain open without blocking milestone closure, but should be completed before the next milestone starts.

---
