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
- **Infrastructure**: Docker Compose (PostgreSQL, MinIO, RabbitMQ, ASR and diarization engines)

## Local development

### Requirements

- Docker Desktop (macOS)
- Node.js >= 20
- Python >= 3.11

### Start the backend

The diarization engine needs a Hugging Face token. Store it outside the repository at
`~/.config/sauri/hf_token`, then load it into the host environment before starting Compose:

```bash
chmod 600 "$HOME/.config/sauri/hf_token"
export HF_TOKEN="$(cat "$HOME/.config/sauri/hf_token")"
```

Then use `make up` below. The token is read into the environment without printing it; do not put its value in `.env`,
`.env.example`, shell commands committed to the repository, or version control.

```bash
make up        # Start the full Docker stack
make build     # Rebuild + start
make down      # Stop everything
make logs      # View logs
make migrate   # Run DB migrations
```

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
