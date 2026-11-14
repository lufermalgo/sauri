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
- ASR failures persist a retryable meeting state with a safe category: `engine_contract_mismatch`, `engine_failed`, or `invalid_response`. Engine response bodies, paths and transcript text are not copied into logs or stored as causes.

- Both ASR adapters trim segment text. Word text keeps its separators: U3 reconstructs turns by concatenating words, so stripping every word would merge adjacent words.
