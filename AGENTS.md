# AGENTS.md — how to work on Sauri

> The guide for anyone changing Sauri, people and AI coding agents alike (Claude Code, Codex and any tool that reads
> `AGENTS.md`). This file is the hub: glossary, dev loop, repo map and the numbered rules. Everything else is read on
> demand under [`rules/`](rules/). Setup and pull requests: [`CONTRIBUTING.md`](CONTRIBUTING.md).

New here? Read [`rules/HUMAN_MODEL.md`](rules/HUMAN_MODEL.md) (what runs and how a recording travels), then the rules
below. Before opening a pull request, follow [`rules/WORKFLOW.md`](rules/WORKFLOW.md).

## Glossary

| Term | Means here | Not to be confused with |
|---|---|---|
| **app** | `desktop/`, the Electron app for Mac. It starts, watches and updates every other process. | The portal. |
| **portal** | `frontend/`, the React UI, served by the API and shown inside the app or a browser. | A website. |
| **extension** | `extension/`, the Chrome extension that records a browser tab and hands it to the app. | The app. |
| **API / worker** | `backend/app`: FastAPI for requests, the worker for the processing pipeline. Both own the domain. | The engines. |
| **engine** | A native service behind a stable HTTP contract: `asr-engine` (transcription), `diar-engine` (speakers), `llm-engine` (summaries), `host-engine` (models and provider keys). | A provider. |
| **provider** | Who does a task: the local engine, or an external service the user connects (an OpenAI-compatible API, Deepgram, AssemblyAI…). | An engine. |
| **runtime** | The relocatable bundle the app ships: Python, PostgreSQL, ffmpeg and the engine binaries. | Node/Electron. |
| **component** | A large download installed on first run or later (models, the speaker runtime), pinned by SHA-256. | An npm package. |
| **meeting / recording** | A meeting is what the user sees; its recording is the audio/video file behind it. | A session. |
| **transcript** | Word-level text with timestamps and a speaker per word. | A summary. |
| **speaker** | A voice found by diarization; the user can name it and Sauri reuses the name in later meetings. | A user account. |
| **summary** | A draft written by the LLM from the transcript and a template; the user reviews it. | Notes (written by the user). |
| **pairing** | How the extension and the app trust each other on localhost, without email or password. | Signing in. |

## Dev loop

```bash
npm ci                                   # JavaScript workspaces; also installs the git hooks (.githooks)
SAURI_RUNTIME_DIR="$HOME/Library/Caches/sauri-runtime-build/runtime-current" \
  bash desktop/scripts/build-runtime.sh  # once: the bundled runtime (slow)
npm run desktop:dev                      # the app against your sources; data in ~/Sauri-dev, never a real install
npm run build -w extension               # extension/dist, load it unpacked in chrome://extensions
npm run typecheck && npm run test        # every TypeScript workspace
cd backend && uv run --extra dev pytest -q   # backend tests (Python always through uv, from backend/)
make check-private check-english         # the public-safe and English-identifier gates
make package                             # desktop/out/Sauri-<version>-mac-arm64.dmg, verified
```

Which checks a change needs, and how to prove it works in the running app: [`rules/TESTING.md`](rules/TESTING.md).

## Repo map

```
desktop/     Electron app: process supervision, ports, folders, first run, updater, pairing   (TypeScript)
frontend/    portal: library, meeting view, transcript, speakers, summaries, settings       (React, Vite)
extension/   Chrome MV3 extension: capture, upload to the app, side panel                    (React, Vite, CRXJS)
backend/app  API + worker: meetings, ingestion, transcription, diarization, summaries…       (Python, FastAPI)
backend/*-engine  native engine services; backend/engine-common shared engine code
packages/    shared TypeScript types         landing/  public download page (GitHub Pages)
scripts/     dev, engines, platform scripts and their tests       brand/  logo and social images
rules/       engineering guides (this folder is the "read on demand" part of this file)
```

## Project rules

Each rule says how it is enforced: `[gate]` = a command or CI fails; `[review]` = checked in review.

1. **Local first.** Audio, transcripts, summaries and speaker names stay on the user's Mac. Anything that leaves it
   goes to a provider the user connected on purpose, and the app shows what leaves and where before it does.
   `[review]`
2. **Loopback only.** The app's services listen on `127.0.0.1`; only paired extension IDs may talk to the app; native
   engines also require the per-recording capability token. `[review]`, tests.
3. **Engines stay behind their contracts.** The API and worker call engines through `backend/app/engines`; a provider
   is swapped by configuration, never by importing an engine's internals. `[review]`
