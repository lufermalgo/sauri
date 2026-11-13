# T16 #655 — GREEN frontend, 2026-11-13

## Authority and candidate

Approved bugfix/design/tasks for `fix-transcript-word-fragments`; scope T16. Base `baea619`, branch `feature/issue-655-transcript-turns-t16`. Predecessor RED `f8f4f40966ddc369ab22e9dcb9d8a0615086a705` from PR #847 is preserved as cherry-pick `a350eb4`; source commit remains untouched. T15 test blocks are unchanged. Original RED evidence: `qa-t15-red.md` (15 failures, 32 passes). T2 grouping is integrated; T14 backend contract is implemented in PR #850 but NOT integrated or fully GREEN. This candidate prepares the independent frontend, not an end-to-end delivery or authorization to bypass T14.

## Changes

- GET and PUT speaker review share snake_case→camelCase adaptation, retain the full label map and normalize numeric revision IDs. `expected_version` is supported along with the older `version`; legacy missing versions are not fabricated and cannot be submitted.
- Grouping and speaker presentation use only known speaker IDs from the active generation with finite positive overlap. Legacy or unknown/zero/negative/null evidence remains separate and uncertain.
- Transcript labels come only from the same-revision `labelsBySpeakerId`, then the diarization speaker label, then `Speaker N`. Pending items never supply transcript labels. Historical review controls are not displayed as active.
- `not_reconstructible` reports unavailable original audio and preserves source fragments ungrouped. A newer pending/failed attempt does not erase the completed generation.
- Untimed source text stays visible, ungrouped, with disabled playback instead of an invented timestamp.
- Existing pre-T15 fixtures now supply revision/overlap/full label map instead of asserting the superseded legacy attribution contract. Assertions were retained. Added untimed-text and historical-controls regression cases; did not weaken T15.

## Executed validation

From the isolated worktree:

- `npm ci --ignore-scripts`: dependencies installed; existing Git hooks verified active (`core.hooksPath=.githooks`); no bypass on commits/pushes.
- `npm run test --workspace=frontend -- src/api.test.ts src/components/TranscriptView.test.tsx`: **49 passed**.
- `npm run test --workspace=frontend`: **113 passed, 11 files**. jsdom prints its known not-implemented media-play messages; they do not represent real media playback validation.
- `npm run typecheck`: **PASS** extension, frontend, shared-types.
- `npm run build --workspace=frontend`: **PASS**, 40 modules transformed.
- `git diff --check`: **PASS**.

No Rust/backend code changed. No Docker resources created.

## Interactive check (APX browser)

Opened `http://127.0.0.1:5187` in APX tab `t13`; temporary harness lives outside the repository. It renders the actual production TranscriptView and API adapter against controlled synthetic HTTP replies, not a substitute implementation. No private media, credentials or identity samples. Playback manifest deliberately responds 404; the visible unavailable-media message is expected, and audio/seek fidelity is NOT certified here (T18).

Clicked naming action: selected synthetic name remained on the grouped passage after PUT removed the pending item. Checked completed state and reload; historical revision used `Speaker 1`, not the prior name, and no historical review controls appeared after the correction. Checked unavailable-audio state: Spanish terminal explanation, two original fragments, both `Speaker N`. Checked untimed source: text preserved, `Sin marca de tiempo`, disabled play action. Pictures captured with `browser_snapshot` for named, historical, untimed and not-reconstructible states. No browser error overlay observed; intentional media 404 remains a fixture limitation, not backend evidence.

## Pending gates

This is frontend GREEN only. Fer retains merge. PR #850/T14 requires its exact readiness gate before integration; full backend/concurrency validation and T19/T20 security gate remain unchanged. T18 must integrate grouped playback intervals without closing gaps. No product acceptance, real inference accuracy, PostgreSQL persistence, S3 or full deployed portal validation is claimed.
