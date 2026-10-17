# Implementation Plan — Meeting Review Playback

## Phase Summary

| Phase | Description | Tasks | Dependencies |
|---|---|---|---|
| 1 | RED: source inventory and authenticated retrieval contracts | T-1, T-3 | None |
| 2 | GREEN: persistence, ingestion, and authorized playback/transcript APIs | T-2, T-4 | T-1 → T-2; T-3 → T-4 |
| 3 | RED: frontend data mapping and playback-controller behavior | T-5, T-7 | T-4 → T-5; T-5 → T-7 |
| 4 | GREEN: frontend mapping and playback controller | T-6, T-8 | T-5 → T-6; T-7 → T-8 |
| 5 | RED: playback view, controls, and error behavior | T-9 | T-6, T-8 |
| 6 | GREEN: meeting playback view | T-10 | T-9 |
| 7 | Storage delivery integration contract | T-11 | T-4 |

The dependency graph contains only mandatory RED-before-GREEN edges and the data/API prerequisites needed by the frontend. T-1 and T-3 are independent. T-2 and T-4 are independent after their respective RED tasks; frontend tasks wait for the authorized API contract. T-11 is independent of frontend work once the manifest route exists.

## Phase 1: RED — Persistence and API Contracts

### T-1: Add failing source-inventory migration and ingestion tests

**Files:** `backend/tests/test_migration.py`; ingestion tests under `backend/tests/ingestion/test_playback_source_ingestion.py` (new)

**Action:** Add synthetic-data tests for migration from revision `008_speaker_review_aggregate`: backfill exactly one `Original` audio source per existing `audio_ref`, one video source per non-null `video_ref`, leave unavailable legacy MIME/offset null, preserve original recording refs through downgrade/re-upgrade, and reject duplicate `(recording_id, kind, object_ref)`. Cover ingestion accepting separate video only with a finite signed integer `video_offset_ms`, rejecting missing/invalid offset with 422 before persistence, and allowing null when no separate video is supplied. Do not use real recordings.

**Acceptance evidence:** The new tests fail against the pre-feature schema/ingestion behavior for the expected missing source-inventory and offset-contract behavior.

**Validation:** `cd backend && pytest tests/test_migration.py tests/ingestion/test_playback_source_ingestion.py`.

**Dependencies:** None

### T-2: Implement recording source inventory and offset persistence

**Files:** Backend recording ORM/model and repository modules; new Alembic migration after `008_speaker_review_aggregate`; ingestion schemas/service and source persistence modules identified by the tests.

**Action:** Implement the `RecordingMediaSource` table/model with UUID id, cascading recording FK, `audio`/`video` kind, private object reference, nullable MIME/dimensions/signed video offset, quality label, and uniqueness constraint. Backfill legacy refs as specified without rewriting `SessionRecording` refs. Persist the supplied signed offset for distinct video uploads and reject missing/invalid offsets before persistence; keep the existing single interleaved upload path valid without an offset.

**Acceptance evidence:** `cd backend && pytest tests/test_migration.py` and the ingestion test module pass, including downgrade/re-upgrade preservation and duplicate rejection.

**Dependencies:** T-1

## Phase 2: RED — Authorized Retrieval Contract

### T-3: Add failing manifest and transcript ownership route tests

**Files:** `backend/tests/meetings/test_playback_manifest.py`; `backend/tests/meetings/test_transcript_turn_id.py`

**Action:** Add synthetic route tests for owner success, missing/invalid JWT (401), absent and non-owned meeting indistinguishable 404, no recording/playable source, one versus multiple video choices, omission of video sources with null offset, signed positive/negative offsets, and confirmation that only authorized refs are sent to `temporary_read_url` with TTL 3600 and raw refs are never serialized. Verify the transcript route has the same ownership boundary and does not return another user's transcript.

**Acceptance evidence:** Tests fail before implementation for the absent playback manifest and/or missing transcript ownership check; unauthorized cases assert no signing and no transcript/object reference disclosure.

**Validation:** `cd backend && pytest tests/meetings/test_playback_manifest.py tests/meetings/test_transcript_turn_id.py`.

**Dependencies:** None

### T-4: Implement authorized playback manifest and transcript ownership check

**Files:** `backend/app/meetings/` route/service/repository/schema modules; existing transcript route/service modules.

**Action:** Add `GET /api/v1/meetings/{meeting_id}/playback`, requiring the current user and ownership check before access to sources or signing. Return same 404 for absent/non-owned meetings; sign only the recording's authorized source objects with `temporary_read_url(reference, ttl_seconds=3600)`. Return mandatory audio plus only video sources with known signed offsets, and never expose raw object refs. Apply identical ownership checking to transcript retrieval before returning content.

**Acceptance evidence:** `cd backend && pytest tests/meetings/test_playback_manifest.py tests/meetings/test_transcript_turn_id.py` passes, including unauthorized non-disclosure assertions.

**Dependencies:** T-3; T-2 (requires persisted source inventory)

## Phase 3: RED — Frontend Data Mapping and Controller

### T-5: Add failing API mapping and timed-passage contract tests

