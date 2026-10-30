# AGENTS.md

## Dialectical Rigor & Context Integrity Protocol

### 1. Anti-Sycophancy & Lexical Ban
- **Strict Lexical Ban:** Never open or frame a response with validation phrases such as "You're right," "Tienes razón," "Good point," "That makes sense," or "I agree."
- **Fallible User Premise:** Treat every user observation, suggestion, or correction as a potentially incomplete, biased, or locally optimized hypothesis—never as an absolute directive that automatically overrides prior context.

### 2. Full-Context Stress-Testing (Defend Against Recency Bias)
- **Systemic Audit Before Concession:** When the user introduces a new constraint, critique, or pivot, DO NOT immediately pivot to accommodate it. First, cross-examine the user's input against the entire session history, architectural decisions, business goals, and previously established constraints.
- **Explicit Trade-off Evaluation:** Before adopting any user suggestion, explicitly evaluate and state:
  1. **What it solves locally:** The immediate merit of the user's observation.
  2. **What it breaks globally:** Hidden regressions, technical debt, second-order risks, or contradictions with earlier decisions in the session.
- **Hold Your Ground:** If the user's observation is flawed, shortsighted, or inferior to the existing approach when viewed against the full context, reject the premise directly and defend the stronger position with technical/strategic evidence.

### 3. Qualified Integration (When the User IS Right)
- **Analytical Delta Only:** If rigorous evaluation proves the user's observation is genuinely valid, do not flatter the user. State * strictly why* the new variable changes the structural calculus, identify which prior assumption is now invalidated, and immediately map out the ripple effects across the rest of the system.

## Project overview and current code map

