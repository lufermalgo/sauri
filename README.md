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
- **Native audio engines (Mac)**: MLX Whisper and pyannote/MPS, outside Docker for Apple GPU acceleration
- **Infrastructure**: Docker Compose (built Nginx portal, API, worker, PostgreSQL, S3-compatible RustFS, RabbitMQ); local deployment candidate tracked in #818 (publication, merge and product acceptance are separate)

See [Architecture and specification map](docs/ARCHITECTURE.md) for the current deployment boundaries, evidence and remaining gaps. The roadmap above is historical, not delivery evidence or authorization for deferred features; [PRODUCT_BASELINE.md](PRODUCT_BASELINE.md) defines approved scope.

## Local development

### Requirements

- Docker Desktop (macOS)
- Node.js >= 20
- Python >= 3.11

### Start the local platform

See [Local deployment and isolated validation](docs/LOCAL_DEPLOYMENT.md) for required private variables, the built portal at `http://127.0.0.1:5173`, QA cleanup and evidence boundaries. `make clean` deletes data and is not a startup or validation step.

```bash
make up        # Start dependencies, verify bucket, migrate, then start API/worker/portal and check HTTP
make build     # Rebuild images, then run the same readiness sequence
make down      # Stop everything
make logs      # View logs
make migrate   # Run DB migrations manually
```

`make up` and `make build` report failure and exit nonzero if the database is not healthy,
the object-store bucket cannot be verified/created, or Alembic cannot reach `head`. The
bring-up preserves named volumes and their objects. A one-shot, root-owned helper uses only
`CAP_CHOWN` to repair ownership inside the `minio-data` volume to the pinned RustFS image's
verified runtime identity (`10001:10001`); RustFS itself continues running as its image-defined
non-root user. No production deployment behavior is implied.

### Local meeting summaries

The summaries worker requires `SUMMARIZATION_OLLAMA_URL` (HTTP base URL with port)
and `SUMMARIZATION_OLLAMA_MODEL` (installed Ollama model name) in its runtime environment.
Compose passes these variables through without defaults: missing/malformed values prevent
worker startup. Configure a route to the owner-selected local Ollama instance **from the
worker container**, then verify the endpoint and model there before claiming real generation.
A host-only `localhost` check does not establish container connectivity. Summarization has no
cloud provider or fallback; broker retries and terminal failure retain only request status,
not provider diagnostics. See `.env.example` for the variable names.

`SUMMARIZATION_TIMEOUT_SECONDS` is the finite, positive per-attempt generation budget
(default **900 seconds**, including HTTP setup and response wait). Non-streaming local
inference may take more than a minute before sending response headers; the HTTP read
budget follows this setting while connection setup remains limited to 10 seconds.
Empty, non-numeric, non-positive and non-finite values prevent worker startup. Expiry
uses the existing broker retry/terminal-failure path; it does not truncate the transcript
or change the model, prompt, template, or result schema. Keep this budget below the
broker's configured consumer acknowledgement timeout (RabbitMQ default: 1800 seconds),
allowing time for database work. Raising it is not a guarantee of model latency/quality.
This setting is read at worker startup. Do not recreate a shared worker while ASR or
diarization jobs are active: wait for the worker to drain and coordinate the update;
changing `.env` alone does not reconfigure a running process.

### Native Mac GPU engines

Fer confirmed the local deployment direction on 2026-11-12: keep the API, worker, PostgreSQL,
S3 storage and RabbitMQ in Docker; run audio engines on the Mac for Apple GPU acceleration.
This is not evidence of production readiness or a verified end-to-end rollout. Configure their
URLs with `ASR_LOCAL_URL` and `DIARIZATION_LOCAL_URL` (Compose defaults use
`host.docker.internal`). Native MLX and MPS HTTP adapters exist in this repository and implement
`POST /transcribe` and `POST /diarize`. Compose configuration alone does not demonstrate
native inference, GPU execution or API/worker integration.

Install the host-native engine dependencies with `make engines-install`, then start the local
ASR and diarization servers with `make engines-up`. The lifecycle command provisions missing engine
credentials under `~/.config/sauri/`; `make up` also provisions them before Compose starts. Both
paths use the same host files: `engine_token` and `recording_capability_key`. The files are created
outside the repository, preserved if already present, and restricted to mode `0600` (the containing
`~/.config/sauri` directory is mode `0700`). Compose mounts these files read-only into the worker,
while the host-native engines read the same files. Do not copy credentials into the repository or
logs. To restart the engines and worker after updating code, run `make engines-down`, `make
engines-up`, then `docker compose build worker && docker compose up -d worker`.

The host-native adapters are implemented in `backend/asr-engine/native_main.py` (MLX Whisper) and
`backend/diar-engine/native_main.py` (pyannote on MPS); both implement the existing HTTP contracts.
They are started on loopback by `make engines-up`, outside Compose. The deployment direction is
confirmed; verified native inference and production readiness remain separate acceptance checks. Reuse the existing shared caches: MLX and
Hugging Face models (including pyannote) under `~/.cache/huggingface`, and the whisper.cpp GGML turbo
model under `~/.apx/v2/models`. Download any genuinely missing model only once into its shared cache;
never place model-sized files in this repository or copy existing model files. A repository-local `models/`
directory is not a cache and must not be used for this experiment. Use synthetic audio for this
credential and integration validation. For a separate spike experiment, use only the same recording
Fer explicitly authorized; do not expose tokens, model files, or recording data.
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
