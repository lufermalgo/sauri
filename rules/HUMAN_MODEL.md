# Human model — Sauri

A map of the system for someone who will not read every file. Update it in the same pull request when a process,
module, port, folder or boundary changes. Names below are the ones in the code; search for them.

Sauri is a local-first meeting recorder for Apple-silicon Macs. A Chrome extension records a browser tab, the Mac app
transcribes it, finds who spoke and drafts a summary, and everything stays on the Mac unless the user connects an
external provider.

## 1. Processes that run

The installed app is one Electron process that starts and supervises the rest (`desktop/src/main/services.ts`, class
`Core`; each child is a `Supervisor` in `supervisor.ts`). Every port derives from the API's (`ports.ts`, `portPlan`).

| Process | Entry | Role | Port (installed app) | Lifetime |
|---|---|---|---|---|
| **desktop** | `desktop/src/main/main.ts` | Single instance. Setup, portal window, menu-bar icon, updater; starts and stops everything below. | — | While the app runs. Closing the window keeps services up; quitting asks first if meetings are processing. |
| **postgres** | runtime `pg/bin/postgres` | The database. No TCP: `listen_addresses=` empty, Unix socket `.s.PGSQL.5432` in the run folder, mode 0700. | none | Starts first; stopped with SIGINT (fast shutdown). |
| **api** | `backend/app/main.py` (`uvicorn app.main:app`) | FastAPI. Serves the portal (`app/portal/static.py`), ingestion, meetings, media, settings. | `127.0.0.1:41750` | Starts after migrations (`alembic upgrade head`). The portal opens once it answers `/health`. |
| **worker** | `backend/app/worker.py` (`python -m app.worker`) | Consumes queue jobs (`transcribe`, `diarize`, `summarize`), runs sweepers (orphans, stale requests, retention, thumbnails). | none | Starts last, after the engines, so it never sends a job to an engine that is not listening. |
| **asr-engine** | `backend/asr-engine/native_main.py` | Transcription: Parakeet on Core ML when installed and verified, else whisper.cpp on Metal. | `41751` | Behind the open portal; blocked (not faked) while its model files are missing. |
| **diar-engine** | `backend/diar-engine/native_main.py` | Speakers: Senko on Core ML. | `41752` | Blocked until the downloadable speaker component is installed. |
| **llm-engine** | `backend/llm-engine/native_main.py` | Authenticated chat gateway for summaries. | `41753` | Always up; it starts `llama-server` on demand. |
| **llama-server** | runtime `bin/llama-server` | llama.cpp inference, child of llm-engine. | `41754` | Lazy; released after 120 s idle (5 s on low memory). |
| **host-engine** | `backend/host-engine/native_main.py` | Host administration: model installs, components, provider secrets, engine status, ChatGPT sign-in. | `41755` | Behind the open portal. Every route needs the management token. |

`SAURI_API_PORT` moves the whole block (API, +1 … +5); `SAURI_DESKTOP_HOME` swaps the home folder. Both exist to
isolate test runs. Logs go to `~/Library/Logs/Sauri/<name>.log` (`postgres`, `api`, `worker`, `asr-engine`, …).

Other processes:

| Process | Entry | Role | Lifetime |
|---|---|---|---|
| **extension** | `extension/src/background.ts`, `offscreen.ts`, `panel/` | MV3 service worker, offscreen recorder, side panel. Records a tab and uploads it to the app. | Chrome's. |
| **portal** | `frontend/` (React, Vite) | The app's UI, built with `VITE_API_BASE_URL=` empty and served same-origin by the API. | Per window or tab. |
| **Docker dev stack** (retiring) | `docker-compose.yml`, `make up` | API `127.0.0.1:8000`, portal `:5173`, PostgreSQL `:5432`, MinIO `:9000/9001`, RabbitMQ `:5672/15672`. | Until retired. |
| **native dev engines** | `scripts/engines/native-engines.sh`, `make engines-up` | The same engines for the Docker stack: ASR `8001`, diar `8002`, LLM `8003`, llama `8004`, host `8005`. | Until stopped. |

## 2. Where data lives

| What | Installed app | Development (`npm run desktop:dev`, `SAURI_DEV=1`) |
|---|---|---|
| User folders (chosen in setup) | `~/Sauri/Recordings`, `~/Sauri/Database`, `~/Sauri/Models` by default | `~/Sauri-dev/…` |
| Database cluster | `<Database>/pgdata`; update backups in `<Database>/backups/` | same, under `Sauri-dev` |
| App support | `~/Library/Application Support/Sauri/` | `~/Library/Application Support/Sauri-dev/` |
| Logs | `~/Library/Logs/Sauri/` | `~/Library/Logs/Sauri-dev/` |
| Runtime (Python, PostgreSQL, ffmpeg, whisper.cpp, llama.cpp) | inside `Sauri.app/Contents/Resources/runtime` | `~/Library/Caches/sauri-runtime-build/runtime-current` (`SAURI_RUNTIME_DIR`) |

Inside app support (`desktop/src/main/paths.ts`, `appPaths`):

