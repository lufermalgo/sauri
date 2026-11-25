# Change workflow

For any change bigger than a typo. A one-line fix can jump to step 5.

ISSUE → PLAN → IMPLEMENT → SELF-REVIEW → CHECKS + RUNTIME PROOF → PULL REQUEST → REVIEW → MERGE

## 1. Issue

- Search the open issues first. Bugs and ideas use the issue forms.
- For anything that changes behaviour, a screen or a contract, say what you want to change in the issue and wait for
  a maintainer's go-ahead before writing a lot of code. Product direction is the maintainer's call.

## 2. Plan

Do not edit yet.

- Trace the current behaviour through the real path: extension → app → API → worker → engine → portal
  ([`HUMAN_MODEL.md`](HUMAN_MODEL.md)).
- Name the files you will touch and the existing function, component or pattern you will reuse.
- List side effects: database writes, files on disk, queue jobs, engine calls, anything that leaves the Mac.
- Say how you will prove it works ([`TESTING.md`](TESTING.md)).

## 3. Implement

- Work on a branch from `main`, named like the commit type: `fix/upload-progress`, `feat/export-srt`.
- Keep the diff to the change: no unrelated refactors, formatting sweeps or renames.
- Match the neighbouring code. Rules: [`../AGENTS.md`](../AGENTS.md#project-rules).
- Add or update tests; a bug fix starts with a test that fails ([fix regression contract](TESTING.md#fix-regression-contract)).
- Text a person reads goes in the locale files, Spanish first, English in step.
- Schema changes are new Alembic migrations.
- A new dependency needs a reason in the pull request.

## 4. Self-review

Read your own diff as a reviewer would, before anyone else does:

- Does it do what the issue asked, and only that?
- Is there a second copy of logic that already exists?
- Do the tests prove behaviour, or only repeat the implementation?
- Any real names, recordings, paths, secrets or debug leftovers? (`make check-private` catches some, not all.)
- Comments: only the non-obvious *why*, one or two lines.

## 5. Checks and runtime proof

Run the checks for what you touched ([`TESTING.md`](TESTING.md#which-checks)). Then exercise the change for real in
`npm run desktop:dev` or the built extension, with synthetic audio. For a screen, take screenshots in light and dark
mode, and at a narrow width if the screen can be narrow. Whatever you could not exercise, write it down as `UNVERIFIED`.

## 6. Pull request

Open it against `main` and fill in the template:

- **What and why**, with `Closes #N`.
- **Verification:** the exact commands and their results, what you checked by hand, what is `UNVERIFIED`.
- **Docs impact:** `updated` with the paths, or `none` with a concrete reason. Check `README.md`, `CONTRIBUTING.md`,
  `AGENTS.md`, `rules/` and `SECURITY.md`.
- Screenshots for UI changes. Never of a real meeting.

CI runs the backend tests, the portal and extension tests and builds, and the public-safe check. A red CI is fixed in
the branch; do not ask for review on red.

## 7. Review and merge

- A maintainer reviews. Findings are concrete: what is wrong, where, and why it matters.
- Address each finding or answer it; push new commits instead of force-pushing during review.
- The maintainer merges with a squash; the commit title follows the conventional-commit form.
- Delete your branch after the merge.

## Changes that need extra care

| Change | Also do |
|---|---|
| Anything that sends data out of the Mac | Show it to the person before it happens; describe it in `SECURITY.md` if it is a new path. |
| Ports, pairing, the capability token, the updater allow-list | Explain the threat model in the pull request; add a test for the refusal case. |
| Database schema | A new migration, tested on an existing database; never edit a shipped one. |
| Models or components | New SHA-256 in `scripts/engines/model-catalog.json`; licence added to `THIRD_PARTY_NOTICES.md`. |
| Release, packaging, landing | Follow [`RELEASE.md`](RELEASE.md). |
