## What and why

<!-- What this pull request changes and why. Link the issue it closes: "Closes #123". -->

## How it was tested

<!-- Commands you ran and what you checked by hand (app, portal, extension). -->

## Checklist

- [ ] `npm run typecheck` and `npm run test` pass (TypeScript changes)
- [ ] `cd backend && uv run --extra dev pytest -q` passes (Python changes)
- [ ] No new `ruff check .` errors, and `uv run --extra dev mypy app` is clean
- [ ] `npm run i18n:check -w frontend` / `-w extension` pass (user-facing text changes)
- [ ] `make test-scripts` passes (changes in `scripts/`)
- [ ] Code, comments and commit messages are in English; user-facing text is only in the locale files
- [ ] No real meeting recordings, transcripts, summaries or secrets in code, fixtures, logs or screenshots
