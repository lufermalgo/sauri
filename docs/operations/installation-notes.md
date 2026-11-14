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

- Command: `make engines-install` (runs `_tools/install-diar-engine.sh`).
- Creates `~/.local/share/sauri/native-engines/diar-venv` with Python 3.11 and installs `backend/diar-engine/requirements-native.txt`: FastAPI service dependencies plus Senko pinned to commit `1bcb09041bfa170b4a5a4b0af92f66eff76204d5` from GitHub.
- Senko ships its models inside the package; the installer verifies the pinned commit and the SHA-256 of every model file listed in `_tools/engine-hashes.json`, and fails closed on any mismatch.
- Measured on a MacBook Air M3 (24 GB): ~41 s, downloads ~60 Python packages (coremltools, numba, scikit-learn, umap-learn, among others).
- Verify: `bash _tools/install-diar-engine.sh --check`; native test: `cd backend && SAURI_RUN_NATIVE_TESTS=1 uv run --extra dev pytest tests/native/test_diar_native.py` (passed, ~63 s).
- macOS only: Senko uses CoreML. Windows/Linux need another adapter behind the same diarization contract (Senko's CUDA/CPU mode or pyannote); the container engine `backend/diar-engine/main.py` is the current Linux fallback.

## Summary engine (llm-engine + llama.cpp + Qwen3.5-9B) — 2026-11-14

- Command: `bash _tools/install-llm-engine.sh` (Apple Silicon only today). Needs `uv`, `cmake` and `git`.
- Creates `~/.local/share/sauri/native-engines/llm/` with: a Python 3.11 venv for the gateway (`backend/llm-engine/requirements-native.txt`), a `llama-server` binary compiled from llama.cpp commit `af76639f728c69c74c873cc45f038aaa17afd09e` as a static build with Metal and without OpenSSL (the Homebrew build crashes with this model), and the model `unsloth/Qwen3.5-9B-GGUF` revision `3885219b…` file `Qwen3.5-9B-Q4_K_M.gguf` (~5.5 GB, SHA-256 `03b74727…`). It records `provenance.json` and fails closed on any hash or provenance mismatch.
- The model download is skipped when a file with the right SHA-256 is already in `models/` (useful for an offline or pre-seeded install).
- Measured on a MacBook Air M3: compile ~1 min 25 s (model pre-seeded). First request including cold model load: ~16 s for a short transcript; the model unloads after 120 s idle.
- Verify: `bash _tools/install-llm-engine.sh --check`; start with `bash _tools/native-engines.sh start llm`.
- Other platforms: llama.cpp builds on Linux (CUDA/CPU) and Windows; the gateway is platform-neutral, but the installer and the build flags (Metal) are macOS-specific today. An external OpenAI-compatible provider can replace the local engine through configuration.

## Pending to document

- ASR engine (whisper.cpp `large-v3-turbo`, unit U2).
- Extension packaging and updates; portal and backend updates.
