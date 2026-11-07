<!-- sauri-workflow v1.3 -->
# Sauri engineering workflow (v1.3)

Single source of truth for how work on Sauri is done, by agents or humans. `AGENTS.md` says what the project is and how its code is organized; this file says how work flows. `AGENTS.md` defines project-wide rules, this file defines shared process, and agent contracts define role-specific duties. Routine prompts trigger a pass and provide context; they do not expand authority. Escalate unresolved conflicts to Ansel.

**History.** v1.3 (2026-11-07, issue #726): no handoff file or skill (§6), wake-up step 9. v1.2 (2026-11-07, issue #726): approvals carry across a clean merge of `main` (§8). v1.1 (2026-11-07, issue #721): how the team talks to Fer (§3) and cards in review (§6). v1.0 (2026-11-07, issue #699): created by Fer's order. Sections 2 and 4–9 moved verbatim from `AGENTS.md` (old §2, §3, §4+§12, §5, §6–§8, §9, §13); §1, §3, §8 merge and cleanup, and §10 are new. Approved specs that cite old `AGENTS.md` section numbers are historical; map old §3→§4, §4→§6, §5→§5, §6–§8→§7, §9→§8, §12→§6, §13→§9.

## 1. Principles
1. **One task = one issue = one branch = one worktree = one PR.** Small and reversible.
2. **Fer decides product; specialists decide technique; Ansel decides when they disagree or when a technical question is open.** Owner decisions are limited to product direction, privacy and retention policy, spending, security policy, deployment and release.
3. **The simplest solution that fully satisfies the approved requirements.** See §3.
4. **Evidence over claims.** Report what was run and observed; anything not run is `UNVERIFIED`. A green check is not proof by itself.
5. **Protect work you did not create.** Never discard, overwrite or absorb someone else's uncommitted work.
6. **No silent blockers.** Every unresolved blocker has an owner and a resumption condition; Ansel resolves technical questions or consults Teo when needed.

## 2. Execution model and roles

Features are built from specs, not ad-hoc prompts: `Idea → Spec (requirements + design + tasks) → Implementation → PR → main`. Until the owner approves `PRODUCT_BASELINE.md`, legacy roadmaps, README claims and old specs are history, not target scope.

### Specs (Spectra)

Specs live in `.spectra/specs/[slug]/` with `.config.spectra` (`specType`: feature|bugfix; phase status). Files: `requirements.md` (or `bugfix.md`), `design.md`, `tasks.md`, `product-acceptance.md`. Skills `spectra-req`, `spectra-bugfix`, `spectra-design`, `spectra-tasks` author them; `.spectra/` is reserved for specs.

* No feature implementation before the spec is approved. Small bugfixes, docs/config changes and explicit spikes may skip a full spec but still need scoped validation.
* One spec per feature. Tasks are atomic. Acceptance criteria come before code. Keep task status current.
* `PRODUCT_DISCOVERY.md` is the cumulative record of product definition and is not a baseline or an authorization. Only scope the owner explicitly approves is promoted into `PRODUCT_BASELINE.md`; requirements derive from it.
* QA passing is technical evidence, not product acceptance. A user-visible feature is complete only when Cyrus records `PRODUCT_ACCEPTED` for the exact version in `product-acceptance.md` (infrastructure-only work may record `N/A` with a rationale).

### Roles and gates

| Agent | Role | Output |
|---|---|---|
| Ansel | Orchestrator | sequencing, cards, exceptions, owner messages |
| Cyrus | Product owner | discovery, baseline, product acceptance |
| Zoya | PM | requirements/bugfix, `tasks.md`, GitHub issues |
| Brisa | Architect | `design.md` |
| Mira | Spec auditor | verdict `APPROVED` / `REVISE` / `NEEDS USER INPUT` per artifact snapshot |
| Imre / Ilan | Developer | one issue per worktree, RED → GREEN → REFACTOR, PR |
| Nia | QA | `PASS` / `FAIL` / `BLOCKED` on an exact commit |
| Zev | Security | `NO_ACTIONABLE_FINDINGS` / `FINDINGS` / `BLOCKED` on an exact commit |

* Only Mira's `APPROVED` on the submitted snapshot advances a spec phase; the verdict stays valid while that artifact is unchanged. Audits iterate until approved and list every blocker at once.
* Each agent's contract in `.apc/agents/` defines its steps and who follows it; work is handed on by reassigning the APX task card. The contract defines role-specific hand-offs and must follow the shared process.
* Design, tasks and implementation use only the skills named on the card. Independent ready tasks run in parallel in separate worktrees; blocked tasks never stall unrelated ready ones.

### No-silent-stop status

Every turn ends as one of: `completed` with evidence; `in progress` with the next action and a verified active run; or `blocked` with what is blocked, evidence and attempts, next actor, whether the owner must act, and the exact condition that resumes work. `unknown` is not success and does not justify a blind retry. Do not promise background monitoring unless a verified mechanism is active.

## 3. Questions and decisions
- **Who decides.** Technical and sequencing questions are decided by Ansel after hearing the specialists who own the area. Product, privacy/retention, spending, security policy, deployment and release go to Fer through Ansel. A specialist never asks Fer a technical question.
- **How a question is raised.** On the card HAND-OFF (or to Ansel): the decision needed, the options, the evidence, the risks of each, and the asker's recommended option. A question without a recommendation is incomplete.
- **The simplest complete option.** Approve the option that is correct and complete for the approved requirement: it fixes the root cause, keeps tests real, stays maintainable and adds no hidden debt. A simpler or faster option is acceptable when it fully meets the approved requirements and preserves real validation. Rejected by rule: dummy implementations, stubs or placeholders, mocks in production code, skipped or weakened tests, scope narrowed so a check turns green, and "temporary" workarounds without their own issue.
- **When the right answer is unclear.** Ansel consults the relevant specialists when evidence is insufficient and chooses a solution that fully meets the approved requirement. If still blocked, consult Teo and continue independent work.
- **When the correct solution exceeds the approved scope.** It becomes a spec amendment through the normal SDD flow (§2), never a shortcut inside the current task.
- **Finding open questions.** On every wake-up Ansel scans `apx runs pending`, cards waiting on the owner or marked `NEEDS USER INPUT`, and hand-offs or comments that end in a question. Technical ones are decided in that turn and the decision is sent to the agent so the work continues. Product ones are batched into one message to Fer with a recommendation, and other work keeps moving. Permission prompts that only the owner can approve are listed for Fer, never bypassed.
- **Record.** Decision, reason and rejected options go on the card; durable decisions also go to project memory.
- **Talking to Fer.** Fer is not a developer. Anything addressed to him (`NEEDS USER INPUT`, a card waiting on the owner, an `@owner` comment, a question) is plain Spanish about the product, in at most four lines: what the person using Sauri will see or lose, the options in those terms, and the recommendation. No PR or issue numbers, hashes, commands, file names, or APX internals. If the question cannot be said that way, it is technical and the team decides it. Fer is asked to try or confirm something only when only he can (his own device, his own meeting): give the exact steps he can follow. Never ask him to diagnose.
- **What is Fer's.** What the product does for its users, privacy/retention/consent, spending, release. Not Fer's: accepting proposals, merging, test or CI failures, schema or migration choices, limits and bounds, tool or APX behavior. Those are decided by the team and Ansel from the product requirement.
- **Waiting on Fer has an owner.** A card is marked as waiting on Fer only with a question written as above. On every wake-up Ansel reviews each such card: a technical one is decided and unmarked; a product one is rewritten if it breaks these rules; an answered one is unmarked.

## 4. TDD and quality discipline

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

## 5. Validation and quality gates

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

## 6. Hand-offs and coordination
### Where state lives (no handoff file)
* There is no `handoff.md` and no `handoff` skill. APX already keeps what a session needs: the conversation history of each thread, the card (description with PACKET and HAND-OFF, comments, plan), the board, the agent memory injected every turn, and the routine's own system summary.
* A decision goes on the card it concerns. A decision that must outlive the card goes to project memory (`apx memory add project`), one short curated fact. Never write a status log into the repository.
* A session that starts reads its card and the system summary it was given; it does not read a status file.

### Coordination rules

These rules apply once the project has a repository, a default branch, and a PR workflow.

1. **`main` must always compile or pass the configured project validation workflow.**

2. **Never merge a PR to a feature branch and call it done.** PRs go to `main`.

3. **Before starting a task, fetch main and synchronize safely:**

   ```bash
   git fetch origin main
   # Rebase only before first push; for a published branch use a normal merge when needed.
   ```

4. **If `main` is broken, stop and fix it first.**

5. **Clean up branches after merge.** Delete remote branches once their PR is merged.

6. **Read `_tools/SESSION_STATUS.md` before every task only when session tracking is enabled.**

7. **Keep session state accurate when session tracking is enabled.** A stale session file is worse than no session file.

### Cards in review
A card moved to `review` always names a reviewer agent (`reviewer`, never the assignee). An empty reviewer means Fer in APX and shows as "Reviews: you", which is almost never right. A finished card, or one that only waits for a merge, is closed with `task_close` and a note instead of being parked in review. On every wake-up Ansel fixes any card in review without a reviewer: name the right agent, or close it.

## 7. Git: branches, worktrees, commits
### Branch naming

| Type         | Pattern                           | Example                          |
| ------------ | --------------------------------- | -------------------------------- |
| Feature      | `feature/issue-{id}-{short-desc}` | `feature/issue-12-silero-vad`    |
| Bugfix       | `bugfix/issue-{id}-{short-desc}`  | `bugfix/issue-34-paste-timing`   |
| Hotfix       | `hotfix/issue-{id}-{short-desc}`  | `hotfix/issue-56-security-patch` |
| Docs / chore | `feature/{short-desc}`            | `feature/consolidate-agents-md`  |

**NEVER work on `main` or any shared branch directly.**

Enforcement is local (git hooks in `.githooks/`, `make setup-hooks`, and the Claude Code hook); GitHub branch protection is unavailable on this plan.

### Git workflow: one worktree per spec or issue

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

# 3. Before the first push, rebase if needed; never rebase a published branch
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

#### Containers (Docker, CLI only)

* Compose project `sauri` is the one shared dev stack (`make up`, `docker compose -p sauri`). `sauri-fer-test` is the owner's test stack: never start, stop, change or remove it. Do not create any other long-lived Compose project.
* A container an agent needs for a check (for example PostgreSQL 16 for migration tests) is throwaway: name `sauri-qa-<pr-or-issue>-<service>`, host port 55000 or higher, created and removed (`docker rm -f` / `docker compose -p sauri-qa-<n> down -v`) by that agent before it hands the card on. Check leftovers with `docker ps -a --filter name=sauri-qa-`.
* Only touch containers, volumes and projects you created. Never `docker system prune`, `make clean` or kill a host process: the PostgreSQL on port 5432 belongs to the machine. If Docker does not answer, report it on the card; do not work around it.

#### Git rules

* Stage specific files — never `git add .` blindly.
* Rebase before the first push — never merge. Once a branch is pushed or has an open PR, never rewrite it (no rebase, no force-push): if `main` moved and the PR conflicts, `git merge origin/main` into the branch, resolve, and push a normal commit. Conflicts only in progress rows of a shared `tasks.md` resolve by keeping every `Done` row from both sides. A PR conflict is never a reason to stop or hand the card back.
* Do not work directly on `main` — use a worktree (see above), not a branch in the
  shared checkout.
* If `main` is broken, stop and fix it first.
* Clean up branches **and worktrees** after merge (`_tools/remove-worktree.sh`).

### Commit format: Conventional Commits

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

## 8. PRs, merge and cleanup
### PR rules

* Every change requires a PR — no direct pushes to `main`.
* PRs always target `main` directly.
* One issue = one branch = one PR → merge to `main`.
* Reference the issue: `Closes #id`.
* If the PR depends on another: `Depends on: #id`.
* If the project uses Rust, the configured Rust validation command must pass before opening a Rust PR.
* If the project uses TypeScript, the configured project typecheck command must pass before opening a TypeScript PR.
* Stage specific files — never `git add .` blindly.
* At task completion, APX reviews every tracked modification and untracked file in the active worktree, assigns each a disposition (this PR, another PR, or pending with reason and next step), and reports the complete inventory; never silently omit a path.

#### GitHub operations and failure recovery

Before publishing, check `pwd`, the toplevel, branch, `git status --short` and the full tracked/untracked inventory, and preserve pre-existing changes. A PR request is end-to-end (issue, worktree, scoped change, validation, named-file commit, rebase, push, PR). Never claim a PR before verifying URL, base `main`, head SHA, issue link, files, draft state and mergeability. `EPERM` on `.git/worktrees/<name>/FETCH_HEAD` is a local permission failure: preserve the checkout, report the exact command and error, do not retry or bypass it. Full procedure: skill `sauri-git-recovery`.

### Merge and cleanup
- **Ansel alone merges** in dependency order using `gh pr merge <n> --merge`. Before merging, check the current PR state, scope, conflicts and CI. Do not bypass protections.
- Spec PRs require Mira's approval of the submitted artifact; Nia is required only when the card explicitly requires QA. Implementation and other non-spec PRs require Nia PASS; Zev's security verdict is required when the card lists that gate. Product acceptance remains distinct from QA and is required for completion of user-visible features (§2).
- Reviews cover the changes actually reviewed. Revalidate material changes after review with the appropriate reviewer; an administrative-only change does not require repeating unrelated reviews. No mandatory SHA citation or separate SHA recheck is required.
- No cap on open PRs. Update another branch only when conflicts, a relevant dependency, or merge requirements make it necessary; do not update every PR after every merge. Never force-push or rebase published history.
- After merge, remove the worktree and branch when safe. Never remove uncommitted or unpublished work; record its disposition and owner. Update the primary checkout only if clean. Temporary worktree creators stop their servers and remove them when safe.

## 9. Spec → GitHub traceability

Each approved product module maps to a Spectra spec and a GitHub milestone:

| Spectra artifact | GitHub artifact |
|---|---|
| Spec slug | Milestone |
| Atomic task from `tasks.md` | Issue, label `task` |
| Property test task | Issue, labels `task`, `test`, `pbt` |
| Bug found during execution | Issue, label `bug` |

* Only after Mira approves the exact `tasks.md`, Zoya creates, for every required task, one issue in the milestone and one board card (one task = one issue = one card) and records `Issue #n · Card task_x` in `tasks.md`; the implementer adds the PR number when opening the PR after QA (and security) pass and closes the card. Tests are never optional and never labeled `optional`.
* Every approved spec artifact and every implemented issue ends in its own PR by its author; a security finding that needs a spec change or separate code gets its own `security` issue, card and PR. Publish reviewed candidates before hand-offs. Synchronize branches safely under §7. After merge, remove the worktree and branch only when safe; Ansel is the only agent who merges.
* Each issue is implemented in its own worktree and PR (`Closes #id`); the milestone closes when all its issues are closed, no open `bug` blocks acceptance, property tests pass with ≥100 examples, and user-visible work has `PRODUCT_ACCEPTED`.
* Test tasks are required, sequenced before their implementation (`test (red)` → `implementation (green)`). If test infrastructure is missing, the first task sets it up; tests blocked by external limits are documented as blocked, not skipped.

## 10. Orchestrator wake-up
The routine runs every 15 minutes. If another Ansel session is working, skip this pass; the current session and sessions waiting for input do not count.

Use the supplied state summary as a starting point and inspect current details when needed. Resolve technical questions from available evidence, consult Teo if blocked, and continue independent work while waiting. Advance existing approved tasks, prioritizing work that unblocks others, then work near completion, then recorded priority and waiting time. Assign actionable work to free specialists and verify it starts; do not invent work merely to occupy agents. Advance returned cards and proposals, assign reviewers where needed, merge ready PRs and clean worktrees when safe. Record decisions, owners and blockers on the relevant cards. Ask Fer only for decisions reserved in §3, in concise, nontechnical Spanish. If no action is needed, respond `SKIP`.
