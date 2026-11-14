# Sauri

Sauri records virtual meetings from a Chrome tab and produces transcripts with speaker identification and draft summaries. Everything runs locally: audio, transcripts and summaries never leave your machine unless you explicitly configure an external service.

## Status

Early development. The speech core (fast local transcription, speaker attribution per word, and summaries as reviewable drafts) is specified in [`.spectra/specs/core-speech-pipeline`](.spectra/specs/core-speech-pipeline/) and is being implemented. Nothing here is production-ready. Approved product scope lives in [`docs/product/baseline.md`](docs/product/baseline.md).

## Architecture

- **Chrome extension** (Manifest V3): captures tab audio and video and uploads the recording.
- **Web portal** (React, served by Nginx): upload, browse, play back and review recordings.
- **API and workers** (FastAPI, Python): authentication, recording lifecycle and the processing pipeline.
- **Docker services**: PostgreSQL, RabbitMQ and S3-compatible object storage.
- **Native Mac engines** (outside Docker, for Apple GPU acceleration): whisper.cpp (transcription), Senko (speaker identification) and llama.cpp (summaries), each behind a stable contract so it can be swapped by configuration.

See [`docs/architecture/overview.md`](docs/architecture/overview.md) for details and current gaps.

## Quick start

Requirements: macOS on Apple silicon, Docker Desktop, Node.js 20 or newer, Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
npm ci                  # JavaScript workspaces; also installs the git hooks
make up                 # Docker stack: database, queue, storage, API, worker, portal
make engines-install    # native engines, once
make engines-up         # start the native engines
```

The portal is served at `http://127.0.0.1:5173`. `make down` stops the stack and `make logs` shows its logs. Private variables, credentials and cleanup are described in [`docs/operations/local-deployment.md`](docs/operations/local-deployment.md). `make clean` deletes data.

To load the extension, build it and open `chrome://extensions/` with developer mode on:

```bash
cd extension && npm run build   # then load extension/dist/ as an unpacked extension
```

## Repository layout

```text
backend/            API, workers, migrations, tests and the audio engines
frontend/           web portal
extension/          Chrome extension
packages/           shared TypeScript types
scripts/            development, engine, platform scripts and their tests (dev, engines, platform, tests)
docs/
  product/          approved scope and discovery notes
  architecture/     overview and project structure
  operations/       local deployment and validation
  design/           visual references
  history/          past reports and spikes
.spectra/specs/     specifications, indexed in .spectra/README.md
```

## Contributing and security

- [CONTRIBUTING.md](CONTRIBUTING.md): setup, workflow and required checks.
- [SECURITY.md](SECURITY.md): handling of personal data and vulnerability notes.
- [AGENTS.md](AGENTS.md): full working rules for contributors and agents.

## License

To be defined.
