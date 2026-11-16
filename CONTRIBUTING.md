# Contributing to Sauri

Sauri is in early development. Read `AGENTS.md` for the full working rules (it is written in Spanish); this file is the short version.

## Setup

```bash
make setup-hooks        # git hooks that block direct commits to main (also run by npm ci)
npm ci                  # JavaScript workspaces: extension, frontend, packages/*
make up                 # Docker stack: API, worker, portal, PostgreSQL, RabbitMQ, S3-compatible storage
make engines-install    # native Mac engines (once)
make engines-up         # start the native engines
```

Python commands run through uv: `cd backend && uv run --extra dev <command>`.

## Workflow

1. Write or update the spec in `.spectra/specs/<slug>/` (requirements, design, tasks) before code. Specs are indexed in `.spectra/README.md`.
2. One issue, one branch, one git worktree per delivery unit, created from `origin/main` (`make worktree BRANCH=feature/issue-N-desc`). Never work in the root checkout or on `main`.
3. Open a pull request linked to the issue. Do not bypass hooks.

## Required checks

```bash
npm run typecheck
npm run test
cd backend && uv run --extra dev pytest -q
cd backend && uv run --extra dev ruff check .
cd backend && uv run --extra dev mypy .
```

## Conventions

- Identifiers, comments and commit messages are in English. User-facing UI copy (Spanish source and English) lives only in `frontend/src/locales/`; `npm run i18n:check` keeps both languages in step. `make check-english` enforces this.
- Keep changes small, tested and consistent with the surrounding code. No dead code.
- Secrets go in environment variables or files outside the repository, never in commits or logs.
