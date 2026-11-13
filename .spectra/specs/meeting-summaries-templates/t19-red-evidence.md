# T19 / #287 — SummarySection RED handoff

- Spec: approved `meeting-summaries-templates` requirements R1/R5 and design §7, correctness P2/P5; tasks T19, predecessor T16 + T18.
- Preimplementation candidate: `791ba673262f13d3b45152353b9861975d51dfa4` (T16 PR #873 `4398c09` plus T18 PR #863 history preserved).
- RED test commit: `e1f3a5f`. File: `frontend/src/components/SummarySection.test.tsx`.
- Executed before any SummarySection implementation, from candidate `frontend/`: `npm run test -- --run src/components/SummarySection.test.tsx`.
- Observed: **10 tests collected, 10 failed, no skips**, each with `Failed to load url /src/components/SummarySection.tsx ... Does the file exist?`. Dynamic import runs inside each test lifecycle; no production stub, type suppression or collection failure hides the absent component. Full captured output is attached to the APX task.
- `npm run typecheck`: **PASS** using project TypeScript configuration. Shared contracts from T18 are real imports.
- `git diff --check`: **PASS**.

## Contract for T20

Implement named `SummarySection` accepting `meetingId` and `hasTranscript` props; replace the lifecycle import with a static import when the real component exists. These props are a technical seam for the design's existing meeting/transcript availability inputs, not a new product rule. API mocks expose the design's `getSummary`, `getLatestSummaryRequest`, `getSummaryRequest`, `requestSummary`, `listTemplates` functions. T20 must separately validate real HTTP snake_case mapping; these mocks are not provider/backend evidence.

Coverage: an independent accessible summary section; intact topic and ordered key-point text; neutral 404 only with no pending/running request; resumption of both pending/running latest events; distinguish other fetch errors; configured-default marker and implicit request (no explicit template ID sent); poll returned event every 3 seconds; refetch on success and stop terminal polling; preserve an older summary on failure and suppress provider details; retry a status network error without marking generation failed; continued polling and unmount cancellation. Copy/download controls are T21/T22; no serialization, MIME, filename, no-default behavior or visual layout is invented.

## Status

RED only, not implemented, not integrated, no UI change to inspect yet. T20 may now start while preserving `e1f3a5f`; T16/T18 integration is still pending Fer. GitHub Actions is externally blocked by account billing/spending limit (run 43411279294 on predecessor PR #873 did not start either job). Local typecheck is not a substitute for required remote controls, and this RED branch's intentional test failures are not an integration candidate. Fer retains all merges.
