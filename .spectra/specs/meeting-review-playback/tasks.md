# Implementation Plan — Meeting Review Playback

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | RED: source inventory and authenticated retrieval contracts | T-1, T-3 | None |
| 2 | GREEN: persistence, ingestion, and authorized playback/transcript APIs | T-2, T-4 | T-1 → T-2; T-2 and T-3 → T-4 |
| 3 | RED: frontend data mapping and playback-controller behavior | T-5, T-7 | T-4 → T-5; T-7 has no prerequisite |
| 4 | GREEN: frontend mapping and playback controller | T-6, T-8 | T-5 → T-6; T-7 → T-8 |
| 5 | RED: playback view, controls, and error behavior | T-9 | T-6, T-8 |
| 6 | GREEN: meeting playback view | T-10 | T-9 |
| 7 | Storage delivery integration contract | T-11 | T-4 |
| 8 | Browser E2E test infrastructure and RED trial test | T-12, T-13 | T-12; T-10 → T-13 |
| 9 | GREEN development-only trial fixture route | T-14 | T-13 |

The dependency graph contains only mandatory RED-before-GREEN edges and real data/API prerequisites. T-1 and T-3 are independent. T-2 waits for T-1; T-4 waits for both T-2 (persisted source inventory) and T-3 (route contract tests). T-5 waits for T-4, while controller test task T-7 is independent of API mapping; T-6 and T-8 each wait only for their corresponding RED task. T-9 waits for T-6 and T-8. T-11 waits for T-4 and is otherwise independent of frontend work. T-12 enables a frontend real-browser test runner; T-13 requires that runner and the view from T-10, then remains RED until T-14 adds the development-only trial route/link and fixture.

## Phase 1: RED — Persistence and API Contracts

### T-1: Add failing source-inventory migration and ingestion tests

**Tracking:** Issue #299 · Card `task_4fbc236854b540d2` · PR #311

**Files:** `backend/tests/test_migration.py`; `backend/tests/ingestion/test_playback_source_ingestion.py` (new); `extension/src/core/capture.test.ts`.

**Production seams under test:** The new migration under `backend/alembic/versions/` and `RecordingMediaSource`/`SessionRecording` in `backend/app/infra/models.py`; `IngestionData` in `backend/app/ingestion/schemas.py` and the validation/persistence path in `backend/app/ingestion/router.py` and `service.py`; the extension capture helper in `extension/src/core/capture.ts` and its single-object upload hand-off in `extension/src/background.ts`. Assert the capture helper observes `MediaStream` video tracks before constructing the upload and that the ingestion boundary rejects invalid presence/offset metadata before storage.

**Action:** Add synthetic RED tests for migration from revision `008_speaker_review_aggregate`: backfill exactly one `RecordingMediaSource` audio row per existing `audio_ref`, one `RecordingMediaSource` video row per non-null `video_ref`, initialize every legacy recording's `video_presence` to `unknown` regardless of MIME or refs, leave unavailable legacy MIME/offset null, preserve original refs through downgrade/re-upgrade, and reject duplicate `(recording_id, kind, object_ref)`. Add capture tests proving observed `MediaStream` video-track presence is reported before the existing interleaved single-object upload is constructed. Add ingestion tests requiring explicit metadata consistent with capture mode: `muxed` only for the single-object interleaved path with an observed video track; `absent` only when capture observed no video; `separate` only with a distinct video object and finite signed integer `video_offset_ms`; reject missing/inconsistent metadata with 422 before persistence or media storage. Do not use real recordings or infer presence from MIME, missing `video_ref`, or recording association.

**Acceptance evidence:** New migration/ingestion tests fail against the pre-feature persistence contract for the missing inventory, `video_presence` and offset validation; capture test fails because no explicit track-presence metadata is reported. Keep test results synthetic.

**Validation:** `cd backend && pytest tests/test_migration.py tests/ingestion/test_playback_source_ingestion.py`; `cd extension && npm run test`.

**Dependencies:** None

### T-2: Implement recording source inventory and offset persistence

**Tracking:** Issue #300 · Card `task_939e38b11c53404d` · PR #320

**Files:** `backend/app/infra/models.py`; `backend/app/ingestion/schemas.py`, `backend/app/ingestion/router.py`, `backend/app/ingestion/service.py`; new migration under `backend/alembic/versions/` after `008_speaker_review_aggregate`; `extension/src/background.ts` and the capture helper used by that path.