Sauri is Summan's internal commercial-meeting intelligence platform. This is a source-code map,
not a product-acceptance or release claim. The inventory below was checked against code at
`e3cce64` (`origin/main`, merge of PR #255) on 2026-10-16; refresh it when implementation changes.
The README roadmap is stale as an implementation-status source: it marks transcription and speaker
identification pending even though code and tests for both exist. Do not treat source presence or
tests as proof of product acceptance or a working deployment.

**The canonical folder structure is [`.spectra/PROJECT_STRUCTURE.md`](.spectra/PROJECT_STRUCTURE.md).**
It is the single authority for where code lives across the three product surfaces (`backend/`,
`frontend/`, `extension/`), the shared package (`packages/shared-types/`), the Compose stack and the
worktrees. Read it before creating, moving or deleting any directory, and before writing a
`design.md`. The "Layout and commands" section below is the short working summary; if the two ever
disagree, `PROJECT_STRUCTURE.md` wins and this file gets fixed in the same PR.

All code and domain identifiers use English. Actual transcript content remains in Spanish because
it represents meeting speech. UI language is feature-specific; do not infer a global language from
this rule. If an approved spec contains a `Domain_Term_Mapping`, follow it, but do not assume that
spec exists: this checkout currently has no `.spectra/specs/` or `PRODUCT_BASELINE.md`.

### Stack and runtime

- **Backend**: Python >=3.11, FastAPI, SQLAlchemy async, PostgreSQL, Alembic (`backend/`).
- **Chrome extension**: TypeScript, Manifest V3, React, Vite + CRXJS (`extension/`).
- **Web frontend**: TypeScript, React, Vite (`frontend/`).
- **Shared types**: `@sauri/shared-types` in `packages/shared-types`; current consumer is the web frontend.
- **ASR engine**: faster-whisper service in `backend/asr-engine/`.
- **Diarization engine**: pyannote service source in `backend/diar-engine/`, requiring a Hugging Face token for gated model access.
- **Docker Compose at this snapshot**: API, worker, PostgreSQL, MinIO, RabbitMQ, and ASR engine. It does **not** define a diarization-engine service; `DIARIZATION_LOCAL_URL` is required by the backend factory but is not configured in the Compose worker. Do not claim diarization is deployable through the checked-in Compose stack until that gap is resolved.
- The root npm workspaces are `extension`, `frontend`, and `packages/*`; Node >=20.

### Implemented source surfaces (presence only; validate runtime separately)

- **API wiring**: `backend/app/main.py` includes `/api/v1/auth`, `/api/v1/ingestion`, and
  `/api/v1/meetings` plus `/health`.
- **Meetings** (`backend/app/meetings/`): register/list/get/rename/delete meetings, request a
  meeting join, retrieve transcript and diarization, and pure meeting-state transition logic.
- **Ingestion** (`backend/app/ingestion/`): accept recording uploads, store objects, and enqueue
  processing.
- **Transcription** (`backend/app/transcription/`): ASR interface, local and cloud providers,
  provider factory, persistence, and asynchronous worker. The factory supports `local` and `cloud`.
- **Diarization** (`backend/app/diarization/`): engine interface, local/cloud provider classes,
  assignment/labeling, persistence, state logic, and worker. At this snapshot the factory only
  accepts the local provider despite the cloud class being present; runtime also lacks the Compose
  service/configuration noted above.
- **Retention** (`backend/app/retention/`): expiration policy/configuration and deletion worker.
- **Auth** (`backend/app/auth/`): login, password/token handling, current-user dependency,
  authorization, seed users, and access audit.
- **Infrastructure** (`backend/app/infra/`): database, S3-compatible object store, RabbitMQ queue,
  and SQLAlchemy models.
- **Extension** (`extension/src/`): Meet content script/background service worker, offscreen
  capture, IndexedDB recording persistence, retryable upload queue, Chrome side panel, options,
  and transcript detail UI with search/speaker/time helpers.
- **Web frontend** (`frontend/src/`): small React SPA with meeting registration, meeting list, and
  transcript view; it is not a full administrative/analytics product surface.
- **Contracts/tests**: shared meeting/recording/transcript types and backend/frontend/extension
  unit, property, integration, and extension E2E test sources exist. Test files are evidence of
  intended behavior only; do not report them passing unless the relevant command was run.

### Layout and commands

Three product surfaces, one shared package, one deployment definition. Full detail, including the
per-folder trees and the placement rules, is in
[`.spectra/PROJECT_STRUCTURE.md`](.spectra/PROJECT_STRUCTURE.md).

```text
sauri/
├── backend/          # Python ≥3.11 · FastAPI · SQLAlchemy async · Alembic · PostgreSQL
│   ├── app/          #   main.py, worker.py, auth/ meetings/ ingestion/ transcription/
│   │                 #   diarization/ retention/ infra/  (one folder per bounded module)
│   ├── tests/        #   mirrors app/: auth/ meetings/ ingestion/ … + integration/
│   ├── alembic/      #   versions/ (sequential migrations)
│   ├── asr-engine/   #   faster-whisper service (its own Dockerfile)
│   └── diar-engine/  #   pyannote service (its own Dockerfile, HF token gated)
├── frontend/         # TypeScript · React · Vite — small internal SPA
│   └── src/          #   App.tsx, api.ts (the only HTTP layer), components/
├── extension/        # TypeScript · React · Vite+CRXJS · Chrome Manifest V3
│   └── src/          #   core/ (pure logic, no DOM/Chrome) · panel/ · detail/ · options/
│                     #   background.ts · content.ts · offscreen.ts · upload-queue.ts · recording-db.ts
│   └── tests/e2e/    #   Playwright
├── packages/
│   └── shared-types/ # @sauri/shared-types — source-only TS contracts (consumer: frontend)
├── _tools/           # new-worktree.sh, remove-worktree.sh, check_english_only.py
├── .spectra/specs/<slug>/  # requirements.md|bugfix.md · design.md · tasks.md
├── docker-compose.yml      # project "sauri": api, worker, postgres, minio, rabbitmq, asr-engine
└── package.json            # npm workspaces root: extension, frontend, packages/*
```

The surfaces never import each other's source. They are coupled only through the HTTP API and, on the
TypeScript side, through `@sauri/shared-types`. `frontend/` and `extension/` are not Compose
services: the SPA is built and served separately, the extension runs inside Chrome and reaches the
API over HTTP. Data flow: extension → `/api/v1/ingestion` → MinIO → RabbitMQ → worker → asr-engine →
PostgreSQL → `/api/v1/meetings` transcript endpoints → frontend and the extension detail view.

Backend modules do **not** all follow one router/service/repository/schema template. `meetings` and
`ingestion` have those layers; `auth` is organized around router/dependencies/token/password/audit;
`transcription` and `diarization` use engine/factory/provider/repository/worker modules; `retention`
uses policy/configuration/worker. Shared adapters are in `backend/app/infra/`.

```bash
# Full local services; `make clean` removes volumes and local DB/object data
make up
make build
make logs
make migrate
make down

# Backend, from backend/
pip install -e ".[dev]"
pytest
pytest tests/meetings/test_state_machine_property.py
ruff check .
mypy .

# Extension or web frontend, from the corresponding package directory
npm run dev
npm run build
npm run typecheck
npm run test
# Extension only:
npm run test:e2e
```

From the repository root, `npm run typecheck` and `npm run test` fan out to npm workspaces.
To load the extension, build it from `extension/` and load `extension/dist/` as an unpacked
extension in Chrome. Confirm API/auth configuration for the target environment before testing.

### Data handling

Meeting audio, video, and transcripts can contain personal or confidential information. Read
[SECURITY.md](SECURITY.md) before changing capture, storage, retention, or access control. The
retention worker uses `RETENTION_DAYS`; verify auth and audit behavior in the target deployment
rather than assuming local defaults.

## 1. Agent Operating Principles

These rules govern how agents must behave before, during, and after any task.

### Token Efficiency — The Fundamental Principle

* **Read before writing**: inspect existing code before modifying. Never write blind.
* **Edit, don't rewrite**: targeted edits only. Full rewrites require explicit justification.
* **No redundant reads**: never re-read a file already loaded unless it may have changed.
* **Surgical reads**: only the file being edited, only the relevant lines. No project-wide scans.
* **Focused diffs**: touch only what the task requires. Zero side edits.
* **Lazy loading**: pull context just-in-time, never preemptively.
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
* Each agent's contract in `.apc/agents/` defines its steps and who follows it; work is handed on by reassigning the APX task card. The contract prevails over this file on coordination.
* Design, tasks and implementation use only the skills named on the card. Independent ready tasks run in parallel in separate worktrees; blocked tasks never stall unrelated ready ones.

### No-silent-stop status

Every turn ends as one of: `completed` with evidence; `in progress` with the next action and a verified active run; or `blocked` with what is blocked, evidence and attempts, next actor, whether the owner must act, and the exact condition that resumes work. `unknown` is not success and does not justify a blind retry. Do not promise background monitoring unless a verified mechanism is active.

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

## 4. Canonical Handoff

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

Enforcement is local (git hooks in `.githooks/`, `make setup-hooks`, and the Claude Code hook); GitHub branch protection is unavailable on this plan.

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

### Containers (Docker, CLI only)

* Compose project `sauri` is the one shared dev stack (`make up`, `docker compose -p sauri`). `sauri-fer-test` is the owner's test stack: never start, stop, change or remove it. Do not create any other long-lived Compose project.
* A container an agent needs for a check (for example PostgreSQL 16 for migration tests) is throwaway: name `sauri-qa-<pr-or-issue>-<service>`, host port 55000 or higher, created and removed (`docker rm -f` / `docker compose -p sauri-qa-<n> down -v`) by that agent before it hands the card on. Check leftovers with `docker ps -a --filter name=sauri-qa-`.
* Only touch containers, volumes and projects you created. Never `docker system prune`, `make clean` or kill a host process: the PostgreSQL on port 5432 belongs to the machine. If Docker does not answer, report it on the card; do not work around it.

### Git rules

* Stage specific files — never `git add .` blindly.
* Rebase before the first push — never merge. Once a branch is pushed or has an open PR, never rewrite it (no rebase, no force-push): if `main` moved and the PR conflicts, `git merge origin/main` into the branch, resolve, and push a normal commit. Conflicts only in progress rows of a shared `tasks.md` resolve by keeping every `Done` row from both sides. A PR conflict is never a reason to stop or hand the card back.
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
* At task completion, APX reviews every tracked modification and untracked file in the active worktree, assigns each a disposition (this PR, another PR, or pending with reason and next step), and reports the complete inventory; never silently omit a path.

### GitHub operations and failure recovery

Before publishing, check `pwd`, the toplevel, branch, `git status --short` and the full tracked/untracked inventory, and preserve pre-existing changes. A PR request is end-to-end (issue, worktree, scoped change, validation, named-file commit, rebase, push, PR). Never claim a PR before verifying URL, base `main`, head SHA, issue link, files, draft state and mergeability. `EPERM` on `.git/worktrees/<name>/FETCH_HEAD` is a local permission failure: preserve the checkout, report the exact command and error, do not retry or bypass it. Full procedure: skill `sauri-git-recovery`.

---

## 10. Directory Structure & Ownership

Authoritative trees and placement rules: [`.spectra/PROJECT_STRUCTURE.md`](.spectra/PROJECT_STRUCTURE.md).
This table is the ownership summary; it does not replace that document.

| Directory         | Purpose                                        | Rule                                                         |
| ----------------- | ----------------------------------------------- | ------------------------------------------------------------ |
| `backend/app/<module>/` | One bounded module: `auth`, `meetings`, `ingestion`, `transcription`, `diarization`, `retention` | New behavior goes in the module that owns it; create a new module folder only when a spec says so, and follow the shape of the closest existing module instead of inventing a template |
| `backend/app/infra/` | Shared adapters: database, models, object store, queue | The only place for cross-cutting infrastructure; models live in `models.py`, never inside a feature module |
| `backend/tests/<module>/` | Tests mirroring `backend/app/<module>/` | Every backend change ships tests here; a folder with tests but no matching `app/` module (e.g. `library`, `speaker_review`) means the module is not implemented yet — never infer implementation from tests |
| `backend/alembic/versions/` | Sequential migrations | Next sequential number; migration + model change in the same PR |
| `backend/asr-engine/`, `backend/diar-engine/` | Independent engine services with their own Dockerfiles | `asr-engine` is in Compose; `diar-engine` is **not**, so diarization is not deployable through the checked-in stack |
| `frontend/src/` | Internal React SPA | All HTTP calls go through `src/api.ts`; components must not call `fetch` directly. This is not the main user surface and not an admin/analytics product |
| `extension/src/core/` | Surface-independent logic and its colocated `*.test.ts` | No DOM, no Chrome APIs — pure and unit-testable. New extension behavior lands here first, then is wired into a surface |
| `extension/src/panel/`, `detail/`, `options/` | The three extension surfaces, each with its own `index.html` + `index.tsx` | UI adapters only; no business logic that belongs in `core/` |
| `extension/src/background.ts`, `content.ts`, `offscreen.ts`, `upload-queue.ts`, `recording-db.ts` | Chrome lifecycle: service worker, Meet content script, offscreen capture, retryable upload queue, IndexedDB persistence | Capture, storage and upload changes require reading `SECURITY.md` first |
| `extension/tests/e2e/` | Playwright E2E | Run with `npm run test:e2e` from `extension/` |
| `packages/shared-types/` | `@sauri/shared-types`, source-only TS contracts | Adding or changing a contract is a cross-surface change that belongs in a spec; current consumer is `frontend/` only, and the extension keeps its own types in `extension/src/core/types.ts` — do not duplicate a contract a third time |
| `.spectra/` | Feature/bugfix specs: requirements, design, tasks; plus `PROJECT_STRUCTURE.md` | Reserved for `.spectra/specs/` and this structure reference; create specs via `/spectra-req`, `/spectra-design`, `/spectra-tasks`, `/spectra-bugfix` |
| `.agents/skills/`, `.claude/skills/`, `.kiro/skills/` | Agent Skills exposed from the canonical library | Manage bindings with Skill-manager; do not copy skills into `.spectra/` |
| `.kiro/hooks/`    | Legacy Kiro IDE automation hooks                | Historical; unused by Claude Code, kept as-is                |
| `_tools/`         | Worktree scripts, English-only check, optional session state | `new-worktree.sh` / `remove-worktree.sh` are the only supported way to create and delete a worktree; use `SESSION_STATUS.md` only when persistent session state is explicitly enabled |
| `.worktrees/`     | Local per-issue checkouts                       | Scratch space, untracked layout; never author an artifact or edit `main` from the root checkout while a worktree is assigned to you |
| repository root   | Only the tracked top-level files (`AGENTS.md`, `SECURITY.md`, `README.md`, `PRODUCT_BASELINE.md`, `PRODUCT_DISCOVERY.md`, `DEVELOPMENT_STATUS.md`, `SPIKE_FINDINGS.md`, `Makefile`, `docker-compose.yml`, `package.json`, `package-lock.json`, `.env.example`) | Nothing new goes in the root without a spec decision; ad-hoc files (`*.html` dumps, `*.tsv` samples) are local leftovers — never commit or reference them |

### Design must state folder placement

Every `design.md` declares, per surface it touches: which folders it adds or modifies, where its
tests live, whether a migration is needed, and whether `docker-compose.yml` or
`packages/shared-types` must change. "Somewhere in the backend" is not a design decision, and Mira
audits the artifact against `.spectra/PROJECT_STRUCTURE.md` paths.

### Naming

All code, module, file and identifier names are in English; transcript content stays in Spanish
because it is meeting speech. Spanish module folders from earlier revisions (`reuniones`, `ingesta`,
`transcripcion`, `diarizacion`, `retencion`) are untracked `__pycache__` residue in local checkouts,
not modules — `alembic` version 007 renamed the schema to English. If a working tree shows one,
check `git ls-files` before reasoning about it, and never import from it.

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
## 13. Spec → GitHub Traceability

Each approved product module maps to a Spectra spec and a GitHub milestone:

| Spectra artifact | GitHub artifact |
|---|---|
| Spec slug | Milestone |
| Atomic task from `tasks.md` | Issue, label `task` |
| Property test task | Issue, labels `task`, `test`, `pbt` |
| Bug found during execution | Issue, label `bug` |

* Only after Mira approves the exact `tasks.md`, Zoya creates, for every required task, one issue in the milestone and one board card (one task = one issue = one card) and records `Issue #n · Card task_x` in `tasks.md`; the implementer adds the PR number when opening the PR after QA (and security) pass and closes the card. Tests are never optional and never labeled `optional`.
* Every approved spec artifact and every implemented issue ends in its own PR by its author; a security finding that needs a spec change or separate code gets its own `security` issue, card and PR. Local and remote must stay in step: push before hand-offs, rebase on `origin/main`, and fast-forward `main` and remove the worktree after a human merge.
* Each issue is implemented in its own worktree and PR (`Closes #id`); the milestone closes when all its issues are closed, no open `bug` blocks acceptance, property tests pass with ≥100 examples, and user-visible work has `PRODUCT_ACCEPTED`.
* Test tasks are required, sequenced before their implementation (`test (red)` → `implementation (green)`). If test infrastructure is missing, the first task sets it up; tests blocked by external limits are documented as blocked, not skipped.
