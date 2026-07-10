# Implementation Plan

## Overview

Fix the base64 upload memory crash by eliminating the base64 encoding/decoding path. The offscreen document will send metadata-only messages after recording stops, and the background service worker will read the Blob directly from the shared `sauri-recordings` IndexedDB at upload time.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1", "2"],
      "description": "Write exploration and preservation tests on unfixed code"
    },
    {
      "wave": 2,
      "tasks": ["3.1"],
      "description": "Create shared recording-db module"
    },
    {
      "wave": 3,
      "tasks": ["3.2", "3.3"],
      "description": "Update offscreen and upload-queue to remove base64"
    },
    {
      "wave": 4,
      "tasks": ["3.4"],
      "description": "Update background to read Blob from IndexedDB"
    },
    {
      "wave": 5,
      "tasks": ["3.5", "3.6"],
      "description": "Verify exploration and preservation tests pass"
    },
    {
      "wave": 6,
      "tasks": ["4"],
      "description": "Final checkpoint — all tests pass"
    }
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** — Base64 Upload Memory Failure
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate base64 encoding/decoding causes memory issues for large recordings
  - **Scoped PBT Approach**: Scope the property to the concrete failing case — any recording where `transferMethod == "base64_via_sendMessage"` and `decodingMethod == "atob_in_service_worker"` (i.e., all recordings on unfixed code)
  - Test that `uploadRecording(base64Data, mimeType, sessionId)` with a large base64 string (≥10MB encoded) triggers memory allocation failure via `atob()`
  - Test that `handleRecordingStopped` receives `base64Data` in the message and stores it in the upload queue's `blobBase64` field (33% storage overhead)
  - Run test on UNFIXED code — expect FAILURE (this confirms the bug exists)
  - Document counterexamples found (e.g., "`atob()` throws memory allocation error for 15MB base64 string in service worker context")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** — Upload Queue Idempotent Retry and FIFO Recovery
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: `enqueueUpload({ sessionId, claveIdempotencia, blobBase64, mimeType })` creates job with `status: "pending"`, `retryCount: 0`, `maxRetries: 3`
  - Observe: `getNextPendingJob()` returns oldest pending job by `createdAt` (FIFO)
  - Observe: `markFailed(jobId, error)` increments `retryCount`; if `retryCount >= maxRetries` sets `status: "failed"`, else resets to `"pending"`
  - Observe: `markProcessing(jobId)` sets `status: "processing"` and `lastAttemptAt`
  - Observe: `markDone(jobId)` sets `status: "done"`
  - Write property-based tests:
    - For all valid enqueue inputs, job is created with correct initial state (`pending`, `retryCount: 0`)
    - For any N jobs enqueued in sequence, `getNextPendingJob` always returns the one with smallest `createdAt`
    - For any job failed K times where K < maxRetries, status returns to `"pending"` (retryable)
    - For any job failed K times where K >= maxRetries, status becomes `"failed"` (permanent)
    - For any job with a given `claveIdempotencia`, a duplicate enqueue is rejected (unique index)
  - Verify all tests pass on UNFIXED code
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.2, 3.4, 3.5, 3.6_

