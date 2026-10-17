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

The dependency graph contains only mandatory RED-before-GREEN edges and real data/API prerequisites. T-1 and T-3 are independent. T-2 waits for T-1; T-4 waits for both T-2 (persisted source inventory) and T-3 (route contract tests). T-5 waits for T-4, while controller test task T-7 is independent of API mapping; T-6 and T-8 each wait only for their corresponding RED task. T-9 waits for T-6 and T-8. T-11 waits for T-4 and is otherwise independent of frontend work.

## Phase 1: RED — Persistence and API Contracts

### T-1: Add failing source-inventory migration and ingestion tests

**Files:** `backend/tests/test_migration.py`; `backend/tests/ingestion/test_playback_source_ingestion.py` (new); `extension/src/core/capture.test.ts`.

**Action:** Add synthetic RED tests for migration from revision `008_speaker_review_aggregate`: backfill exactly one `Original` audio source per existing `audio_ref`, one video source per non-null `video_ref`, initialize every legacy recording's `video_presence` to `unknown` regardless of MIME or refs, leave unavailable legacy MIME/offset null, preserve original refs through downgrade/re-upgrade, and reject duplicate `(recording_id, kind, object_ref)`. Add capture tests proving observed `MediaStream` video-track presence is reported before the existing interleaved single-object upload is constructed. Add ingestion tests requiring explicit metadata consistent with capture mode: `muxed` only for the single-object interleaved path with an observed video track; `absent` only when capture observed no video; `separate` only with a distinct video object and finite signed integer `video_offset_ms`; reject missing/inconsistent metadata with 422 before persistence or media storage. Do not use real recordings or infer presence from MIME, missing `video_ref`, or recording association.

**Acceptance evidence:** New migration/ingestion tests fail against the pre-feature persistence contract for the missing inventory, `video_presence` and offset validation; capture test fails because no explicit track-presence metadata is reported. Keep test results synthetic.

**Validation:** `cd backend && pytest tests/test_migration.py tests/ingestion/test_playback_source_ingestion.py`; `cd extension && npm run test`.

**Dependencies:** None

### T-2: Implement recording source inventory and offset persistence

**Files:** `backend/app/infra/models.py`; `backend/app/ingestion/schemas.py`, `backend/app/ingestion/router.py`, `backend/app/ingestion/service.py`; new migration under `backend/alembic/versions/` after `008_speaker_review_aggregate`; `extension/src/background.ts` and the capture helper used by that path.

**Action:** Implement `RecordingMediaSource` with UUID id, cascading recording FK, `audio`/`video` kind, private object reference, nullable MIME/dimensions/signed video offset, quality label, and uniqueness constraint. Add non-null `SessionRecording.video_presence` (`muxed`, `separate`, `absent`, `unknown`) with server default `unknown`; migrate every existing recording to `unknown` without deriving state from MIME or refs and preserve original refs on downgrade/re-upgrade. Make the existing extension's single interleaved upload report `muxed` only when its captured `MediaStream` actually contains a video track, otherwise report `absent`; persist the explicit evidence. Accept `separate` only with a distinct video object and measured signed integer offset; reject missing/inconsistent metadata with 422 before media storage or persistence. Do not add a new producer, infer offsets, or infer video presence from MIME or absent source rows.

**Acceptance evidence:** `cd backend && pytest tests/test_migration.py tests/ingestion/test_playback_source_ingestion.py` and `cd extension && npm run test` pass, including migration round-trip, capture track evidence, presence-mode validation, signed-offset validation, duplicate rejection, and rejection before media storage.

**Dependencies:** T-1

## Phase 2: RED — Authorized Retrieval Contract

### T-3: Add failing manifest and transcript ownership route tests

**Files:** `backend/tests/meetings/test_playback_manifest.py`; `backend/tests/meetings/test_transcript_turn_id.py`

