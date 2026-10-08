---
name: sauri-project-context
description: Shared product, architecture, stack, and validation context for development agents working on Sauri.
---

# Sauri project context

This is curated APX context migrated from `CLAUDE.md`. `AGENTS.md` remains the authoritative source for workflow, testing, Git, and contribution rules; `SECURITY.md` governs security-sensitive changes.

## Product and language

Sauri is a Summan platform concept whose target product baseline is being redefined by the user and Cyrus. The previous concept included Google Meet capture, transcription, speaker identification, ClickUp, a searchable library, and commercial analytics; treat those as historical scope, not current commitments or requirements, unless the owner explicitly adopts them in `PRODUCT_BASELINE.md`. The stack and architecture below describe the existing repository only; they are not the target architecture for the new baseline unless an approved spec chooses to reuse them. Treat actual meeting audio, video, transcripts, credentials, and customer details as sensitive. For tests, use synthetic fixtures, never real meeting data unless the owner explicitly authorizes it.

All code and domain identifiers are English. Actual transcript content remains Spanish because it reflects meeting speech. UI copy defaults to English unless a feature specification says otherwise. For canonical domain terminology and naming conventions, follow `AGENTS.md` rather than inventing translations.

## Stack

- Backend: Python 3.11, FastAPI, async SQLAlchemy, PostgreSQL, Alembic.
- Chrome extension: TypeScript, Manifest V3, React, Vite, CRXJS.
- Web frontend: TypeScript, React, Vite.
- Shared types: `packages/shared-types` (`@sauri/shared-types`).
- ASR: self-hosted faster-whisper service in `backend/asr-engine`.
- Diarization: pyannote.audio service in `backend/diar-engine`; requires `HF_TOKEN`.
- Local infrastructure: Docker Compose with PostgreSQL, MinIO, RabbitMQ, ASR and diarization services.

## Architecture patterns

- Backend modules use `router.py` → `service.py` → `repository.py` → `schemas.py`; shared infrastructure lives in `backend/app/infra/`.
- Pluggable ASR/diarization engines use a factory selected by configuration and a shared protocol. Keep domain services provider-agnostic.
- Meeting state transitions are pure functions in `backend/app/meetings/state_machine.py`; persistence and side effects belong in the service layer.
- Background transcription, diarization, and retention run in separate workers consuming RabbitMQ, not inline in request handlers.
- The MV3 extension uses a service worker, content script, offscreen document for media capture, React panel, IndexedDB persistence, and a durable upload queue. Follow the existing boundaries rather than bypassing them.

## Useful validation commands

- Backend, from `backend/`: `pytest`, `ruff check .`, `mypy .`.
- Frontend/extension: from each package, `npm run test`, `npm run typecheck`, `npm run build`; extension E2E uses `npm run test:e2e`.
- Root `npm run test` and `npm run typecheck` fan out across npm workspaces.
- Root `make up`, `make build`, `make down`, `make logs`, `make migrate` manage the Compose stack. `make clean` removes local volumes and data; do not run unless explicitly requested.

## Sensitive-data guardrail

Before changing storage, retention, authentication, or access control, read `SECURITY.md` and the relevant spec. Do not copy personal data, transcripts, secrets, tokens, or private runtime state into `.apc/`, Git, prompts, or test fixtures.
