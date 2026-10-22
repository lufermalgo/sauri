# sauri

Summan's internal commercial-meeting intelligence platform.

## What it does

sauri captures Google Meet sessions (audio + video), automatically transcribes them in Spanish
— the language spoken in the meetings — and links them to the team's commercial management.
It's an in-house solution built incrementally, module by module.

## Modules (roadmap)

| # | Module | Status |
|---|--------|--------|
| 1 | Meeting capture | ✅ MVP implemented |
| 2 | Transcription (ASR) | Pending |
| 3 | Speaker identification | Pending |
| 4 | Notes & intelligence | Pending |
| 5 | CRM integration (ClickUp) | Pending |
| 6 | Library & search | Pending |
| 7 | Commercial analytics | Pending |
| 8 | Administration | Pending |

## Tech stack

- **Backend**: Python / FastAPI / SQLAlchemy / PostgreSQL
- **Chrome extension**: TypeScript / MV3 / React (Vite + CRXJS)
- **Frontend web**: TypeScript / React (Vite)
- **Local ASR engine**: faster-whisper (own container)
- **Infrastructure**: Docker Compose (PostgreSQL, MinIO, RabbitMQ, ASR engine)

## Local development

### Requirements

- Docker Desktop (macOS)
- Node.js >= 20
- Python >= 3.11

### Start the backend

```bash
make up        # Start the full Docker stack
make build     # Rebuild + start
make down      # Stop everything
make logs      # View logs
make migrate   # Run DB migrations
```

### Native Mac GPU engine feasibility spike

This is an owner-authorized, local feasibility experiment on an Apple M3 Mac, not a production
configuration or rollout. Keep the API, worker, PostgreSQL, MinIO, and RabbitMQ in Docker; run
candidate engines on the host and configure their URLs with `ASR_LOCAL_URL` and
`DIARIZATION_LOCAL_URL` (the Compose defaults use `host.docker.internal`). The host processes must
implement the existing Sauri HTTP contracts (`POST /transcribe` and `POST /diarize`); this
repository does not provide native MLX, whisper.cpp, or MPS HTTP adapters. Compose configuration
alone therefore does not make native inference runnable or demonstrate API/worker integration.

Compare MLX `whisper-large-v3-turbo` with whisper.cpp `large-v3-turbo-q5_0` for ASR, and evaluate
pyannote 3.1 with PyTorch MPS for diarization. Reuse the existing shared caches: MLX and Hugging Face
models (including pyannote) under `~/.cache/huggingface`, and the whisper.cpp GGML turbo model under
`~/.apx/v2/models`. Download any genuinely missing model only once into its shared cache; never place
model-sized files in this repository or copy existing model files. A repository-local `models/`
directory is not a cache and must not be used for this experiment. Use only the same recording Fer
explicitly authorized for this experiment; do not expose tokens, model files, or recording data.
Record hardware, OS, runtime/library and model versions, clip duration, initialization/cold-start and
processing times, processing time per audio hour, observed transcript and speaker-label quality, and
whether inference actually ran on Metal/MPS without CPU fallback. Report installation footprint only
if it can be measured without downloading or replacing cached artifacts. Feasibility success means a
repeatable native accelerated run and complete evidence for both candidates; do not invent
speed/quality thresholds or infer production readiness. No Compose services are started by
documentation validation.

### Chrome extension

```bash
cd extension
npm install
npm run build
```

Then load `extension/dist/` as an unpacked extension at `chrome://extensions/` (developer mode).

### Frontend web

```bash
cd frontend
npm install
npm run dev
```

## Project structure

```
sauri/
├── backend/           # Python/FastAPI (API + workers)
├── extension/         # Chrome MV3 (meeting capture)
├── frontend/          # React SPA (meeting browsing)
├── packages/          # Shared types (@sauri/shared-types)
├── .spectra/specs/    # Module specs (Spectra)
├── docker-compose.yml # Full local stack
├── Makefile           # Development commands
└── AGENTS.md          # Project rules and workflow
```

## Development workflow

See [AGENTS.md](./AGENTS.md) for the full rules. In summary:

1. Each module has a spec in `.spectra/specs/` (requirements/bugfix → design → tasks)
2. Each atomic task → GitHub issue assigned to the module's milestone
3. Each issue → branch → PR → merge to main
4. GitHub milestones reflect roadmap progress

## Security

See [SECURITY.md](./SECURITY.md) for notes on TLS, encryption, and handling of personal data.
