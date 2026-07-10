# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

sauri is Summan's internal commercial-meeting intelligence platform. It captures Google Meet
sessions (audio + video) via a Chrome extension, transcribes them in Spanish, and will
progressively add speaker diarization, notes/intelligence, CRM (ClickUp) integration, a
searchable library, and commercial analytics. It's built module by module — see the roadmap
table in [README.md](README.md).

Domain code, comments, and docstrings are written in **Spanish** (e.g. `Reunion`, `estado_proceso`,
`Motor_ASR`, `Proveedor_De_Transcripcion`) because this mirrors the ubiquitous language used with
the business. Match this convention in backend/domain code; the AGENTS.md workflow doc and this
file are in English.

## Stack

- **Backend**: Python 3.11 / FastAPI / SQLAlchemy (async) / PostgreSQL / Alembic
- **Chrome extension**: TypeScript / MV3 / React (Vite + CRXJS)
- **Frontend web**: TypeScript / React (Vite)
- **Shared types**: `packages/shared-types` (`@sauri/shared-types`), consumed by frontend/extension
- **Local ASR engine**: faster-whisper, own container (`backend/asr-engine`)
- **Local diarization engine**: pyannote.audio, own container (`backend/diar-engine`), requires `HF_TOKEN`
- **Infra**: Docker Compose — PostgreSQL, MinIO (S3-compatible), RabbitMQ, asr-engine, diar-engine

npm workspaces tie together `extension`, `frontend`, and `packages/*` (see root `package.json`).

## Commands

### Full stack (Docker Compose)

```bash
make up        # start all services
make build     # rebuild images + start
make down      # stop everything
make logs      # tail logs for all services
make migrate   # run Alembic migrations (docker compose exec api alembic upgrade head)
make clean     # stop and remove volumes (wipes local data)
```

### Backend (Python, run from `backend/`)

```bash
# venv setup (torch/pyannote.audio are heavy — installed via Dockerfile, not required locally
# unless working on diarization directly)
pip install -e ".[dev]"

pytest                              # full suite
pytest tests/test_repository.py     # single file
pytest tests/test_repository.py::test_name  # single test
pytest tests/diarizacion            # a module's tests
ruff check .                        # lint
mypy .                               # typecheck (strict mode is on)
```

Test config lives in `backend/pyproject.toml`: `asyncio_mode = "auto"`, hypothesis profile
`"sauri"` registered in `tests/conftest.py` with `max_examples=100` — property-based tests
must run at that minimum. DB tests use an in-memory async SQLite engine (see `conftest.py`
fixtures: `async_engine`, `session_factory`, `db_session`), not a real Postgres instance.

### Extension / Frontend (TypeScript, run from `extension/` or `frontend/`)

```bash
npm run dev         # vite dev server
npm run build       # production build
npm run typecheck   # tsc --noEmit
npm run test        # vitest run
npm run test:e2e    # playwright test (extension only, --if-present at root)
```

From the repo root, `npm run typecheck` / `npm run test` fan out across all workspaces.

To load the extension in Chrome: `cd extension && npm run build`, then load `extension/dist/`
as an unpacked extension at `chrome://extensions` (developer mode on). It targets the local
API at `http://localhost:8000`.

## Architecture

### Spec-driven development (Kiro)

Features are not built ad hoc. Each module has a spec under `.kiro/specs/{module-name}/`:
`requirements.md` (user-facing behavior/acceptance criteria) → `design.md` (architecture/data
flow) → `tasks.md` (atomic, ordered implementation tasks). Small bugfixes, docs, and config
changes may skip a full spec but still need scoped validation. Full workflow, branch naming,
commit format, and PR rules are documented in [AGENTS.md](AGENTS.md) — read it before doing
git/PR work in this repo, since it's more detailed than the summary below.

Key points from AGENTS.md worth internalizing:
- **TDD is non-negotiable**: red (failing test) → green (minimal implementation) → refactor,
  for every behavior change. A task isn't done until its test has actually been *executed* and
  passes — static analysis doesn't count.
