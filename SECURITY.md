# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's
**Security** tab and choose **Report a vulnerability**
([direct link](https://github.com/lufermalgo/sauri/security/advisories/new)).
Do not open a public issue, pull request or discussion for a security problem.

Include the Sauri version (menu bar icon › About Sauri), your macOS version, the
steps to reproduce and the impact you expect. Never attach real meeting
recordings, transcripts or summaries: build a reproduction with synthetic audio.

This is a small project maintained in spare time. You will get an acknowledgement
as soon as possible, and we will agree on a disclosure date with you once a fix
is ready.

## Supported versions

Only the [latest release](https://github.com/lufermalgo/sauri/releases/latest)
receives security fixes. The app checks for new versions and offers to install
them.

## Scope

In scope:

- The Sauri desktop app for macOS (`desktop/`), including its updater and the
  services it starts: PostgreSQL, the API and worker (`backend/app`) and the
  native engines (`backend/asr-engine`, `diar-engine`, `llm-engine`,
  `host-engine`).
- The local API and the web portal it serves (`frontend/`).
- The Chrome extension (`extension/`).

Out of scope: third-party models and binaries (report those upstream; see
`THIRD_PARTY_NOTICES.md`), external providers a user connects on purpose, and
attacks that require an attacker who already controls the user's macOS account.

## Security model

Sauri is a single-user app that runs on the user's Mac. These notes describe the
boundaries the code enforces today.

### Local services

- The API and every engine listen on `127.0.0.1` only. The API in desktop mode
  answers only the `Host` values `localhost:<port>` and `127.0.0.1:<port>`, which
  blocks DNS rebinding from web pages.
- Browser calls are accepted only from explicit origins; a wildcard origin makes
  the API refuse to start.
- The Chrome extension pairs only if its origin is in the app's allow-list
  (`ALLOWED_EXTENSION_IDS` in `desktop/src/main/services.ts`) and then
  authenticates with a per-install local token.
- Internal credentials (local token, engine token, management token, recording
  capability key, database password) are random values created once per install
  in `~/Library/Application Support/Sauri/secrets/` (folder `0700`, files
  `0600`). They are never written to logs.
- Keys for external providers are kept by `host-engine` on the host (Keychain or
  a `0600` file). The worker never receives them.

### Native inference recording authorization

Native ASR and diarization requests require both the engine bearer token and an
`X-Sauri-Recording-Capability` header. The backend worker signs the exact
`audio_ref` and a 60-second expiry with an HMAC-SHA256 key that is independent of
the engine token (`SAURI_RECORDING_CAPABILITY_KEY_FILE`; in the desktop app,
`secrets/recording_capability_key`; in the development engine scripts,
`~/.config/sauri/recording_capability_key`). Engine handlers verify the signature
and expiry before reading the object or running inference, so a broad engine
token alone cannot authorize access to a recording. Keep the key readable only by
the worker and engine processes, rotate it by replacing it and restarting both
sides, and do not log capabilities. A capability scopes access to one object
reference; it assumes only the trusted worker can mint it and does not replace
authorization on user-facing API routes.

### Downloads and updates

- Models and the speaker component are downloaded only from allowed hosts and
  checked against SHA-256 hashes pinned in the repository before use.
- App updates come from this repository's GitHub Releases. Each redirect is
  checked against a fixed host list and the archive is verified against its
  `.sha256` file before it is applied.
- The app is ad-hoc signed, not notarized by Apple. Verify a downloaded `.dmg`
  with `shasum -a 256` against the `.sha256` file in the release.
