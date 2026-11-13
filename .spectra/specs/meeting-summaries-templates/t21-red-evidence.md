# T21 / #289 — RED copy/download controls

Pre-implementation candidate: `ff5c9386e6c37c815b02e654fb78988dafa1dcaf` (T20 PR #876). T19 RED `e1f3a5f` remains an ancestor. No production code is changed by this delivery. The test commit must remain an ancestor of T22 GREEN.

## Command and actual result

From `frontend/`:

```sh
npm run typecheck
npm run test -- --run src/components/SummarySection.test.tsx
```

- Typecheck: PASS.
- Vitest: **18 collected, 14 passed, 4 failed**, 0 collection errors, 0 skipped (689 ms).
- All four failures are expected missing capability assertions: accessible Copy button absent for available summary; Copy button absent for clipboard-success case; Copy button absent for clipboard-rejection/retry case; Download button absent for export-content case.
- The 13 predecessor tests still pass, as does the new negative case preventing enabled export actions without a successful artifact.
- `git diff --check`: PASS.

## Covered behavior and boundaries

Tests use the existing synthetic UI/API seam; they do not claim real HTTP/provider/browser verification. Required topic and every key point must survive clipboard/download. Existing successful summaries remain exportable during a subsequent pending generation. Clipboard rejection must not claim success or lose the displayed artifact and must permit retry.

The download test observes browser boundaries (Blob URL or data URL and anchor click), not a backend export endpoint. It does not prescribe filename, extension, MIME type or a particular serialization. T22 still requires the design D8/D11/D12 boundary to be respected: no unspecified format may be inferred without product clarification.

No node dependencies were downloaded or changed; the existing installed workspace dependencies were reused through temporary local symlinks removed after validation. No Docker environment was needed. This RED candidate is not an integrable production delivery. Fer retains merge authority and GitHub CI must not be bypassed.