- **No mocks in production code.** Mocks/stubs are only for test files simulating external I/O.
- **Never work directly on `main`, and give each spec/issue its own git worktree**
  (`_tools/new-worktree.sh feature/issue-{id}-{desc}`), not just its own branch — this repo is
  routinely worked on by multiple concurrent sessions, and a shared checkout means they stomp
  on each other's index. This is enforced locally via `.githooks/` (`core.hooksPath`, auto-wired
  by `npm install`'s `prepare` script) and a Claude Code `PreToolUse` hook in
  `.claude/settings.json`, since GitHub-side branch protection isn't available on this private
  repo under the Free plan. See AGENTS.md §6-7 for the full rationale and workflow.
- Branches: `feature|bugfix|hotfix/issue-{id}-{desc}`. Rebase before push, never merge main in.
  Never push directly to `main`.
- Commits: Conventional Commits (`feat|fix|refactor|docs|test|chore(scope): ...`), referencing
  `Closes #{id}`.
- Session state, when tracking is enabled, lives in `_tools/SESSION_STATUS.md` — check it at
  the start of a session if it exists, since it records in-progress work, known tech debt, and
  next priorities that aren't visible in the code.

### Backend module layout (`backend/app/`)

Each domain module (`ingesta`, `reuniones`, `transcripcion`, `diarizacion`, `retencion`, `auth`)
follows the same internal shape: `router.py` (FastAPI endpoints) → `service.py` (orchestration)
→ `repository.py` (DB access) → `schemas.py` (Pydantic I/O models). Shared infra (DB engine,
object store, message queue) lives in `app/infra/`.

**Provider/factory pattern for external engines**: both `transcripcion` and `diarizacion` follow
the same shape — a `factory.py` reads an env var (`ASR_PROVIDER`, analogous var for diarization)
and returns either a `*_local` provider (calls the self-hosted engine container over HTTP) or a
`*_nube` (cloud) provider, both implementing a common protocol (`MotorASR`, `MotorDiarizacion`).
This lets `reuniones`/`service.py` stay provider-agnostic. Follow this pattern for any new
pluggable external engine rather than branching on config inline.

**State machine**: `app/reuniones/state_machine.py` defines `aplicar_evento`, a pure function
(no DB/IO) computing valid `Reunion` state transitions (`en_cola → uniendose → grabando →
transcribiendo → completado/fallido`). Keep transition logic here pure and push side effects
(persisting the new state, writing `EstadoHistorial`) into the service layer.

**Async workers**: background processing (transcription, diarization, retention) runs as
separate worker processes (`app/worker.py`, `app/transcripcion/worker.py`,
`app/diarizacion/worker.py`, `app/retencion/worker.py`) consuming from RabbitMQ
(`app/infra/queue.py` / `queue_rabbitmq.py`), not inline in request handlers.

### Extension layout (`extension/src/`)

MV3 Chrome extension: `background.ts` (service worker), `content.ts` (injected into
`meet.google.com`), `offscreen.ts`/`offscreen.html` (offscreen document for tab audio capture,
required since MV3 service workers can't touch media APIs directly), `panel/` (extension
popup UI, React), `recording-db.ts` (IndexedDB persistence), `upload-queue.ts` (durable upload
queue with retry). `core/` and `detail/` hold newer domain/API/design-token modules feeding a
side-panel + transcript detail view (see the `chrome-side-panel` spec).

Test files follow a naming convention indicating intent: `*.exploration.test.ts` (exploratory/
characterization tests) vs `*.preservation.test.ts` (regression-lock tests for existing
behavior) — match this when adding tests in this package.

### Data classification

Audio, video, and transcripts are personal data under Colombian law (Ley 1581 de 2012).
Retention is enforced automatically per `RETENTION_DAYS` via the retention worker — see
[SECURITY.md](SECURITY.md) before changing anything related to storage, retention, or access
control (JWT auth, `es_comercial` claim, `RegistroDeAcceso` audit logging).