**Action:** Implement `RecordingMediaSource` with UUID id, cascading recording FK, `audio`/`video` kind, private object reference, nullable MIME/dimensions/signed video offset, quality label, and uniqueness constraint. Add non-null `SessionRecording.video_presence` (`muxed`, `separate`, `absent`, `unknown`) with server default `unknown`; migrate every existing recording to `unknown` without deriving state from MIME or refs and preserve original refs on downgrade/re-upgrade. Make the existing extension's single interleaved upload report `muxed` only when its captured `MediaStream` actually contains a video track, otherwise report `absent`; persist the explicit evidence. Accept `separate` only with a distinct video object and measured signed integer offset; reject missing/inconsistent metadata with 422 before media storage or persistence. Do not add a new producer, infer offsets, or infer video presence from MIME or absent source rows.

**Acceptance evidence:** `cd backend && pytest tests/test_migration.py tests/ingestion/test_playback_source_ingestion.py` and `cd extension && npm run test` pass, including migration round-trip, capture track evidence, presence-mode validation, signed-offset validation, duplicate rejection, and rejection before media storage.

**Dependencies:** T-1

## Phase 2: RED — Authorized Retrieval Contract

### T-3: Add failing manifest and transcript ownership route tests

**Tracking:** Issue #301 · Card `task_43a6ab934e754109` · PR #476

**Files:** `backend/tests/meetings/test_playback_manifest.py`; `backend/tests/meetings/test_transcript_turn_id.py`

**Production routes under test:** `backend/app/meetings/router.py` exposes `GET /api/v1/meetings/{meeting_id}/playback` (`get_playback_manifest`) and `GET /api/v1/meetings/{meeting_id}/transcript` (`get_transcript`). Exercise their authenticated meeting-ownership boundary and playback source signing through these HTTP routes, not an isolated test-only handler.

**Action:** Add synthetic route tests for owner success, missing/invalid JWT (401), absent and non-owned meeting indistinguishable 404, no recording/playable source, one versus multiple video choices, and confirmation that every legacy row (`video_presence=unknown`), including null MIME and absent `video_ref`, is audio-only. Assert that only explicit persisted `muxed` evidence for the single-object capture mode returns `muxed_video_source`; `absent` returns no video sources; `separate` returns only rows with signed offsets. Verify signed positive/negative offsets, authorized signing with TTL 3600, no raw refs in responses, and transcript ownership/non-disclosure.

**Acceptance evidence:** Tests fail before implementation for the absent playback manifest and/or missing transcript ownership check; unauthorized cases assert no signing and no transcript/object reference disclosure.

**Validation:** `cd backend && pytest tests/meetings/test_playback_manifest.py tests/meetings/test_transcript_turn_id.py`.

**Dependencies:** None

### T-4: Implement authorized playback manifest and transcript ownership check

**Tracking:** Task done · Issue #302 · Card `task_202c6580874741e6` · PR #481

**Files:** `backend/app/meetings/` route/service/repository/schema modules; existing transcript route/service modules.

**Action:** Add `GET /api/v1/meetings/{meeting_id}/playback`, requiring the current user and ownership check before access to sources or signing. Return same 404 for absent/non-owned meetings; sign only the recording's authorized objects with `temporary_read_url(reference, ttl_seconds=3600)`. Return `video_presence`, mandatory audio, `muxed_video_source` only for explicit `muxed` evidence (same underlying object as audio), and separate video sources only for `separate` rows with known signed offsets; `absent`/`unknown` return audio-only with null muxed source and no video rows. Never expose raw refs. Apply identical ownership checking to transcript retrieval before returning content.

**Acceptance evidence:** `cd backend && pytest tests/meetings/test_playback_manifest.py tests/meetings/test_transcript_turn_id.py` passes, including unauthorized non-disclosure assertions.

**Dependencies:** T-3; T-2 (requires persisted source inventory)

## Phase 3: RED — Frontend Data Mapping and Controller

### T-5: Add failing API mapping and timed-passage contract tests

**Tracking:** Task done · Issue #303 · Card `task_b51714b10bb6489e` · PR #484

**Files:** `frontend/src/api.test.ts` (tests for `getPlaybackManifest` and `getTranscript`).

