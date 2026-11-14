Historical snapshot of 2026-10-16; see overview.md for the current architecture.

# Sauri — Canonical Project Structure

Status: reference artifact. Owner request 2026-10-16: "es muy importante que se entienda bien la
estructura del proyecto… estructura de carpetas, ya que tendremos backend, frontend y extensión de
Chrome… debe quedar claro para los agentes también en AGENTS.md".

Verified against `origin/main` @ `e3cce64` (merge of PR #255) on 2026-10-16 with
`git ls-tree -r --name-only origin/main` and direct directory reads. This is a source-code map:
presence of code is not proof of runtime behavior, product acceptance, or a working deployment.

## 1. The three product surfaces

Sauri ships as three surfaces plus shared packages and one deployment definition:

| Surface | Directory | Stack | Build/test entry |
| --- | --- | --- | --- |
| Backend API + async workers | `backend/` | Python ≥3.11, FastAPI, SQLAlchemy async, Alembic, PostgreSQL | `pytest`, `ruff check .`, `mypy .` from `backend/` |
| Chrome extension (Manifest V3) | `extension/` | TypeScript, React, Vite + CRXJS, Playwright E2E | `npm run build`, `npm run typecheck`, `npm run test`, `npm run test:e2e` from `extension/` |
| Web frontend (internal SPA) | `frontend/` | TypeScript, React, Vite | `npm run build`, `npm run typecheck`, `npm run test` from `frontend/` |
| Shared TS contracts | `packages/shared-types/` | TypeScript, published as `@sauri/shared-types` | `npm run typecheck` |
| Local deployment | `docker-compose.yml`, `Makefile` | Docker Compose project `sauri` | `make up`, `make build`, `make migrate`, `make down` |

The three surfaces never import each other's source. They are coupled only through the HTTP API and,
on the TypeScript side, through `@sauri/shared-types`.

## 2. Root layout (tracked files and directories)

```text
sauri/
├── AGENTS.md                  # rules every agent must follow (coordination, gates, git, validation)
├── SECURITY.md                # read before touching capture, storage, retention or access control
├── README.md                  # product overview; roadmap in it is stale as an implementation status source
├── docs/                      # product/, architecture/, operations/, design/, history/
├── Makefile                   # up / build / logs / migrate / down / clean
├── docker-compose.yml         # project name: sauri
├── package.json               # npm workspaces root: extension, frontend, packages/*
├── package-lock.json
├── backend/                   # Python API, workers, engines, migrations, tests
├── frontend/                  # React SPA (meeting registration, list, transcript)
├── extension/                 # Chrome MV3 extension (capture, panel, detail, options)
├── packages/shared-types/     # @sauri/shared-types, the TS contract package
├── _tools/                    # new-worktree.sh, remove-worktree.sh, check_english_only.py
├── .spectra/                  # specs (requirements/design/tasks or bugfix) — one folder per slug
├── .agents/ .claude/          # Agent Skill bindings exposed from the canonical library
├── .githooks/                 # core.hooksPath (set by npm run prepare)
└── .env.example .gitignore
```

`.worktrees/` exists locally (one checkout per issue, created by `_tools/new-worktree.sh`) and is not
part of the tracked layout. It must be treated as scratch space, never as a place to author artifacts.

## 3. backend/

```text
backend/
├── Dockerfile                 # single image used by both the api and worker Compose services
├── pyproject.toml             # deps + [dev] extra (pytest, ruff, mypy)
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/              # 001…007; 003/004/006 were Spanish-schema, 007 renamed to English
├── app/
│   ├── main.py                # FastAPI app: /api/v1/auth, /api/v1/ingestion, /api/v1/meetings, /health
│   ├── worker.py              # async worker entrypoint (`python -m app.worker`)
│   ├── auth/                  # router, dependencies, token, passwords, authorization, audit, seed
│   ├── meetings/              # router, service, repository, schemas, state_machine
│   ├── ingestion/             # router, service, repository, schemas (upload, store, enqueue)
│   ├── transcription/         # asr_engine, factory, local_provider, cloud_provider, repository, worker
│   ├── diarization/           # diarization_engine, factory, local/cloud provider, assignment, labeling,
│   │                          #   state, repository, worker
│   ├── retention/             # expiration, config, worker
│   └── infra/                 # database, models, object_store(+_s3), queue(+_rabbitmq)
├── asr-engine/                # faster-whisper service (Dockerfile, main.py)
├── diar-engine/               # pyannote service (Dockerfile, main.py, requirements.txt)
└── tests/
    ├── conftest.py
    ├── auth/ meetings/ ingestion/ transcription/ diarization/ retention/ infra/
    ├── diar_engine/           # tests for the diarization engine service
    ├── library/               # tests for Library work whose app module is not in main yet
    ├── speaker_review/        # tests for speaker-review work
    ├── integration/
    ├── test_migration.py test_queue.py test_check_english_only.py
```

Backend module shapes are deliberately not uniform; do not impose one template. `meetings` and
`ingestion` use router/service/repository/schemas; `auth` is organized around
router/dependencies/token/passwords/authorization/audit; `transcription` and `diarization` use
engine/factory/provider/repository/worker; `retention` uses expiration/config/worker. Cross-cutting
adapters live only in `app/infra/`.

Convention: a feature's tests live in `backend/tests/<module>/`, mirroring `backend/app/<module>/`.
Tests for work that has no app module yet (for example `library`, `speaker_review`) keep their own
folder and move under the module folder when the module lands.

Known gaps to state honestly, not to paper over:

- `backend/app/library/` does not exist on `main`, while `backend/tests/library/` does. Do not claim
  a Library module is implemented from the test folder alone.
- `docker-compose.yml` defines `api`, `worker`, `postgres`, `minio`, `rabbitmq`, `asr-engine` and no
  diarization-engine service. `DIARIZATION_LOCAL_URL` is required by the backend factory but is not
  configured in the Compose worker, so diarization is not deployable through the checked-in stack.
- The diarization factory accepts only the local provider even though a cloud provider class exists.

## 4. frontend/

```text
frontend/
├── index.html
├── package.json               # depends on "@sauri/shared-types": "*"
├── tsconfig.json
├── vite.config.ts
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── api.ts                 # the only place that talks HTTP to the backend
    ├── vite-env.d.ts
    └── components/
        ├── RegisterForm.tsx
        ├── MeetingList.tsx (+ .test.tsx)
        └── TranscriptView.tsx (+ .test.tsx)
```

This is a small internal SPA (register a meeting, list meetings, read a transcript). It is not an
administrative or analytics surface, and it is not the product the Chrome extension serves. Do not
describe it as the main user interface. All backend calls go through `src/api.ts`; components must not
call `fetch` directly. `frontend/dist/` is a build artifact and is gitignored.

## 5. extension/

```text
extension/
├── manifest.json              # Manifest V3
├── package.json
├── tsconfig.json
├── vite.config.ts             # Vite + CRXJS
├── playwright.config.ts
├── tests/e2e/                 # Playwright E2E (npm run test:e2e)
└── src/
    ├── background.ts          # service worker (+ exploration tests)
    ├── content.ts             # Meet content script (+ exploration/preservation tests)
    ├── offscreen.ts offscreen.html        # offscreen capture document
    ├── recording-db.ts        # IndexedDB recording persistence
    ├── upload-queue.ts        # retryable upload queue (+ property and preservation tests)
    ├── manifest.test.ts test-setup.ts
    ├── core/                  # surface-independent logic: api/ (client), design/ (tokens),
    │                          #   authLock, capture, detailUrl, interventions, notes, order,
    │                          #   search, speakerTime, speakers, time, types, view
    ├── panel/                 # Chrome side panel: SidePanelApp.tsx + components/
    │                          #   (AuthView, CaptureControls, NotesList, PanelHeader)
    ├── detail/                # transcript detail page: DetailApp, TranscriptPanel,
    │                          #   TranscriptSearch, SpeakingTimeView, SummarySpace
    └── options/               # OptionsApp.tsx
```

Rule that matters most here: `src/core/` holds pure logic with no DOM and no Chrome API calls, so it
is unit-testable in isolation; `src/panel/`, `src/detail/`, `src/options/`, `background.ts`,
`content.ts` and `offscreen.ts` are the surface adapters. New behavior goes into `core/` first and is
wired into a surface afterwards. Each surface folder owns its own `index.html` and `index.tsx`.
`extension/dist/` is a build artifact and is gitignored; load `extension/dist/` unpacked in Chrome to
test manually.

The extension does not import `@sauri/shared-types` today; it keeps its own types in
`src/core/types.ts`. Any contract that must match the backend or the frontend is a shared-types
candidate and should be raised as such rather than duplicated a third time.

## 6. packages/shared-types/

```text
packages/shared-types/
├── package.json               # name "@sauri/shared-types", main/types -> ./src/index.ts, private
└── src/index.ts               # Meeting, Transcript, SpeechTurn, ProcessState, MeetingOrigin, FailureCause
└── tsconfig.json
```

It is source-only (no build step): consumers resolve `src/index.ts` directly through the npm
workspace link. The only current consumer is `frontend/`. Adding a consumer is a contract change and
belongs in a spec, not in an ad-hoc edit.

## 7. .spectra/ — where design lives

```text
.spectra/specs/<slug>/
├── .config.spectra            # specId, specType (feature|bugfix), phase status
├── requirements.md            # feature specs (or bugfix.md for defects — never interchangeable)
├── design.md                  # architecture, data flow, folder placement, key decisions
└── tasks.md                   # atomic tasks -> one GitHub issue -> one board card -> one PR
```

Slugs on `main`: `extension-capture-preferences`, `meeting-review-playback`,
`meeting-summaries-templates`, `recording-library-metadata`, `recording-notes`,
`recording-speaker-review`.

`.spectra/` is reserved for specs. Agent Skills are never stored there; bindings live in `.agents/`
and `.claude/` and are managed with Skill-manager.

Every `design.md` must state, per surface it touches, exactly which folders the change adds or
modifies and where its tests live, using the paths in this document. "Somewhere in the backend" is
not a design decision. When a design needs a new module, it names the folder
(`backend/app/<module>/`), its shape (which of the existing templates it follows and why), its test
folder (`backend/tests/<module>/`), and whether the Compose stack or `packages/shared-types` must
change too.

## 8. Deployment and how the surfaces relate

`docker-compose.yml` (project `sauri`):

| Service | Source | Notes |
| --- | --- | --- |
| `api` | `backend/Dockerfile` | port 8000; depends on postgres, minio, rabbitmq |
| `worker` | `backend/Dockerfile`, `python -m app.worker` | transcription and retention workers |
| `postgres` | `postgres:16` | volume `pgdata` |
| `minio` | `rustfs/rustfs@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b` | volume `minio-data`, bucket `sauri-recordings` |
| `rabbitmq` | `rabbitmq:3-management` | queue broker |
| `asr-engine` | `backend/asr-engine/Dockerfile` | faster-whisper at `http://asr-engine:8001` |

All services sit on the `sauri-net` network. `frontend/` and `extension/` are not Compose services:
the SPA is built and served separately, and the extension runs inside Chrome and reaches the API over
HTTP. Recording data flows extension → `/api/v1/ingestion` → MinIO → RabbitMQ → worker →
ASR engine → PostgreSQL → `/api/v1/meetings` transcript endpoints → frontend and extension detail
view. Retention (`RETENTION_DAYS`) is enforced by the worker, not by the API.

Configuration comes from the environment: `.env.example` documents the variables, and the Compose
file defaults `ASR_PROVIDER=local`, `AUTH_DISABLED=true`, `RETENTION_DAYS=90`,
`JWT_SECRET=dev-secret-change-in-production`. Those defaults are for local development only; verify
auth, retention and audit behavior in the target environment instead of assuming them.

## 9. Where new code goes (placement rules)

| Change | Location |
| --- | --- |
| New API endpoint | `backend/app/<module>/router.py` (+ service/repository/schemas as that module is shaped) |
| New SQLAlchemy model | `backend/app/infra/models.py` |
| New migration | `backend/alembic/versions/` with the next sequential number |
| New async processing step | `backend/app/<module>/worker.py`, enqueued through `app/infra/queue.py` |
| New object storage or queue adapter | `backend/app/infra/` |
| Backend tests | `backend/tests/<module>/` |
| New extension logic | `extension/src/core/`, with a colocated `*.test.ts` |
| New extension UI | the owning surface folder: `src/panel/`, `src/detail/` or `src/options/` |
| Chrome lifecycle (events, capture, upload) | `background.ts`, `content.ts`, `offscreen.ts`, `upload-queue.ts`, `recording-db.ts` |
| Extension E2E | `extension/tests/e2e/` |
| New web UI | `frontend/src/components/`, HTTP only through `frontend/src/api.ts` |
| Contract shared by two TS surfaces | `packages/shared-types/src/index.ts` |
| Spec artifacts | `.spectra/specs/<slug>/` |
| Repo tooling | `_tools/` |

Nothing else goes in the repository root. The root holds only the tracked top-level files listed in
§2; ad-hoc scratch files (for example `action.html`, `page.html`, `off.html`, `live2.tsv` found in a
local checkout) are untracked local leftovers and must never be committed or referenced.

Naming: all code, module, file and identifier names are in English. Spanish folder names left over
from earlier revisions (`reuniones`, `ingesta`, `transcripcion`, `diarizacion`, `retencion`) are
untracked `__pycache__` residue in local checkouts, not modules; `alembic` version 007 renamed the
schema to English. If you see a Spanish module path in a working tree, delete the cache and re-check
against `git ls-files` before reasoning about it. Transcript content stays in Spanish because it is
meeting speech.

## 10. Worktrees

One issue = one worktree = one PR. Create it with `_tools/new-worktree.sh <branch>` (it branches from
`origin/main` into `.worktrees/<branch-with-dashes>` and seeds `.agents/skills`), and
remove it with `_tools/remove-worktree.sh` after a human merges the PR. A worktree has no Python
virtualenv of its own: run backend tests with the root checkout's interpreter,
`<root>/backend/.venv/bin/python -m pytest`, from the worktree directory.
