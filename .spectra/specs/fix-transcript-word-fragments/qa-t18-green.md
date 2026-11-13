# T18 #657 — grouped playback GREEN, 2026-11-13

## Candidate and scope

Approved `fix-transcript-word-fragments` T18. Branch/worktree `feature/issue-657-transcript-turns-t18`, stacked on T16 PR #859 SHA `00e505a829372aed7d1cd85068b3eb3c289b0926`. RED T17 PR #849 commit `81c14677c8547cf09d63d0d9929905af01055c26` preserved as cherry-pick `3a6f2f6`; original is untouched. Existing T2 grouping/interval helpers reused. No backend, storage, inference, retention, shared types or controller clock changes.

## RED and fixture correction

On `3a6f2f6`, `npm run test --workspace=frontend -- src/components/__tests__/MeetingPlaybackView.test.tsx src/components/__tests__/PlaybackController.test.ts`: **4 failed / 29 passed**. Failures are the missing grouped view seam (original evidence `qa-t17-red.md`).

After implementing the view seam: **1 failed / 32 passed**. The remaining play test fired `loadedmetadata` without a finite `duration`; jsdom does not load media, so existing production readiness correctly kept Play disabled. Added only `Object.defineProperty(audio, "duration", { configurable: true, value: 0.3 })` before that event. All original assertions and cases remain. Did NOT weaken the media-readiness guard, mock the controller, remove the test or change expected timing. Real browser metadata/control behavior checked separately below.

## Implementation

- `MeetingPlaybackView` optionally receives `presentationTurns` separately from exact source `passages`. The controller still receives every original valid source interval, unchanged.
- Map the controller's active source passage to `presentationTurnId` for grouped-row highlighting, summary preview and scrolling. In gaps and exclusive ends no source is active, so no grouped row or preview is active.
- The grouped row's play action targets only the first valid source interval, never an outer composed interval. Untimed text remains visible without Play.
- `TranscriptView` wires its source segments through `createPlaybackIntervals` and passes labeled presentation rows derived from the same validated generation. No duplicate text/timing persistence.
- Added a component integration regression: one grouped playback row, highlights at 50ms and 250ms, no highlight at 150ms gap or 300ms exclusive end. This checks actual TranscriptView→MeetingPlaybackView→controller wiring, not just an isolated prop fixture.

## Validation executed

- Normative command above: **33 passed**.
- `npm run test --workspace=frontend`: **120 passed**, 11 files. Existing jsdom not-implemented media messages remain in unrelated tests; no inference of real audio playback from them.
- `npm run typecheck`: **PASS** across extension/frontend/shared-types.
- `npm run build --workspace=frontend`: **PASS**, 40 modules.
- `git diff --check`: **PASS**.

No Rust/backend code modified. No Docker resources created.

## Interactive APX browser

Tab `t13`, `http://127.0.0.1:5187`. Temporary synthetic HTTP harness outside repository loads actual production TranscriptView, adapter, grouping helper, MeetingPlaybackView and controller from this worktree. A generated 12-second PCM WAV supplies real browser metadata and a running media clock, not mocked HTMLMediaElement methods. It contains silence, no speech/private media, and is NOT real-engine or deployed-backend evidence.

- Initial source intervals `[0,3000)` and `[6000,9000)` rendered one grouped playback row. Slider click at 6000ms selected the second source and showed the same active grouped preview. Play-turn seek returned to the first source; Play resumed the real media clock (snapshot observed 8900ms).
- Widened the synthetic gap for a deterministic manual check to `[0,3000)` and `[9000,11000)` with the same 12-second media. At 0ms the grouped preview was active. Clicked the production seek slider to 6000ms: **grouped preview absent**, text still visible, no fabricated continuous highlight.
- Captured APX pictures of first/second source and gap states. No browser error overlay observed after valid WAV replaced the T16 harness's deliberate media 404. The slider typing attempt did not change its value; click was used and actual resulting 6000ms confirmed in snapshot.

The exact unit tests additionally verify overlaps, boundaries, first-interval Play and untimed text. The unchanged server-side revision/readiness/security gates are not certified by this harness.

## Integration status

Prepared frontend GREEN only; Fer retains merge. T16 PR #859 and T14 PR #850 must satisfy their integration gates; final T19 backend/concurrency suite and T20 independent security review still required. Not product acceptance and not certification of real audio attribution or inference quality. No issue auto-close or main merge performed.