**Production seam under test:** The authenticated HTTP adapter in `frontend/src/api.ts`, specifically `getPlaybackManifest(meetingId)` and `getTranscript(meetingId)` and their manifest/segment-to-timed-passage mapping. Do not move HTTP access into the playback view.

**Action:** Add synthetic tests for typed `getPlaybackManifest(meetingId)` and `getTranscript(meetingId)` responses. Verify manifest mapping preserves `video_presence` (`muxed`, `separate`, `absent`, `unknown`), nullable `muxed_video_source`, and separate `video_sources` with signed offsets; MIME and missing video rows must not determine mode. Verify `segments` preserve sequence/text while mapping `start_ms`/`end_ms` to `TimedPassage.startMs`/`endMs`; invalid/missing timing retains text but produces no playback action. Handle errors without exposing object-store refs beyond signed URLs.

**Acceptance evidence:** Tests fail against the existing adapter's transcript type/mapping mismatch and absent manifest method.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** T-4

### T-6: Implement typed playback and transcript API mapping

**Tracking:** Task done · Issue #304 · Card `task_8fb3bb8e18dc4583` · PR #526

**Files:** `frontend/src/api.ts` and its API type/test modules.

**Action:** Implement typed retrieval methods for playback manifest and transcript using the existing authenticated HTTP adapter. Map the manifest's `video_presence`, nullable `muxed_video_source`, and separate `video_sources` without inferring mode from MIME or missing rows. Correct mapping of ordered `segments` into timed passages; preserve source text/order and exclude invalid timing from time-linked actions without deleting text. Keep all web HTTP access within the adapter.

**Acceptance evidence:** `cd frontend && npm run test` passes the new mapping and manifest tests.

**Dependencies:** T-5

### T-7: Add failing playback-controller RED tests

**Tracking:** Issue #305 · Card `task_a03f9dcab3d24308`

**Files:** `frontend/src/components/__tests__/PlaybackController.test.ts`.

**Production seam under test:** `frontend/src/components/PlaybackController.ts`: exercise the design's `findPassageAt(passages, currentTimeMs)` entry point and the controller's media-event/state/control behavior (including passage actions that seek to `startMs` and play). The tests target the production module, not a test-only replacement.

**Action:** Add tests for valid interval matching (half-open `[startMs,endMs)`), first supplied matching passage on overlap, gaps, invalid timing, empty input, seek/pause/resume/rate/volume/mute state, active passage changes and clear-on-no-match. Use synthetic controller inputs for each `video_presence` mode: `muxed` uses one media clock; `absent`/`unknown` (including legacy null MIME/no video rows) use audio only; `separate` uses paired media only when a signed offset is present. Cover paired audio/video alignment, signed offset formula, positive-offset wait, correction only above 250 ms, and audio as authoritative clock.

**Acceptance evidence:** Tests fail before controller implementation for the expected absent controller behavior.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** None

## Phase 4: GREEN — Data Mapping and Playback Controller

### T-8: Implement playback controller and passage matching

**Tracking:** Issue #306 · Card `task_0b950661c7f2410f` · PR #313 · Status: done

**Files:** `frontend/src/components/PlaybackController.ts` and its unit tests.

**Action:** Implement typed `TimedPassage`, `MediaSourceOption`, `PlaybackState`, and video-presence mode behavior. Select exactly one native video element with audio for explicit `muxed`; select audio alone for `absent`/`unknown`; use authoritative audio plus muted separate video only for `separate` sources with signed offsets. Derive the active passage from the authoritative media clock, use half-open intervals and first-match order, and clear the active passage when no valid interval matches. Implement paired synchronization, signed-offset formula, positive-offset pause, >250 ms drift correction, and consistent controls. Handle rejected play promises as paused/error.

**Acceptance evidence:** `cd frontend && npm run test` passes controller tests for design properties 1, 2, 3, 5, and 6 and defined playback error behavior.

**Dependencies:** T-7

## Phase 5: RED — Playback View

### T-9: Add failing meeting playback view tests

**Tracking:** Task done · Issue #307 (closed after verification 2026-11-13) · Historical card `task_91e0bb5a24b14959` (unavailable in APX) · RED commit `496fb4c33ecafbda9ffa100a8c0d194edddf955f` · PR #594 (merged 2026-10-30, merge `46c8605d4dc635655838b33b98f11a67b7316053`).