**Files:** Frontend API adapter tests for `frontend/src/api.ts`; transcript mapping tests in the existing frontend test structure.

**Action:** Add synthetic tests for typed `getPlaybackManifest(meetingId)` and `getTranscript(meetingId)` responses. Verify backend `segments` preserve sequence and source text while mapping `start_ms`/`end_ms` to `TimedPassage.startMs`/`endMs`; invalid/missing timing retains text but produces no playback action. Verify manifest source fields and errors are handled without exposing object-store references outside signed URLs.

**Acceptance evidence:** Tests fail against the existing adapter's transcript type/mapping mismatch and absent manifest method.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** T-4

### T-6: Implement typed playback and transcript API mapping

**Files:** `frontend/src/api.ts` and its API type/test modules.

**Action:** Implement typed retrieval methods for playback manifest and transcript using the existing authenticated HTTP adapter. Correct mapping of ordered `segments` into timed passages; preserve source text/order and exclude invalid timing from time-linked actions without deleting the text. Keep all web HTTP access within the adapter.

**Acceptance evidence:** `cd frontend && npm run test` passes the new mapping and manifest tests.

**Dependencies:** T-5

### T-7: Add failing playback-controller RED tests

**Files:** `frontend/src/**/__tests__/PlaybackController.test.ts` (place in the established frontend test location).

**Action:** Add tests for valid interval matching (half-open `[startMs,endMs)`), first supplied matching passage on overlap, gaps, invalid timing, empty input, seek/pause/resume/rate/volume/mute state, active passage changes and clear-on-no-match. Cover paired audio/video alignment: signed offset formula, positive-offset wait, correction only above 250 ms, audio as authoritative clock, and audio-only control state. Use synthetic media fixtures.

**Acceptance evidence:** Tests fail before controller implementation for the expected absent controller behavior.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** T-5

## Phase 4: GREEN — Data Mapping and Playback Controller

### T-8: Implement playback controller and passage matching

**Files:** `frontend/src/components/PlaybackController.ts` and its unit tests.

**Action:** Implement typed `TimedPassage`, `MediaSourceOption`, and `PlaybackState` behavior. Derive the active passage from the authoritative audio clock, use half-open intervals and first-match order, and clear the active passage when no valid interval matches. Implement the designed media operations, paired video synchronization with signed offsets and 250 ms drift correction, positive-offset pause behavior, and audio-only operation. Handle rejected play promises as paused/error, not as successful playback.

**Acceptance evidence:** `cd frontend && npm run test` passes controller tests for properties 1, 2, 3, 5, and 6 and defined playback error behavior.

**Dependencies:** T-7

## Phase 5: RED — Playback View

### T-9: Add failing meeting playback view tests

**Files:** `frontend/src/**/__tests__/MeetingPlaybackView.test.tsx` (place in the established frontend test location).

**Action:** Add synthetic component tests for seek, pause/resume, speed, volume, mute, passage play action, and visible active-passage highlight/scroll behavior. Assert quality selection exists and changes source only for multiple playable video options, preserves audio source and playback position, and is absent for audio-only/single-video cases. Cover single muxed-media behavior, inaccessible legacy separate video with null offset, metadata-loading disabled controls, URL refresh exactly once at saved time then accessible error/stop on failure, failures to start either paired element pausing both, and accessible empty/unavailable/error states. Assert the view adds no editing, library, notes, summary, metadata, or other out-of-scope controls.

**Acceptance evidence:** Tests fail against the pre-feature meeting review view for the missing approved playback behaviors.

**Validation:** `cd frontend && npm run test`.

**Dependencies:** T-6, T-8

## Phase 6: GREEN — Meeting Playback View

### T-10: Implement accessible meeting playback view

**Files:** `frontend/src/components/MeetingPlaybackView.tsx` (new); existing meeting review route/view integration point.

**Action:** Add the view around the playback controller and typed adapter data. Provide accessible native media controls for seek, pause/resume, speed, volume, mute and conditional quality selection; render the transcript and active passage from playback time; provide a per-passage control that seeks to `startMs` and requests play. Disable controls during unavailable metadata, preserve content on invalid timing without time-linked controls, and display accessible loading/empty/error states. Add no feature excluded by the requirements.

**Acceptance evidence:** `cd frontend && npm run test` and `cd frontend && npm run typecheck` pass, including T-9 tests and the existing frontend suite/typecheck.

**Dependencies:** T-9

## Phase 7: Storage Delivery Integration Contract

### T-11: Verify signed-source range and CORS delivery contract

**Files:** `backend/tests/meetings/test_playback_storage_integration.py`.

**Action:** Add/run the designed integration test against disposable S3-compatible storage: fetch a signed source URL with HTTP `Range`, assert 206, correct `Content-Range` and bytes; run browser-origin CORS preflight and GET from the configured frontend origin. Do not introduce a public URL or unauthenticated fallback if delivery configuration fails.

**Acceptance evidence:** The integration test passes with disposable storage; a failed/missing range or CORS configuration is recorded as a deployment blocker, never bypassed.

**Validation:** `cd backend && pytest tests/meetings/test_playback_storage_integration.py` with disposable S3-compatible storage configured.

**Dependencies:** T-4
