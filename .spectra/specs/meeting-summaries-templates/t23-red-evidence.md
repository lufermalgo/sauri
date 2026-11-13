# T23 / #291 — personal template settings RED

Date: 2026-11-13. Executor/reviewer: Ansel. Spec: requirements R3–R5, design §7/D12, tasks T23. No product behavior or UI is implemented by this delivery.

## Candidate and dependencies

- T8 / PR866: `68e81cd236eef5d0da9328a149175b3f9277247b`.
- T18 / PR863: `722287a7c6f0bd725d94c1f2142df596047be512`.
- Combined pre-test candidate: `31e140011e5e3e86a99dace390e4808244eb83b2` (merge preserves both histories).
- Isolated branch/worktree: `feature/issue-291-template-settings-red`, `.worktrees/feature-issue-291-template-settings-red`.
- Only test + spec/evidence changed. No overlap with Nahuel's summary worker files. No production stub or API client implementation.

## Coverage and contract

Seven component tests cover personal template list and single default marking; two successive creates with opaque instructions unchanged; edit form loading and saving; optional category assignment and category reuse; explicit `categoryId: null` for removal on PATCH; inline category creation and selection; default change across categories with the approved void/204 setter client contract.

API mocks implement the exact planned camelCase client signatures (design §7). They are synthetic component boundaries, not evidence of a working API, privacy enforcement or real user experience. HTTP mappings/204 parsing belong to T24. Accessible labels/actions serve as the test interface, not a mandated layout, CSS, template grammar or instruction format. English accessible names match the existing frontend convention. The repository's language-regression hook rejected accented Spanish test strings on the first commit attempt; fixtures and label queries were changed to English and the hook rerun, without disabling any control.

The absent component is imported in the test lifecycle via its source-file URL: all seven tests collect and fail at the missing production module, rather than failing test collection. No TypeScript suppression or fake production component is used. T24 should switch to a static import once the module exists. No seed/default fallback, deletion or foreign-template policy is invented. Ownership enforcement remains backend coverage.

## Observed commands

From `frontend/` in the isolated worktree, using existing root node_modules via a worktree symlink (no install/dependency changes):

```bash
npm run test -- --run src/components/TemplateSettingsView.test.tsx
# exit 1; 1 file failed, 7 collected tests failed.
# Error: Failed to load url .../frontend/src/components/TemplateSettingsView.tsx
# The component is absent on the pre-implementation candidate, as expected.
npm run typecheck
# exit 0, tsc --noEmit.
npm run test -- --exclude src/components/TemplateSettingsView.test.tsx
# exit 0; 11 files, 94 tests passed.
# Existing jsdom media-method 'Not implemented' stderr remains; assertions pass.
git diff --check
# exit 0.
```

Focused RED run and regression outputs are retained as task attachments. A first attempt to redirect the output failed because the per-thread scratch directory did not exist; creating that directory resolved it before either recorded run. No test result is attributed to that failed shell redirection.

## Handoff / limits

T23 RED only. Preserve the exact test commit in the T24 candidate; tests have not been made GREEN and the unfiltered frontend suite is intentionally RED. No visible UI change to inspect, no production generation, integration, deployment or product acceptance claimed. No Docker resources, real user data or services used. Fer retains integration. T24 remains gated by T20 as well as T23/T6/T8/T18; do not edit the shared frontend API client before the T20 boundary is available.
