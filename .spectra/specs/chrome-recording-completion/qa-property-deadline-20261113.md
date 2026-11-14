# T1.1 / T2.1 (#610 / #619): property-run deadline under suite load

Base: origin/main `41ab5f4017b9a6547b42aef8630ff41999f0557e`.
Scope: test-only maintenance of the approved listener-level 100-case properties; no production code, capture behavior, privacy, assertions, generated-case counts or approval gates changed.

## Observed failure and diagnosis

The full extension command initially produced 11 failures / 245 passes and 2 unhandled IndexedDB errors. The three affected files passed together (24/24) when run independently. Limiting full-suite workers to two still produced a **five-second deadline expiration** in the 100-case worker-reload property, followed by duplicate-stop assertions in the next test. That property includes explicit 15ms waits for several worker restarts per case, in addition to real IndexedDB transactions. A timed-out asynchronous property can continue while the following property replaces Chrome and IndexedDB globals.

The test file now sets a local 30-second deadline using Vitest's supported `vi.setConfig`. All eleven tests and all 100-case properties retain their exact assertions and inputs. This addresses deadline exhaustion; it is not proof that every possible scheduling race is eliminated.

## Verification

- Before change: full extension suite 11 failed / 245 passed, 2 unhandled errors.
- Focused original three files: 24 passed.
- Before change with maxWorkers=2/minWorkers=1: 2 failed / 254 passed; log explicitly shows test deadline 5000ms.
- After change, default unfiltered extension suite: **41 files / 256 tests passed**, exit 0; no unhandled errors; 73.88s total.
- `npm run typecheck`: all three workspaces passed.
- `npm run test --workspace sauri-frontend`: 11 files / 94 tests passed. Existing jsdom media-method warnings remain.
- `npm run test --workspace @sauri/shared-types`: 2 tests passed on integrated base before the test-only change.
- `git diff --check`: passed.

No browser-visible change, Docker resources, real-media acceptance, production behavior change, or merge. Fer retains integration. CI must run on the published candidate; account billing restrictions are not bypassed.
