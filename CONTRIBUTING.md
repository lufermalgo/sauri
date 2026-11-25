# Contributing to Sauri

Thanks for your interest in Sauri. Bug reports, ideas and pull requests are all
welcome. By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

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

1. Fork the repository and create a branch from `main` (for example
   `fix/upload-progress` or `feat/export-srt`).
2. Keep each pull request focused on one change, with tests.
3. Run the checks below and say in the pull request what you ran.
4. Open the pull request against `main` and fill in the template. Link the issue
   it closes.

The git hooks (installed by `npm ci`, or `make setup-hooks`) block commits and
pushes to `main` and check that code identifiers are in English. Do not bypass them.

## Required checks

```bash
npm run typecheck
npm run test
npm run i18n:check -w frontend          # only when you touch portal copy
npm run i18n:check -w extension         # only when you touch extension copy
cd backend && uv run --extra dev pytest -q
cd backend && uv run --extra dev ruff check .
cd backend && uv run --extra dev mypy app
make test-scripts                       # only when you touch scripts/
make check-english
```

`ruff check .` has known baseline errors on `main`; a pull request must not add new
ones, and `mypy app` must stay clean. Python commands always run through `uv` from `backend/`.

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
