# Decisions

Why Sauri is the way it is. One entry per decision: what was decided, why, and what was rejected. Add an entry when you
make a choice that a later contributor would otherwise undo; code comments can point here (`See DECISIONS.md#d-003`).
Entries are never rewritten: a change of mind is a new entry that says which one it replaces.

## D-001

**Local first.** Recording, transcription, speakers and summaries run on the user's Mac. External providers are opt-in
per task, and the app shows what leaves before it leaves. *Why:* conversations are private, and a meeting tool that
uploads them by default asks for trust it has not earned. *Rejected:* a cloud service as the default path.

## D-002

**Engines behind stable contracts.** Each capability (transcription, speakers, summaries, model hosting) is a separate
local service with an HTTP contract; the API chooses a local engine or an external provider by configuration. *Why:*
models change fast; swapping one must not touch the domain. *Rejected:* importing model libraries into the API process.

## D-003

**One heavy engine at a time.** Inference takes a PostgreSQL advisory lock (`backend/app/infra/engine_slot.py`), so
two workers never load large models at once. *Why:* the target machines have 8–16 GB shared between CPU and GPU, and
two models at once can push the Mac into swap. *Rejected:* a per-engine queue with free concurrency.

## D-004

**A desktop app, not a Docker stack.** The app ships a relocatable runtime (Python, PostgreSQL, ffmpeg, engine binaries)
and supervises every process itself. *Why:* people who record meetings should not need Docker, and native engines need
direct access to the Apple GPU and Neural Engine. *Rejected:* Docker Desktop as a requirement. The earlier Compose stack
remains in the repository while it is retired.

## D-005

**Loopback and pairing instead of accounts.** Services bind to `127.0.0.1`; the extension pairs with the app on the same
Mac; native engines also check a per-recording capability token. *Why:* no server of ours means nothing to sign in to,
and nothing to breach. *Rejected:* email and password login for a local app.

## D-006

**Downloads are pinned and allow-listed.** Models and components carry SHA-256 hashes in
`scripts/engines/model-catalog.json`. The updater only follows the Releases of `lufermalgo/sauri`, checking every
redirect hop against a fixed list. *Why:* an app that installs code and models must not be redirectable to someone
else's files. *Consequence:* renaming or moving the releases repository strands installed apps. A new release location
ships first in a version that still reads the old one.

## D-007

**One public repository, Apache-2.0.** Code, releases and the landing page live in `lufermalgo/sauri`. *Why:* one place
for people to find, use and improve Sauri, with a licence that allows any use and protects contributors with a patent
grant, and does not license the Sauri name or logo. *Rejected:* a private code repository plus a separate public
downloads repository (the setup until version 0.2.3).

## D-008

**Spanish first on screen, English in code.** Text a person reads is written in Spanish first and kept in step in
English, in locale files only. Identifiers, comments and commits are English. *Why:* the first users speak Spanish;
contributors and tools work best with English code.