**Reconciliation evidence (2026-11-13):** Verified the RED commit is an ancestor of `origin/main` `41ab5f4017b9a6547b42aef8630ff41999f0557e`. In a separate worktree at that RED commit, `npm run test --workspace frontend -- src/components/__tests__/MeetingPlaybackView.test.tsx` exits 1 during collection because `MeetingPlaybackView` does not yet exist; this is missing-seam RED evidence, not a behavioral assertion failure. At current main, `npm run test --workspace frontend` passes 94 tests in 11 files, including all 14 playback-view tests; `npm run typecheck --workspaces` passes all three workspaces. Known jsdom `HTMLMediaElement.pause` warnings remain. This closes only the already-integrated synthetic component-test task, not real-media or product acceptance, and does not close T-13/T-14. Issue #308 is the GREEN task closed by PR #594, not a PR number.

**Files:** `frontend/src/components/__tests__/MeetingPlaybackView.test.tsx` (new).

**Production seam under test:** Render `frontend/src/components/MeetingPlaybackView.tsx` with supplied meeting media and timed transcript data; exercise its native media element and accessible playback/passage controls through user events, and assert its integration with `PlaybackController.ts` for seek, play/pause, clock-driven highlighting and source selection. The view receives data rather than fetching directly; API mapping is covered by T-5/T-6.

**Action:** Add synthetic component tests for seek, pause/resume, speed, volume, mute, passage play, and active-passage highlight/scroll behavior. Assert source selection exists only for multiple playable separate video options and preserves audio source and position. Test all modes: explicit `muxed` evidence renders the same single asset in one native video element with its own audio/timestamps; `absent` and every legacy `unknown` manifest (including null MIME and no `video_ref`/video rows) render audio-only and never infer muxed playback; `separate` uses authoritative audio plus muted video only when its offset is known. Also cover missing-offset legacy video exclusion, metadata-loading disabled controls, one URL refresh at saved time then accessible error/stop on failure, paired startup failures pausing both elements, and accessible empty/unavailable/error states. Assert no editing, library, notes, summary, metadata, or other excluded controls.

**Acceptance evidence:** Tests fail against the pre-feature meeting review view for the missing approved playback behaviors.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** T-6, T-8

## Phase 6: GREEN — Meeting Playback View

### T-10: Implement accessible meeting playback view

**Tracking:** Task done · Issue #308 · Card `task_6a271652b2c34130` · PR #594

**Visibility follow-up:** Task done · Issue #680 · Card `task_e1f49584919a4ca9` · PR #682

**Files:** `frontend/src/components/MeetingPlaybackView.tsx` (new); integrated at `frontend/src/App.tsx` transcript view route (existing `TranscriptView`, mounted on the meeting review path) and consumes `getPlaybackManifest`/`getTranscript` from `frontend/src/api.ts` plus `PlaybackController` from `frontend/src/components/PlaybackController.ts`.


**Action:** Add the view around the playback controller and typed adapter data. Select the media mode strictly from persisted `video_presence`: explicit `muxed` plays the `muxed_video_source` in one native video element with its own audio/timestamps; `absent` and `unknown` (including legacy null-MIME rows and missing video refs) are audio-only; `separate` uses authoritative audio plus muted video only when signed offset is known. Provide accessible controls for seek, pause/resume, speed, volume, mute and conditional separate-video quality selection; render transcript/active passage from playback time; passage action seeks to `startMs` and requests play. Disable controls during unavailable metadata, retain text with invalid timing but no time-linked controls, and show accessible loading/empty/error states. Add no excluded feature.

**Acceptance evidence:** `cd frontend && npm run test` and `cd frontend && npm run typecheck` pass, including T-9 tests and the existing frontend suite/typecheck.

**Dependencies:** T-9

## Phase 7: Storage Delivery Integration Contract

### T-11: Verify signed-source range and CORS delivery contract

**Tracking:** Task done · Issue #309 · Card `task_0cfb4d4d978e4d7e` · PR #485

**Files:** `backend/tests/meetings/test_playback_storage_integration.py`.

**Action:** Add/run the designed integration test against disposable S3-compatible storage: fetch a signed source URL with HTTP `Range`, assert 206, correct `Content-Range` and bytes; run browser-origin CORS preflight and GET from the configured frontend origin. Do not introduce a public URL or unauthenticated fallback if delivery configuration fails.

