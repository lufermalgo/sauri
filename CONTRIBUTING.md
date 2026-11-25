# Contributing to Sauri

Thanks for your interest in Sauri. Bug reports, ideas and pull requests are all
welcome. By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

This file covers setup and pull requests. How to work on the code, the project rules and
the guides behind them are in [`AGENTS.md`](AGENTS.md) and [`rules/`](rules/). They are
written for people and AI coding agents alike, so point your agent at `AGENTS.md`.

## Before you start

- **Bugs and ideas:** open an issue with the bug or feature form. Search existing
  issues first.
- **Larger changes:** open an issue to discuss the approach before writing a lot of
  code.
- **Security problems:** report them privately, never in a public issue. See
  [SECURITY.md](SECURITY.md).
- **Privacy:** never attach real meeting recordings, transcripts, summaries or
  screenshots of real meetings to issues, pull requests or test fixtures. Use
  synthetic audio and invented content.

## Development setup

You need an Apple silicon Mac with macOS 14 or later, Node.js 20 or later,
[uv](https://docs.astral.sh/uv/), `cmake`, `pkg-config`, and Swift 6 with the Xcode
Command Line Tools.

```bash
npm ci                                  # JavaScript workspaces; also installs the git hooks

# Build the bundled runtime once (Python, PostgreSQL, ffmpeg, whisper.cpp, llama.cpp, Parakeet). Slow.
SAURI_RUNTIME_DIR="$HOME/Library/Caches/sauri-runtime-build/runtime-current" \
  bash desktop/scripts/build-runtime.sh

npm run desktop:dev                     # run the desktop app against the repository sources
```

`npm run desktop:dev` builds the portal and the app, then starts PostgreSQL, the API,
the worker and the native engines from the runtime, using the Python sources in
`backend/`. Its data lives in `~/Library/Application Support/Sauri-dev` and
`~/Sauri-dev`, so it never touches a real installation. Logs are in
`~/Library/Logs/Sauri-dev`.

`make package` builds an installable `.dmg` in `desktop/out/`.

### The Chrome extension

```bash
npm run build -w extension              # output in extension/dist
```

Load `extension/dist` as an unpacked extension in `chrome://extensions` (developer
mode on). The app only pairs with extension IDs listed in `ALLOWED_EXTENSION_IDS`
(`desktop/src/main/services.ts`). An unpacked build gets an ID from its folder: to
test it against a development build of the app, add that ID locally and do not
commit it.

### Older Docker stack

The repository still contains the earlier Docker Compose development stack
(`make up`, `make engines-install`, `make engines-up`). It is being retired in favour of the desktop app; use it only if your change targets it.

## Pull requests

1. Open or pick an issue, and for anything beyond a small fix wait for a maintainer's
   go-ahead on the approach.
2. Fork the repository and create a branch from `main`, named like the change
   (`fix/upload-progress`, `feat/export-srt`).
3. Keep the pull request to one change, with tests. Follow
   [`rules/WORKFLOW.md`](rules/WORKFLOW.md).
4. Run the checks for what you touched ([`rules/TESTING.md`](rules/TESTING.md#which-checks))
   and try the change in the running app (`npm run desktop:dev`).
5. Open the pull request against `main` and fill in the template: what and why,
   verification, and documentation impact.

The git hooks (installed by `npm ci`, or `make setup-hooks`) block commits and pushes
to `main`, check that code identifiers are in English, and stop private data
(`make check-private`, see [`rules/PRIVACY.md`](rules/PRIVACY.md)). Do not bypass them.

## Conventions

- Code, identifiers, comments and commit messages are in English, without accents.
- User-facing text lives only in the translation files: `frontend/src/locales/`,
  `extension/src/locales/` and `desktop/src/locales/`. Spanish is the source
  language and English must stay in step.
- Keep changes small, tested and consistent with the surrounding code. No dead code.
- Secrets go in environment variables or files outside the repository, never in
  commits, logs or test fixtures.
- Design tokens and UI rules are in [`DESIGN.md`](DESIGN.md).

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), the license of this project.