4. **Clients hold no domain logic.** The portal, the extension and the app's UI call the API; rules about meetings,
   speakers and summaries live in `backend/app`. The app supervises processes; it does not process meetings. `[review]`
5. **One heavy engine at a time.** Inference takes the shared engine slot (`backend/app/infra/engine_slot.py`); do not
   add a second path that runs a model outside it. `[review]`
6. **Pinned downloads.** Models and components are checked against the SHA-256 in `scripts/engines/model-catalog.json`;
   the updater fetches only allow-listed URLs, hop by hop (`desktop/src/main/releases.ts`). `[gate]` tests.
7. **No real meetings anywhere in the repo.** No real recordings, transcripts, summaries, meeting titles or screenshots
   of real meetings in code, fixtures, tests, issues, pull requests or logs. Use synthetic audio and invented content.
   `[review]`
8. **Public-safe content.** No real people or company names, personal emails, phone numbers, machine-local paths or
   credentials. Placeholders: Acme, Northwind, `user@example.com`, `~/work/…`. `[gate]` `make check-private` (also in
   the pre-commit hook and CI).
9. **Secrets by file or environment variable**, never in the repository, logs, prompts or test fixtures. `[gate]` GitHub
   secret scanning with push protection.
10. **English in code; people's language on screen.** Identifiers, comments and commits are English without accents.
    Text a person reads lives only in `frontend/src/locales/`, `extension/src/locales/` and `desktop/src/locales/`;
    Spanish is the source language and English stays in step. `[gate]` `make check-english`, `npm run i18n:check`.
11. **Screens talk to the person.** UI text says what the person can do and what happens, in plain words: no internal
    names, stack traces or engine jargon. Colours, type and spacing come from [`DESIGN.md`](DESIGN.md). `[review]`
12. **Fixes leave regression protection.** Reproduce the failure, add or strengthen a test that catches it, then fix
    it. Never weaken an assertion, skip a test or switch a gate off to get green. `[review]`
13. **Tests do not depend on luck.** No real time deciding an outcome; wait for the state you assert (`findBy…`,
    `waitFor`, `vi.waitFor`), not for a fixed delay; fixtures are synthetic. [Portable tests](rules/TESTING.md#portable-tests).
    `[review]`
14. **Schema changes are Alembic migrations** that run on start. Never edit a migration that has shipped. `[review]`
15. **New dependency = stated reason** in the pull request: why the platform or an existing dependency is not enough.
    `[review]`
16. **Branches and commits.** Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`…), branches named the same way
    (`feat/…`, `fix/…`), from and back into `main` through a pull request. Never push to `main` or force-push.
    `[gate]` git hooks and the `main` ruleset.
17. **Docs move with the code.** Every feature and fix states `Docs impact: updated` (with paths) or `Docs impact: none`
    (with a reason) in the pull request; update `README.md`, `CONTRIBUTING.md`, this file or `rules/` in the same
    change. `[review]` (pull request template)
18. **Proof, not claims.** A green typecheck is not proof. Behaviour changes are exercised in the running app
    (`npm run desktop:dev`); UI changes come with screenshots. Anything not exercised is reported `UNVERIFIED`.
    `[review]`

### Code comments

One or two lines, only the non-obvious *why*. No history, incident notes, dates or rejected alternatives in code: those
go to [`rules/DECISIONS.md`](rules/DECISIONS.md), and the comment can point at the entry.

## Workflow

Non-trivial changes follow [`rules/WORKFLOW.md`](rules/WORKFLOW.md): open an issue → plan → implement with tests →
self-review → checks and runtime proof → pull request with verification and docs impact → review → merge.

## Deep dives

| When | Read |
|---|---|
| First time; what runs and how a recording travels | [`rules/HUMAN_MODEL.md`](rules/HUMAN_MODEL.md) |
| Making a change, start to finish | [`rules/WORKFLOW.md`](rules/WORKFLOW.md) |
| Which checks to run; fixing a bug or a failing test | [`rules/TESTING.md`](rules/TESTING.md) |
| Privacy, fixtures and the public-safe gate | [`rules/PRIVACY.md`](rules/PRIVACY.md) |
| Why something is the way it is | [`rules/DECISIONS.md`](rules/DECISIONS.md) |
| Cutting a release (maintainers) | [`rules/RELEASE.md`](rules/RELEASE.md) |
| Colours, type, components | [`DESIGN.md`](DESIGN.md) |
| Security reports | [`SECURITY.md`](SECURITY.md) |