- [x] 3. Fix for base64 upload memory crash

  - [x] 3.1 Create shared module `extension/src/recording-db.ts`
    - Extract `openDB`, `getChunksBySession`, `clearSession` from `offscreen.ts` into new shared module
    - Export `ChunkRecord` interface and DB constants (`DB_NAME`, `DB_VERSION`, `STORE_NAME`)
    - Add new `assembleBlob(sessionId: string, mimeType: string): Promise<Blob>` helper that reads chunks and returns assembled Blob
    - Export `storeChunk` for use by offscreen.ts
    - _Bug_Condition: isBugCondition(input) where input.transferMethod == "base64_via_sendMessage"_
    - _Expected_Behavior: Recording data accessed directly from shared IndexedDB without base64_
    - _Preservation: IndexedDB chunk storage schema unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.2 Update `extension/src/offscreen.ts` — remove base64 path
    - Import `openDB`, `storeChunk`, `getChunksBySession` from `./recording-db`
    - Remove local `openDB`, `storeChunk`, `getChunksBySession`, `clearSession`, `ChunkRecord` definitions (use shared module)
    - In `recorder.onstop`: remove `blobToBase64(blob)` call
    - In `recorder.onstop`: change `recording-stopped` message to send only `{ type: "recording-stopped", sessionId, size, mimeType }` — no `base64Data`
    - In `recorder.onstop`: remove `clearSession(storedSessionId)` call — let background handle cleanup after successful upload
    - Delete `blobToBase64` utility function entirely
    - _Bug_Condition: isBugCondition(input) where offscreen converts Blob to base64_
    - _Expected_Behavior: Offscreen sends metadata-only message, no recording data transfer_
    - _Preservation: Chunk storage during recording (5s timeslice) unchanged_
    - _Requirements: 2.1, 3.1_

  - [x] 3.3 Update `extension/src/upload-queue.ts` — remove blobBase64 field
    - Remove `blobBase64: string` from `UploadJob` interface
    - Update `EnqueueUploadInput` type: remove `blobBase64` from the `Pick<>` union
    - Remove `blobBase64: input.blobBase64` assignment in `enqueueUpload` function
    - _Bug_Condition: Queue stores full base64 string wasting 33% additional storage_
    - _Expected_Behavior: Queue stores only sessionId reference, resolves Blob at upload time_
    - _Preservation: All queue state machine logic (pending/processing/done/failed) unchanged_
    - _Requirements: 2.3, 3.2_

  - [x] 3.4 Update `extension/src/background.ts` — read Blob from IndexedDB at upload time
    - Import `assembleBlob`, `clearSession` from `./recording-db`
    - Update `handleRecordingStopped`: remove `base64Data` parameter, accept only `size`, `mimeType`, `sessionId`
    - Update `handleRecordingStopped`: remove `blobBase64` from `enqueueUpload` call
    - Update `uploadRecording` signature: remove `base64Data` parameter, accept `mimeType`, `sessionId`, `notificationEmittedAt`
    - In `uploadRecording`: replace `atob()` + `Uint8Array` + `new Blob()` block with `const blob = await assembleBlob(sessionId, mimeType)`
    - In `uploadRecording`: after successful upload (response.ok), call `await clearSession(sessionId)`
    - Update `processUploadQueue`: pass `job.mimeType`, `job.sessionId` instead of `job.blobBase64`
    - Update message listener: remove `base64Data` from `recording-stopped` handler destructuring
    - _Bug_Condition: background calls atob() on large base64 string causing memory crash_
    - _Expected_Behavior: background reads Blob directly from shared sauri-recordings IndexedDB_
    - _Preservation: Upload queue processing, alarm recovery, auth token retrieval unchanged_
    - _Requirements: 2.2, 2.3, 2.4, 3.2, 3.3, 3.4_

  - [x] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** — Recordings Upload Without Base64
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior (direct IndexedDB access, no base64)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** — Upload Queue Idempotent Retry and FIFO Recovery
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all queue behavior (FIFO, retry, idempotency, alarm recovery) is unchanged
    - _Requirements: 3.2, 3.4, 3.5, 3.6_

- [x] 4. Checkpoint — Ensure all tests pass
  - Run project typecheck to verify no type errors across modified files
  - Ensure exploration test (Property 1) passes on fixed code
  - Ensure preservation tests (Property 2) pass on fixed code
  - Ensure no regressions in existing functionality
  - Ask the user if questions arise


## Notes

- Tasks 1 and 2 MUST be completed before task 3 (write tests on unfixed code first)
- Task 3.1 is the foundation — all other implementation tasks depend on the shared module
- The fix applies to ALL recording sizes, not just >10MB (eliminates unnecessary overhead)
- Property-based tests use the upload-queue's IndexedDB operations directly (no browser mocking needed for queue logic)
- The `sauri-recordings` IndexedDB is shared between offscreen and background because they run under the same extension origin
