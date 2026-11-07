---
name: sauri-project-context
description: Shared product, architecture, stack, and validation context for development agents working on Sauri.
---

# Sauri project context

This is curated APX context migrated from `CLAUDE.md`. `AGENTS.md` remains the authoritative source for workflow, testing, Git, and contribution rules; `SECURITY.md` governs security-sensitive changes.

## Product and language

Sauri is a Summan platform concept whose target product baseline is being redefined by the user and Cyrus. The previous concept included Google Meet capture, transcription, speaker identification, ClickUp, a searchable library, and commercial analytics; treat those as historical scope, not current commitments or requirements, unless the owner explicitly adopts them in `PRODUCT_BASELINE.md`. The stack and architecture below describe the existing repository only; they are not the target architecture for the new baseline unless an approved spec chooses to reuse them. Treat actual meeting audio, video, transcripts, credentials, and customer details as sensitive. For tests, use synthetic fixtures, never real meeting data unless the owner explicitly authorizes it.

All code and domain identifiers are English. Actual transcript content remains Spanish because it reflects meeting speech. UI copy defaults to English unless a feature specification says otherwise. For canonical domain terminology and naming conventions, follow `AGENTS.md` rather than inventing translations.

## Stack

- Backend: Python 3.11, FastAPI, async SQLAlchemy, PostgreSQL, Alembic.
- Chrome extension: TypeScript, Manifest V3, React, Vite, CRXJS.
- Web frontend: TypeScript, React, Vite.
- Shared types: `packages/shared-types` (`@sauri/shared-types`).
- ASR: self-hosted faster-whisper service in `backend/asr-engine`.
- Diarization: pyannote.audio service in `backend/diar-engine`; requires `HF_TOKEN`.
- Local infrastructure: Docker Compose with PostgreSQL, MinIO, RabbitMQ, ASR and diarization services.

## Architecture patterns

- Backend modules use `router.py` → `service.py` → `repository.py` → `schemas.py`; shared infrastructure lives in `backend/app/infra/`.
- Pluggable ASR/diarization engines use a factory selected by configuration and a shared protocol. Keep domain services provider-agnostic.
- Meeting state transitions are pure functions in `backend/app/meetings/state_machine.py`; persistence and side effects belong in the service layer.
- Background transcription, diarization, and retention run in separate workers consuming RabbitMQ, not inline in request handlers.
- The MV3 extension uses a service worker, content script, offscreen document for media capture, React panel, IndexedDB persistence, and a durable upload queue. Follow the existing boundaries rather than bypassing them.

## Useful validation commands

- Backend, from `backend/`: `pytest`, `ruff check .`, `mypy .`.
- Frontend/extension: from each package, `npm run test`, `npm run typecheck`, `npm run build`; extension E2E uses `npm run test:e2e`.
- Root `npm run test` and `npm run typecheck` fan out across npm workspaces.
- Root `make up`, `make build`, `make down`, `make logs`, `make migrate` manage the Compose stack. `make clean` removes local volumes and data; do not run unless explicitly requested.

## Sensitive-data guardrail

Before changing storage, retention, authentication, or access control, read `SECURITY.md` and the relevant spec. Do not copy personal data, transcripts, secrets, tokens, or private runtime state into `.apc/`, Git, prompts, or test fixtures.

# Moved from AGENTS.md (2026-11-07, issue #726)

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

## Directory Structure & Ownership

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

## Anti-Patterns

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