| Path | Holds |
|---|---|
| `config.json` | Folders, local user id, setup step, language, `launchAtLogin` (off by default), `autoUpdate` (on). |
| `secrets/` (0700, files 0600) | `local_token`, `engine_token`, `management_token`, `recording_capability_key`, `database_password`; also the `extension_paired` marker and an optional `hf_token`. Created once, never logged. |
| `run/` | PostgreSQL socket, pid files, engine state. |
| `engines/` | ASR provenance, Parakeet home, engine virtual environments. |
| `components/` | Downloaded components (today: `diar`, the speaker runtime). |
| `updates/` | Downloaded, verified app versions waiting to be applied. |
| `cache/`, `electron/` | Python bytecode cache; Electron's own user data. |

Each user folder carries a `.sauri-folder` marker (`installId`, `kind`). The core refuses to start on a folder that
is missing, unmarked or marked by another installation. Provider keys live in the macOS Keychain (service `sauri`),
with a private-file fallback (`backend/engine-common/sauri_engine_common/secrets.py`). The extension keeps its token
in `chrome.storage.local` and recordings waiting to upload in IndexedDB (`extension/src/recording-db.ts`).

The Docker/native dev setup uses other places: tokens in `~/.config/sauri/`, engine environments in
`~/.local/share/sauri/native-engines/`, engine pids and logs in `~/.local/state/sauri/native-engines/`.

## 3. One recording, end to end

```
Chrome tab ──tabCapture──▶ offscreen recorder ──▶ IndexedDB (kept until the upload succeeds)
   │ GET /health on localhost:41750, then :8000 (must answer service: "sauri")
   ▼ POST /api/v1/ingestion/upload   (multipart: audio, optional video, data JSON; Bearer local token)
api ── checks size and container, writes files to Recordings, meeting → transcribing
   │ publish "transcribe"            (queue in PostgreSQL: QUEUE_KIND=postgres)
   ▼
worker ──▶ asr-engine :41751  (engine token + recording capability; engine reads the file from Recordings)
   │ words and segments saved; publish "diarize"
   ▼
worker ──▶ diar-engine :41752  (Senko) ── speakers, words attributed to speakers
   │ summary request written to an outbox, delivered as "summarize"
   ▼
worker ──▶ llm-engine :41753/v1 ──▶ llama-server :41754 ── draft summary saved
   ▼
portal ── reads the meeting; audio and video come through /api/v1/media with short-lived signed tokens
```

A `transcribe` or `summarize` job that fails for good is moved to `transcribe.failed` or `summarize.failed`. Sweepers in the worker recover work a crash or restart
left without an owner. Meeting states are in `backend/app/meetings/state_machine.py`.

## 4. Pairing the extension with the app

1. The extension finds the app by probing `/health` (`extension/src/core/backend.ts`). Port 41750 first; 8000 stays a
   fallback for the Docker stack and older apps.
2. It calls `POST /api/v1/local/pair` (`backend/app/local/router.py`). The API answers only when the request's
   `Origin` is in `SAURI_EXTENSION_ORIGINS`, which the desktop app builds from `ALLOWED_EXTENSION_IDS` in
   `desktop/src/main/services.ts`. Any other copy gets `403 extension_not_allowed`.
3. The answer is the local token. The extension stores it and sends it as `Authorization: Bearer …`; the API writes
   the `extension_paired` marker, and the welcome page sees it in `/api/v1/local/status`.
4. The portal gets the same token as an `HttpOnly`, `SameSite=Strict` cookie (`sauri_local`) from its own origin.

No account, email or password is involved. A new extension build with a new id must be added to the allow-list.

## 5. First run and model install

- **Phase A, in the app** (`desktop/src/main/setup.ts`): hardware check against `runtime-manifest.json` and
  `scripts/engines/model-catalog.json` (Apple silicon and the minimum macOS block setup; low memory or disk only
  warn), the user's name, the three folders,
  then `initdb`, the `sauri` database, migrations and the local user (`python -m app.local.bootstrap`).
- **Phase B, in the portal** at `/bienvenida` (`frontend/src/components/welcome/WelcomeView.tsx`): installs the
  recommended models for this Mac without asking, then waits for the extension to pair, then marks setup done.
- Installs go portal → API (`/api/v1/engines/local/…`) → host-engine (`host-engine/local_models.py`). URLs are built
  only from catalog fields (repository, pinned revision, file) on Hugging Face hosts. Each download is size-capped,
  resumable (`.part`), and kept only when its SHA-256 equals the catalog value.
- The speaker runtime is a component from a GitHub Release of `lufermalgo/sauri` (`diar-runtime` in the catalog),
  checked by archive `sha256` and unpacked `tree_sha256`.
- Setup state is saved after each step, so an interrupted setup resumes where it stopped.

## 6. Updates

`desktop/src/main/updater.ts`, `releases.ts`, `update-menu.ts`. Off in development.

- **Check**: every 6 hours (first one 90 s after start; a settings switch turns it off) and from the menu. Reads
  `https://api.github.com/repos/lufermalgo/sauri/releases?per_page=20` and picks the newest published `x.y.z` (leading
  `v` allowed) above the current one that carries `Sauri-<v>-mac-arm64.zip` and its `.sha256`. Drafts, pre-releases
  and other tags (`diar-…`) are skipped.