**Action:** Add synthetic route tests for owner success, missing/invalid JWT (401), absent and non-owned meeting indistinguishable 404, no recording/playable source, one versus multiple video choices, and confirmation that every legacy row (`video_presence=unknown`), including null MIME and absent `video_ref`, is audio-only. Assert that only explicit persisted `muxed` evidence for the single-object capture mode returns `muxed_video_source`; `absent` returns no video sources; `separate` returns only rows with signed offsets. Verify signed positive/negative offsets, authorized signing with TTL 3600, no raw refs in responses, and transcript ownership/non-disclosure.

**Acceptance evidence:** Tests fail before implementation for the absent playback manifest and/or missing transcript ownership check; unauthorized cases assert no signing and no transcript/object reference disclosure.

**Validation:** `cd backend && pytest tests/meetings/test_playback_manifest.py tests/meetings/test_transcript_turn_id.py`.

**Dependencies:** None

### T-4: Implement authorized playback manifest and transcript ownership check

**Files:** `backend/app/meetings/` route/service/repository/schema modules; existing transcript route/service modules.

**Action:** Add `GET /api/v1/meetings/{meeting_id}/playback`, requiring the current user and ownership check before access to sources or signing. Return same 404 for absent/non-owned meetings; sign only the recording's authorized objects with `temporary_read_url(reference, ttl_seconds=3600)`. Return `video_presence`, mandatory audio, `muxed_video_source` only for explicit `muxed` evidence (same underlying object as audio), and separate video sources only for `separate` rows with known signed offsets; `absent`/`unknown` return audio-only with null muxed source and no video rows. Never expose raw refs. Apply identical ownership checking to transcript retrieval before returning content.

**Acceptance evidence:** `cd backend && pytest tests/meetings/test_playback_manifest.py tests/meetings/test_transcript_turn_id.py` passes, including unauthorized non-disclosure assertions.

**Dependencies:** T-3; T-2 (requires persisted source inventory)

## Phase 3: RED — Frontend Data Mapping and Controller

### T-5: Add failing API mapping and timed-passage contract tests

**Files:** Frontend API adapter tests for `frontend/src/api.ts`; transcript mapping tests in the existing frontend test structure.

**Action:** Add synthetic tests for typed `getPlaybackManifest(meetingId)` and `getTranscript(meetingId)` responses. Verify manifest mapping preserves `video_presence` (`muxed`, `separate`, `absent`, `unknown`), nullable `muxed_video_source`, and separate `video_sources` with signed offsets; MIME and missing video rows must not determine mode. Verify `segments` preserve sequence/text while mapping `start_ms`/`end_ms` to `TimedPassage.startMs`/`endMs`; invalid/missing timing retains text but produces no playback action. Handle errors without exposing object-store refs beyond signed URLs.

**Acceptance evidence:** Tests fail against the existing adapter's transcript type/mapping mismatch and absent manifest method.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** T-4

### T-6: Implement typed playback and transcript API mapping

**Files:** `frontend/src/api.ts` and its API type/test modules.

**Action:** Implement typed retrieval methods for playback manifest and transcript using the existing authenticated HTTP adapter. Map the manifest's `video_presence`, nullable `muxed_video_source`, and separate `video_sources` without inferring mode from MIME or missing rows. Correct mapping of ordered `segments` into timed passages; preserve source text/order and exclude invalid timing from time-linked actions without deleting text. Keep all web HTTP access within the adapter.

**Acceptance evidence:** `cd frontend && npm run test` passes the new mapping and manifest tests.

**Dependencies:** T-5

### T-7: Add failing playback-controller RED tests

**Files:** `frontend/src/**/__tests__/PlaybackController.test.ts` (place in the established frontend test location).

**Action:** Add tests for valid interval matching (half-open `[startMs,endMs)`), first supplied matching passage on overlap, gaps, invalid timing, empty input, seek/pause/resume/rate/volume/mute state, active passage changes and clear-on-no-match. Use synthetic controller inputs for each `video_presence` mode: `muxed` uses one media clock; `absent`/`unknown` (including legacy null MIME/no video rows) use audio only; `separate` uses paired media only when a signed offset is present. Cover paired audio/video alignment, signed offset formula, positive-offset wait, correction only above 250 ms, and audio as authoritative clock.

