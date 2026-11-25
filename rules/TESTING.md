# Testing

## Which checks

Run what your change touches, from the repository root unless noted.

| You touched | Run |
|---|---|
| Any TypeScript (`desktop/`, `frontend/`, `extension/`, `packages/`) | `npm run typecheck` and `npm run test` |
| Portal or extension text | `npm run i18n:check -w frontend`, `npm run i18n:check -w extension` |
| Portal or extension build setup | `npm run build -w frontend`, `npm run build -w extension` |
| Python (`backend/`) | `cd backend && uv run --extra dev pytest -q`, `uv run --extra dev ruff check .` (no new errors), `uv run --extra dev mypy app` (clean) |
| PostgreSQL queue or locking | `make test-pg` (a disposable PostgreSQL 16 cluster; set `PG_BIN` if needed) |
| `scripts/` | `make test-scripts` |
| Packaging, runtime, updater | `make package` (builds and runs `verify-package`) |
| Always | `make check-private` and `make check-english` (the pre-commit hook runs both on staged files) |

Python always runs through `uv` from `backend/`; the system `python3` is not the project's interpreter.

CI runs the backend tests, the portal and extension tests, type checks and builds, and `check_private_terms.py`. Some
backend steps are still marked non-blocking in `.github/workflows/ci.yml` while old debt is paid; a pull request must not
add failures to them.

## Runtime proof

A green test run is not proof that the feature works. After the checks:

1. Start the app from your sources: `npm run desktop:dev`. Its data lives in `~/Sauri-dev` and
   `~/Library/Application Support/Sauri-dev`, and logs in `~/Library/Logs/Sauri-dev`; a real installation is never
   touched.
2. Exercise the path you changed, end to end, with synthetic audio: upload a file or record a tab playing a synthetic
   meeting through the extension.
3. For a screen: light and dark mode, Spanish and English, and narrow widths where they apply. Attach the screenshots to
   the pull request. Never use a real meeting.
4. Report what you exercised and what you did not (`UNVERIFIED`).

## Fix regression contract

Fixing a bug or a failing test:

1. Reproduce it: a test, or exact steps, that fails for the reported reason.
2. Fix the cause, not the symptom.
3. Keep a test that would catch it again: new, or strengthened.
4. Run the tests of the callers of what you changed.

Never loosen an assertion, skip a test, raise a timeout or switch a check off to make a failure go away. If a test
itself was wrong, say why in the pull request and show what it now proves.

## Portable tests

Tests run on a fast laptop and on a shared 2-core CI runner. To pass on both:

- **No real time decides an outcome.** Use fake timers (`vi.useFakeTimers()`) or inject a clock. Never assert after a
  fixed `setTimeout`.
- **Wait for the state you assert.** In UI tests, `await screen.findBy…` or `await waitFor(…)` for anything that renders
  after loading; assert on the loaded screen, not the first frame. For background work, `await vi.waitFor(…)`.
- **Mocks follow vitest's semantics.** A mock used with `new` needs a `function` implementation. `vi.restoreAllMocks()`
  only restores spies, so clear `vi.mock` factories with `vi.resetAllMocks()` or `mockClear()` when a test counts calls.
  Unmount (`cleanup()`) before removing globals the component still uses.
- **Synthetic data only.** Media headers from `backend/tests/media_samples.py`, generated tones or synthetic speech; names like Acme and Laura
  Méndez; emails `@example.test`. See [`PRIVACY.md`](PRIVACY.md).
- **No shared state.** Each test builds what it needs; database tests use the disposable cluster, never your
  development database.
- **Do not read source files in tests.** Test behaviour through public functions, HTTP and the UI.

A test that fails only on CI is a real failure. Find the race; do not retry it until it passes.
