# Installation notes (input for the future installer and updater)

Living record of what each Sauri component needs to be installed, kept as engines are added. The goal is a future installer and update manager for the extension, the web portal and the backend on macOS, Windows and Linux. Today only macOS (Apple Silicon) is supported for the native engines.

## Common prerequisites (macOS today)

| Need | How it is installed today | Notes for other platforms |
|---|---|---|
| Docker Desktop | Manual download | Windows: Docker Desktop (WSL2). Linux: Docker Engine + Compose plugin. |
| Node.js ≥ 20 + npm | Homebrew | Same version on every platform. |
| Python 3.11 (native engines) | Homebrew `python@3.11` | Linux: system/pyenv; Windows: python.org installer. |
| uv (backend tooling) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Available on all three. |
| ffmpeg | Homebrew `ffmpeg` | Linux: distro package; Windows: static build on PATH. |
| PostgreSQL, RabbitMQ, S3-compatible storage | Docker Compose (`make up`) | Same on all platforms. |

## Diarization engine (Senko, CoreML) — 2026-11-14

- Command: `make engines-install` (runs `scripts/engines/install-diar-engine.sh`).
- Creates `~/.local/share/sauri/native-engines/diar-venv` with Python 3.11 and installs `backend/diar-engine/requirements-native.txt`: FastAPI service dependencies plus Senko pinned to commit `1bcb09041bfa170b4a5a4b0af92f66eff76204d5` from GitHub.
- Senko ships its models inside the package; the installer verifies the pinned commit and the SHA-256 of every model file listed in `scripts/engines/engine-hashes.json`, and fails closed on any mismatch.
- Measured on a MacBook Air M3 (24 GB): ~41 s, downloads ~60 Python packages (coremltools, numba, scikit-learn, umap-learn, among others).
- Verify: `bash scripts/engines/install-diar-engine.sh --check`; native test: `cd backend && SAURI_RUN_NATIVE_TESTS=1 uv run --extra dev pytest tests/native/test_diar_native.py` (passed, ~63 s).
- macOS only: Senko uses CoreML. Windows/Linux need another adapter behind the same diarization contract (Senko's CUDA/CPU mode or pyannote); the container engine `backend/diar-engine/main.py` is the current Linux fallback.

## Summary engine (llm-engine + llama.cpp + Qwen3.5-9B) — 2026-11-14

- Command: `bash scripts/engines/install-llm-engine.sh` (Apple Silicon only today). Needs `uv`, `cmake` and `git`.
- Creates `~/.local/share/sauri/native-engines/llm/` with: a Python 3.11 venv for the gateway (`backend/llm-engine/requirements-native.txt`), a `llama-server` binary compiled from llama.cpp commit `af76639f728c69c74c873cc45f038aaa17afd09e` as a static build with Metal and without OpenSSL (the Homebrew build crashes with this model), and the model `unsloth/Qwen3.5-9B-GGUF` revision `3885219b…` file `Qwen3.5-9B-Q4_K_M.gguf` (~5.5 GB, SHA-256 `03b74727…`). It records `provenance.json` and fails closed on any hash or provenance mismatch.
- The model download is skipped when a file with the right SHA-256 is already in `models/` (useful for an offline or pre-seeded install).
- Measured on a MacBook Air M3: compile ~1 min 25 s (model pre-seeded). First request including cold model load: ~16 s for a short transcript; the model unloads after 120 s idle.
- Verify: `bash scripts/engines/install-llm-engine.sh --check`; start with `bash scripts/engines/native-engines.sh start llm`.
- Other platforms: llama.cpp builds on Linux (CUDA/CPU) and Windows; the gateway is platform-neutral, but the installer and the build flags (Metal) are macOS-specific today. An external OpenAI-compatible provider can replace the local engine through configuration.

## Administrator account — 2026-11-14

- For now Sauri has a single account, the administrator `admin@sauri.local`; other profiles come later. `make up` (via `scripts/engines/ensure-native-engine-credentials.sh`) generates a random password once into `~/.config/sauri/admin_password` (0600, never overwritten), mounts it read-only into the `api` container and runs `python -m app.auth.seed_admin --retire-legacy`, which creates the account and moves data owned by the old seed users to it. Read it with `cat ~/.config/sauri/admin_password`; to change it, replace the file (20+ characters) and run `docker compose run --rm api python -m app.auth.seed_admin --reset-password`. The installer must provision this file the same way on every platform.

## Local credentials and published ports — 2026-11-14

- No fixed credentials remain. `scripts/engines/ensure-native-engine-credentials.sh` (run by `make build` and `make up` through `scripts/platform/compose-bringup.sh`) generates random values once, never overwriting, as private files (0600, folder 0700) under `~/.config/sauri/`: `engine_token`, `recording_capability_key`, `queue_signing_key`, `admin_password`, `database_password`, `queue_password`, `object_store_access_key`, `object_store_secret_key`, `jwt_secret`. The installer must provision the same files on every platform with the same permissions.
- Containers get them as read-only files under `/run/secrets/<name>` and read them via `DATABASE_PASSWORD_FILE`, `QUEUE_BROKER_PASSWORD_FILE`, `OBJECT_STORE_ACCESS_KEY_FILE`, `OBJECT_STORE_SECRET_KEY_FILE`, `JWT_SECRET_FILE` (PostgreSQL: `POSTGRES_PASSWORD_FILE`; RustFS: `RUSTFS_ACCESS_KEY_FILE`/`RUSTFS_SECRET_KEY_FILE`). The native ASR and diarization engines read the object-store keys from `~/.config/sauri/object_store_access_key` and `object_store_secret_key` (override with `SAURI_OBJECT_STORE_ACCESS_KEY_FILE` / `SAURI_OBJECT_STORE_SECRET_KEY_FILE`).
- Every published port (portal 5173, API 8000, PostgreSQL 5432, RustFS 9000/9001, RabbitMQ 5672/15672) binds to `127.0.0.1` only. Native engines (8001-8004) already did.
- One-time migration of an existing installation, no data loss: the next `make up` sets the database role password from the file (`ALTER ROLE` inside the container, nothing printed), creates the RabbitMQ user `sauri` with the file password and deletes `guest`, and starts RabbitMQ with the new named volume `rabbitmq-data` and a fixed hostname (users and durable queues survive container recreation). RustFS starts with the new root keys over the same data volume. Afterwards restart the native engines once: `make engines-down && make engines-up`.
- Reading a value: the owner runs `cat ~/.config/sauri/<file>`; scripts never print or commit values. Rotating: delete the file and run `make up` (database and queue are re-synced, RustFS keys follow the file, the admin password uses `python -m app.auth.seed_admin --reset-password`). Changing `jwt_secret` logs everyone out.

## Local model choice in the gateways (U6.3)

- The ASR and LLM gateways accept `X-Sauri-Route` with `local:<id>`. No header, or `local:default`, keeps the built-in model, unchanged (LLM alias `qwen3.5-9b`). `local:<id>` resolves the catalog file in `SAURI_MODELS_DIR` (default `~/.local/share/sauri/models`) and requires its `*.manifest.json` (written by `host-engine` after a hash-verified install) to say `installed` with the catalog SHA-256, the catalog size, the size on disk and the same `mtime_ns`. The hash is not recomputed per request.
- Unified directory without moving files: the process default model may live at the engine's legacy location (the 9B LLM model in `native-engines/llm/models`, the ASR model without a manifest). `local:<default id>` uses the catalog entry first and falls back to that legacy file only when its size equals the catalog size; its hash was verified by the engine installer. No other model falls back and no file is moved or deleted.
- Errors (`{"detail": code}`): `409 model_not_installed`, `409 model_not_verified` (run Verify in the portal), `422 unknown_model`, `422 route_malformed`, `422 route_capability_mismatch`, `422 route_not_supported` (external routes are not served by this path yet).
- The LLM gateway restarts `llama-server` with `--alias <id>` when the requested model file differs from the loaded one; a refused request never touches the running server.
- API: `GET /api/v1/engines/local/{hardware,models,jobs/<id>}`, `POST .../models/<id>/{install,verify}`, `POST .../jobs/<id>/cancel` and `DELETE .../models/<id>` proxy the host-engine local-model routes (signed-in users only; the management token never leaves the API).
- Deploy: restart the native `asr`, `llm` and `host` engines (`bash scripts/engines/native-engines.sh stop <engine>` then `start <engine>`) and the API container. Do not restart `llm` while a summary is running.
- Opt-in verification with the real binaries and installed models: `cd backend && SAURI_RUN_NATIVE_TESTS=1 .venv/bin/pytest tests/native/test_local_model_native.py -q` (starts its own `whisper-cli` and `llama-server` on a random port; skips what is not installed).

## Recognizing models installed by hand (adoption, #1127)

- A Mac where the transcription, speaker and summary engines or models were installed by hand is shown in the portal exactly as if they had been installed from the install button: each option says installed (verified), which one is active for each process, and which others can still be installed. A new Mac with nothing installed shows everything as available.
- How it is recognized: `host-engine` looks, for every catalog file, in the models directory (`SAURI_MODELS_DIR`, default `~/.local/share/sauri/models`) and, for the default model of a process, at its legacy location (the 9B summary model in `~/.local/share/sauri/native-engines/llm/models`, or `SAURI_LLM_MODEL_FILE`; an explicit `ASR_MODEL_PATH` for transcription). The file size is checked, then its SHA-256 is computed once, in a background job (`type: adopt`, with progress) so a 5 GB file does not block the service, and compared with the hash pinned in `scripts/engines/model-catalog.json`. Only a match writes the same `<file>.manifest.json` an install writes; a file at its legacy location gets `"location": "legacy"` and the manifest still lives in the models directory. Older manifests without `location` stay valid (they mean the models directory).
- When it runs: automatically when the host engine starts (`SAURI_ADOPT_ON_START=0` turns it off) and on demand with `POST /v1/local/adopt` (through the API: `POST /api/v1/engines/local/adopt`). It is idempotent: a file already verified, or already judged different at the same size and modification time, is not hashed again.
- A file that differs from the catalog (different size or hash) is never claimed as installed: it is listed as `present_unverified` with the reason (`size_mismatch` or `hash_mismatch`), the gateways refuse it, and it can be installed again from the catalog.
- What never happens: no file is moved, copied, renamed or deleted, nothing is downloaded (adoption does not touch the network), and a model that lives at its legacy location cannot be removed from the portal (`409 legacy_location`). Replacing or editing an adopted file changes its modification time, so it stops being trusted until adoption runs again.
- Managed engine (Senko): it has no file to hash. It counts as installed when its virtual environment (`SAURI_DIAR_VENV`, default `~/.local/share/sauri/native-engines/diar-venv`) has an interpreter and the `senko` package; this is a presence check only (`bash scripts/engines/install-diar-engine.sh --check` does the integrity check).
- Active model per process (`GET /v1/local/models`, field `active` per model and `active` map): the model chosen in `selection.json`, else the catalog default, and only when it is installed; the auxiliary voice-detection file is `in_use` but never `active`. External providers are a separate choice and are not part of this listing.
- Deploy after merging: restart the host engine (`bash scripts/engines/native-engines.sh stop host` then `start host`); it adopts by itself, or call `POST /v1/local/adopt` and poll the returned job.

## Pending to document

- Extension packaging and updates; portal and backend updates.

## ASR engine (whisper.cpp, Metal) — 2026-11-14

- `make engines-install` runs `scripts/engines/install-asr-engine.sh`. Requires Python 3.11, ffmpeg and an executable `whisper-cli` (default `/opt/homebrew/bin/whisper-cli`, override `WHISPER_CLI`). It does not install Homebrew packages.
- The isolated `~/.local/share/sauri/native-engines/asr-venv` contains only the FastAPI/uvicorn/Pydantic/boto3 service dependencies, not MLX, Torch or pyannote. The old shared venv is left untouched and is no longer the default.
- Model: `~/.local/share/sauri/models/ggml-large-v3-turbo-q5_0.bin` (`ASR_MODEL_PATH` override), 574,041,195 bytes, SHA-256 `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2`. An existing file is verified without replacing it; otherwise `SAURI_ASR_MODEL_SOURCE` can provide a local copy, or the installer downloads from ggerganov/whisper.cpp on Hugging Face. Any size/hash mismatch fails closed.
- `bash scripts/engines/install-asr-engine.sh --check` verifies assets and requires provenance without modifying anything or requiring the service venv. Installation records the executable SHA-256 and model SHA-256 in `native-engines/asr-provenance/provenance.json`; subsequent runs reject missing or changed provenance. The native service performs the same model and binary hash verification once at startup, before accepting requests. This records the installed binary, not a vendor-signed binary pin.
- `SAURI_DEFAULT_LANGUAGE=es` is the default; only two lowercase letters or `auto` are accepted (invalid configuration fails startup). `auto` enables detection. Ingestion accepts optional two-letter/`auto` `language` in multipart `data` and forwards it to the transcription queue. No language preference or new database column is introduced. Recovery jobs without a language override use the configured default. Only the native engine boundary also accepts legacy region hints, reducing them to the two-letter base code. Migration `018_transcript_language_default` changes the SQL default for future rows to `es`, without rewriting existing rows.
- Native service: contract v2 with segments, words, detected language, engine metadata and stage timings; shared PCM mono 16 kHz normalization and KeepAwake protection. `ASR_THREADS=4` by default. Linux retains faster-whisper with word timestamps and the same v2 schema.
- Opt-in verification: `cd backend && SAURI_RUN_NATIVE_TESTS=1 uv run --extra dev pytest tests/native/test_asr_native.py -q`. Uses only a synthetic 30-second tone/silence recording; skips if the installation is absent. This is a technical smoke test, not speech accuracy or product acceptance.

- `ASR_TIMEOUT_SECONDS` is the single end-to-end HTTP timeout (default 3600 s); configure the same value for the worker and native service. The client uses it directly; the server reserves `min(30 s, 10%)` for transport/response overhead, so its request deadline is 3570 s by default. The deadline starts before waiting for the engine lock, bounds the HTTP response including download, and is shared by normalization (at most 300 s) and inference (only the remaining time). Storage reads use the remaining deadline as their socket timeout and check it between chunks; an expired request cleans up without starting inference. Linux also bounds its HTTP response by this deadline.
- ASR failures persist a retryable meeting state with a safe category: `engine_contract_mismatch`, `engine_failed`, or `invalid_response`. A recording the engine reports as having no detected speech (`422 no_speech`) persists the terminal cause `no_speech_detected` instead: it is an expected outcome, so no retry is offered and no diarization or summary runs. Engine response bodies, paths and transcript text are not copied into logs or stored as causes.

- Both ASR adapters trim segment text. Word text keeps its separators: U3 reconstructs turns by concatenating words, so stripping every word would merge adjacent words.