**Acceptance evidence:** Tests fail before controller implementation for the expected absent controller behavior.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** None

## Phase 4: GREEN — Data Mapping and Playback Controller

### T-8: Implement playback controller and passage matching

**Files:** `frontend/src/components/PlaybackController.ts` and its unit tests.

**Action:** Implement typed `TimedPassage`, `MediaSourceOption`, `PlaybackState`, and video-presence mode behavior. Select exactly one native video element with audio for explicit `muxed`; select audio alone for `absent`/`unknown`; use authoritative audio plus muted separate video only for `separate` sources with signed offsets. Derive the active passage from the authoritative media clock, use half-open intervals and first-match order, and clear the active passage when no valid interval matches. Implement paired synchronization, signed-offset formula, positive-offset pause, >250 ms drift correction, and consistent controls. Handle rejected play promises as paused/error.

**Acceptance evidence:** `cd frontend && npm run test` passes controller tests for design properties 1, 2, 3, 5, and 6 and defined playback error behavior.

**Dependencies:** T-7

## Phase 5: RED — Playback View

### T-9: Add failing meeting playback view tests

**Files:** `frontend/src/**/__tests__/MeetingPlaybackView.test.tsx` (place in the established frontend test location).

**Action:** Add synthetic component tests for seek, pause/resume, speed, volume, mute, passage play, and active-passage highlight/scroll behavior. Assert source selection exists only for multiple playable separate video options and preserves audio source and position. Test all modes: explicit `muxed` evidence renders the same single asset in one native video element with its own audio/timestamps; `absent` and every legacy `unknown` manifest (including null MIME and no `video_ref`/video rows) render audio-only and never infer muxed playback; `separate` uses authoritative audio plus muted video only when its offset is known. Also cover missing-offset legacy video exclusion, metadata-loading disabled controls, one URL refresh at saved time then accessible error/stop on failure, paired startup failures pausing both elements, and accessible empty/unavailable/error states. Assert no editing, library, notes, summary, metadata, or other excluded controls.

**Acceptance evidence:** Tests fail against the pre-feature meeting review view for the missing approved playback behaviors.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** T-6, T-8

## Phase 6: GREEN — Meeting Playback View

### T-10: Implement accessible meeting playback view

**Files:** `frontend/src/components/MeetingPlaybackView.tsx` (new); existing meeting review route/view integration point.

**Action:** Add the view around the playback controller and typed adapter data. Select the media mode strictly from persisted `video_presence`: explicit `muxed` plays the `muxed_video_source` in one native video element with its own audio/timestamps; `absent` and `unknown` (including legacy null-MIME rows and missing video refs) are audio-only; `separate` uses authoritative audio plus muted video only when signed offset is known. Provide accessible controls for seek, pause/resume, speed, volume, mute and conditional separate-video quality selection; render transcript/active passage from playback time; passage action seeks to `startMs` and requests play. Disable controls during unavailable metadata, retain text with invalid timing but no time-linked controls, and show accessible loading/empty/error states. Add no excluded feature.

**Acceptance evidence:** `cd frontend && npm run test` and `cd frontend && npm run typecheck` pass, including T-9 tests and the existing frontend suite/typecheck.

**Dependencies:** T-9

## Phase 7: Storage Delivery Integration Contract

### T-11: Verify signed-source range and CORS delivery contract

**Files:** `backend/tests/meetings/test_playback_storage_integration.py`.

**Action:** Add/run the designed integration test against disposable S3-compatible storage: fetch a signed source URL with HTTP `Range`, assert 206, correct `Content-Range` and bytes; run browser-origin CORS preflight and GET from the configured frontend origin. Do not introduce a public URL or unauthenticated fallback if delivery configuration fails.

**Acceptance evidence:** The integration test passes with disposable storage; a failed/missing range or CORS configuration is recorded as a deployment blocker, never bypassed.

**Validation:** `cd backend && pytest tests/meetings/test_playback_storage_integration.py` with disposable S3-compatible storage configured.

**Dependencies:** T-4