**Acceptance evidence:** The integration test passes with disposable storage; a failed/missing range or CORS configuration is recorded as a deployment blocker, never bypassed.

**Validation:** `cd backend && pytest tests/meetings/test_playback_storage_integration.py` with disposable S3-compatible storage configured.

**Dependencies:** T-4

## Phase 8: RED — Real-Browser Trial Readiness

### T-12: Establish frontend Playwright E2E runner

**Tracking:** Issue #500 · Card `task_ec09f84fb1ec4f00`.

**Files:** `frontend/package.json`; frontend Playwright configuration under `frontend/`; root dependency lockfile.

**Action:** Add a frontend-local Playwright runner configuration using the repository's existing `@playwright/test` convention, including a Vite development server `webServer` configuration. Configure `frontend/tests/e2e/` as the frontend E2E directory and expose the script used below. Keep this runner isolated to frontend browser tests; do not alter extension E2E configuration.

**Acceptance evidence:** A temporary runner smoke test launches the Vite app and observes its root page; remove the smoke test when T-13 adds the feature-specific browser test.

**Validation:** `npm run test:e2e --workspace frontend`.

**Dependencies:** None

### T-13: Add failing real-browser trial playback E2E test

**Tracking:** Issue #501 · Card `task_c7bca3a1ade84745`.

**Files:** `frontend/tests/e2e/meeting-review-playback-trial.spec.ts`; `frontend/src/App.tsx`; `frontend/src/components/MeetingPlaybackView.tsx`.

**Production seam under test:** The Vite-development-only root link and `/_trial/meeting-review-playback` route in `frontend/src/App.tsx`, which mounts `MeetingPlaybackView` with the synthetic fixture. Navigate through that link to the exact route; T-13 remains RED until T-14 adds it, without bypassing the authenticated route for real meeting media.

**Action:** Write a real-browser test that starts at `/`, follows the development-only trial link, and expects the trial view, actual fixture WAV with finite non-zero duration, and all three synthetic transcript passages. Use `data-testid="playback-media"` and visible Play/passage controls only; do not call `HTMLMediaElement.play()` or set `currentTime` in test code. Register listeners before clicks; assert Play unpauses and advances media time by at least 500 ms within 5 seconds, then assert the second passage action (`startMs=4000`) emits `seeked` within 250 ms of 4.000 s and subsequently `playing` while unpaused. This task must demonstrate RED before T-14 adds the fixture route/link.

**Acceptance evidence:** The browser test runs and fails specifically because the development-only fixture route/link and WAV are not yet present; runner, browser, and app startup must succeed.

**Validation:** `npm run test:e2e --workspace frontend`.

**Dependencies:** T-10 (requires the rendered playback view and its visible media/passage controls); T-12 (requires the configured browser runner).

## Phase 9: GREEN — Development-Only Trial Fixture

### T-14: Add synthetic WAV, timed transcript, and Vite-only trial route

**Tracking:** Issue #502 · Card `task_d6be0be2de424f71`.

**Files:** `frontend/src/App.tsx`; `frontend/tests/e2e/meeting-review-playback-trial.spec.ts`; synthetic fixture asset and transcript module under `frontend/`.

**Action:** Add a checked-in synthetic WAV with a matching three-passage timed transcript whose intervals cover the media timeline. In the existing app, mount `MeetingPlaybackView` at `/_trial/meeting-review-playback` only in Vite development mode and provide a development-only root link. Load fixture data directly for this trial path; do not change the normal authenticated API-backed route, add the path to meeting navigation, or expose route/link in production builds. Make the T-13 browser assertions pass through user-operated controls and real browser media events.

**Acceptance evidence:** T-13 passes against the actual checked-in WAV and all three passages, exercising play progress and second-passage seek/play timing. After a production build, an automated bundle assertion confirms the development-only route target `/_trial/meeting-review-playback` is absent from `frontend/dist`, demonstrating that neither the route nor its linked entry point is shipped. Report this technical E2E result separately; it does not alter frozen product acceptance or participant criteria.

**Validation:** `npm run test:e2e --workspace frontend`; `npm run build --workspace frontend && ! grep -R -Fq '/_trial/meeting-review-playback' frontend/dist`.

**Dependencies:** T-13