- **Stage**: download with a size cap and resumable `.part`, check against the `.sha256`, unpack with `ditto` into
  `updates/<version>/`, confirm the version in `Info.plist`.
- **Apply**: only when nothing is processing. Stop services, copy `pgdata` to `<Database>/backups/`, run the new
  version's migrations, swap `Sauri.app`, relaunch. On any failure the copy is restored and the old app stays.
- **Allow-list** (`allowedUrl`): every request and every redirect hop must be HTTPS to `api.github.com` (the Releases
  API of the repository), `github.com/lufermalgo/sauri/releases/download/…`, or `release-assets.githubusercontent.com`.
  No cookies, tokens or user data are sent. `SAURI_RELEASES_REPO` overrides the repository; an invalid value turns
  updates and component downloads off.
- **Components** follow the same allow-list from the host-engine and reach users through the catalog that ships
  inside each app version.

## 7. External providers

Off by default: every process (`transcription`, `diarization`, `summary`) runs on the local engines. The user can link
a provider in Settings; the kinds are listed in `backend/app/engines/capability_matrix.py` (OpenAI-compatible APIs,
local apps such as Ollama or LM Studio, Deepgram, AssemblyAI, a ChatGPT plan sign-in, and others).

- Nothing is sent until the user picks a provider for a process and accepts a consent; the gateways check the consent
  again before any call (`asr-engine/asr_external.py`, `diar-engine/diar_external.py`).
- What leaves the Mac is what that process needs: the audio (compressed, maybe split) for transcription or speakers,
  the transcript text for a summary. Only to the provider's own origin, HTTPS unless it is a loopback local app.
- Keys are read by host processes only, from the secret store, after the target origin matches the key. They are
  never returned, logged or stored in PostgreSQL. The ChatGPT plan uses a device-code sign-in with OpenAI.
- Removing a provider sends its processes back to the local engine and deletes its consents and stored key.

## 8. Boundaries and invariants

- **Loopback only.** Every service binds `127.0.0.1`; PostgreSQL has no TCP port at all. The API answers only `Host:
  localhost:<port>` or `127.0.0.1:<port>` (DNS-rebinding defence, `app/infra/http_security.py`).
- **Separate credentials.** The engine token goes to the API, the worker and the inference engines. The management
  token goes only to the API and the host-engine; the worker and the inference engines never hold it.
- **Recording capability.** The worker never hands an engine a path. It sends an object key plus a capability:
  an HMAC-SHA256 of the key and an expiry, signed with `recording_capability_key`, valid 60 s
  (`app/infra/recording_capability.py`). The engine resolves the key inside the Recordings folder only.
- **Pinned models and binaries.** Models are installed only when their SHA-256 matches `model-catalog.json`. The
  whisper.cpp and Parakeet binaries must match `scripts/engines/engine-hashes.json` and `runtime-manifest.json`, or
  the engine is marked unverified. Packaging must never rewrite them (`desktop/scripts/verify-package.mjs`).
- **Minimal environment.** Services start with a fixed environment (`baseEnv`); nothing from a developer's shell leaks
  in. The API runs without an access log because media URLs carry signed tokens.
- **No silent fallback.** An engine that cannot start is reported as blocked, never replaced by another model.

## 9. Repo map

| Path | What |
|---|---|
| `desktop/src/main/` | Electron main: `services.ts` (what runs), `ports.ts`, `paths.ts`, `config.ts`, `setup.ts`, `updater.ts`, `releases.ts`, `tray.ts`, `relocate.ts` (move folders), `uninstall.ts`. |
| `desktop/scripts/` | `build-runtime.sh`, `stage.mjs`, `verify-package.mjs`, `package-diar-component.sh`, `dev.mjs`. |
| `desktop/electron-builder.json`, `runtime-manifest.json` | Packaging config; pinned runtime artifacts. |
| `backend/app/` | API and worker: `ingestion`, `meetings`, `transcription`, `diarization`, `summaries`, `engines`, `media`, `local`, `auth`, `infra`, `retention`, `thumbnails`, `portal`. |
| `backend/alembic/` | Database migrations. |
| `backend/{asr,diar,llm,host}-engine/` | Native engine services; shared code in `backend/engine-common/`. |
| `scripts/engines/` | `model-catalog.json`, `engine-hashes.json`, dev install and start scripts. |
| `frontend/` | React portal. |
| `extension/` | Chrome MV3 extension; store material in `CHROMEWEBSTORE.md` and `store/`. |
| `packages/shared-types/` | TypeScript types shared by the extension and the portal. |
| `landing/` | Static landing and privacy policy, published by `.github/workflows/pages.yml`. |
| `scripts/dev/`, `scripts/platform/`, `scripts/tests/` | Worktree helpers and repo checks; Docker stack helpers; script tests. |
| `docker-compose.yml`, `Makefile` | Docker dev stack (retiring) and common targets (`make package`, `make check-private`). |
