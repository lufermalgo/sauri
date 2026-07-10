# Base64 Upload Fix — Bugfix Design

## Overview

The Chrome extension crashes with memory allocation failures when uploading recordings larger than ~10MB because the current flow converts the recording Blob to a base64 string in the offscreen document, transfers it via `chrome.runtime.sendMessage`, and then decodes it with `atob()` in the MV3 service worker. The fix eliminates the base64 encoding/decoding path entirely by leveraging shared IndexedDB access — both the offscreen document and the service worker run under the same extension origin and can access the same `sauri-recordings` IndexedDB directly. The offscreen document will send only metadata after recording stops, and the background will read the Blob from IndexedDB at upload time.

## Glossary

- **Bug_Condition (C)**: A recording is stopped AND the assembled Blob is transferred as a base64 string via `chrome.runtime.sendMessage` to the background service worker for upload
- **Property (P)**: Recordings of any size (1MB–500MB) upload successfully without memory errors, using direct IndexedDB Blob access instead of base64 encoding/decoding
- **Preservation**: The upload queue's idempotent retry mechanism, alarm-based recovery, FIFO ordering, chunk persistence during recording, and multipart upload to the backend must remain unchanged
- **offscreen.ts**: The offscreen document that captures audio/video via MediaRecorder, stores chunks in `sauri-recordings` IndexedDB with 5s timeslice
- **background.ts**: The MV3 service worker that orchestrates recording lifecycle, upload queue processing, and alarm-based recovery
- **upload-queue.ts**: IndexedDB-backed queue managing upload jobs with states: pending → processing → done/failed
- **sauri-recordings**: IndexedDB database (shared origin) storing raw Blob chunks indexed by sessionId
- **sauri-upload-queue**: IndexedDB database storing upload job metadata
- **clave_idempotencia**: Backend-enforced idempotency key (= sessionId) preventing duplicate uploads on retries

## Bug Details

### Bug Condition

The bug manifests when a recording is stopped and the offscreen document converts the assembled Blob to base64 (`blobToBase64`), sends the full base64 string via `chrome.runtime.sendMessage`, and the background service worker calls `atob()` to decode it back to binary. For recordings >~10MB, this causes memory allocation failure in the MV3 service worker's constrained environment.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type RecordingSession
  OUTPUT: boolean
  
  RETURN input.recordingBlob.size > 0
         AND input.transferMethod == "base64_via_sendMessage"
         AND input.decodingMethod == "atob_in_service_worker"
END FUNCTION
```

Note: While the crash is most visible for recordings >10MB, the base64 path is inefficient for ALL recording sizes (33% size overhead, unnecessary CPU for encode/decode). The fix applies to all recordings regardless of size.

### Examples

- **10MB recording**: Offscreen assembles 10MB Blob → converts to ~14MB base64 string → sends via sendMessage → background calls `atob()` on 14MB string → **crashes with memory allocation failure**
- **50MB recording**: Offscreen assembles 50MB Blob → converts to ~67MB base64 string → exceeds sendMessage practical payload limit → **message silently fails or crashes**
- **2MB recording**: Offscreen assembles 2MB Blob → converts to ~2.7MB base64 → background decodes → upload succeeds but wastes CPU/memory unnecessarily
- **500MB recording**: Impossible to even encode — Blob.readAsDataURL will exhaust offscreen document memory before transfer

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Chunk storage during recording: 5-second timeslice chunks persist in `sauri-recordings` IndexedDB via offscreen document
- Upload queue state machine: pending → processing → done/failed transitions
- Idempotent retry: same sessionId = same `clave_idempotencia` = no duplicate uploads on backend
- Alarm-based recovery: `chrome.alarms` fires every 1 minute to process pending jobs
- Browser restart recovery: `chrome.runtime.onStartup` triggers queue processing
- FIFO ordering: oldest pending job processed first
- Retry limit: maxRetries = 3 before permanent failure
- Backend endpoint: POST `/api/v1/ingesta/subir` with multipart form data (audio file + datos JSON)
- Auth token retrieval from `chrome.storage.sync`

**Scope:**
All inputs that do NOT involve the recording data transfer path (base64 encode → sendMessage → atob decode) should be completely unaffected by this fix. This includes:
- The recording capture flow (MediaRecorder, chunk storage)
- The upload HTTP request format (multipart form data)
- The queue management logic (enqueue, dequeue, mark states)
- The alarm and startup recovery mechanisms
- The panel UI interactions
- The content script meet detection

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Unnecessary base64 encoding in offscreen.ts**: `blobToBase64()` (line ~240) converts the entire assembled Blob to a base64 data URL via `FileReader.readAsDataURL`. For a 10MB Blob, this produces a ~14MB string in memory.

2. **Large payload via chrome.runtime.sendMessage**: The `recording-stopped` message carries the full base64 string in `base64Data`. While sendMessage has no hard size limit documented, payloads exceeding ~64MB fail, and even smaller payloads strain the serialization/deserialization pipeline.

3. **atob() memory constraint in service worker**: In `background.ts` `uploadRecording()` (line ~80), `atob(base64Data)` allocates a string equal to the decoded binary size, then a `Uint8Array` of the same size is allocated character-by-character. This double allocation (~24MB for a 10MB recording) exceeds the MV3 service worker memory budget.

4. **Redundant storage in upload queue**: `upload-queue.ts` stores the full base64 string in `blobBase64` field. For a 10MB recording, this wastes ~14MB in IndexedDB per job, and the data already exists as raw Blob chunks in `sauri-recordings`.

**Core insight**: Both the offscreen document and the service worker share the same extension origin, meaning they can both access the `sauri-recordings` IndexedDB. There is no need to transfer the recording data between contexts — the background can read it directly.

## Correctness Properties

Property 1: Bug Condition — Recordings upload without base64 encoding

_For any_ recording session where the recording is stopped and the Blob exists in `sauri-recordings` IndexedDB, the system SHALL upload the recording by reading the Blob directly from IndexedDB in the service worker, without any base64 encoding or decoding, and without transferring recording data via `chrome.runtime.sendMessage`.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation — Upload queue idempotent retry and recovery

_For any_ upload job in the queue, the system SHALL continue to use the same `clave_idempotencia` (= sessionId) for retries, process jobs in FIFO order, retry up to maxRetries (3), and recover pending jobs on browser restart or alarm trigger, preserving all existing queue behavior.

**Validates: Requirements 3.2, 3.4, 3.5, 3.6**

Property 3: Preservation — Chunk cleanup only after successful upload

_For any_ recording session where the upload completes successfully (HTTP 2xx from backend), the system SHALL clear the chunks from `sauri-recordings` IndexedDB for that sessionId. Chunks SHALL NOT be cleared before upload success, ensuring recovery is possible if the service worker restarts mid-upload.

**Validates: Requirements 2.4, 3.1, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `extension/src/recording-db.ts` (NEW — shared module)

**Purpose**: Extract IndexedDB helper functions into a shared module importable by both offscreen.ts and background.ts.

**Specific Changes**:
1. **Extract shared helpers**: Move `openDB`, `getChunksBySession`, `clearSession` into `recording-db.ts` with exports
2. **Export types**: Export `ChunkRecord` interface and DB constants (`DB_NAME`, `STORE_NAME`, `DB_VERSION`)
3. **Add `assembleBlob` helper**: Reads all chunks for a sessionId and returns a single assembled Blob with the correct mimeType

---

**File**: `extension/src/offscreen.ts`

**Function**: `recorder.onstop` handler

**Specific Changes**:
1. **Remove base64 conversion**: Delete the `blobToBase64(blob)` call and the `base64Data` field from the message
2. **Send metadata only**: Change the `recording-stopped` message to send only `{ type, sessionId, size, mimeType }` — no recording data
3. **Do NOT clear chunks**: Remove the `clearSession()` call from onstop — let the upload process handle cleanup after successful upload
4. **Import from shared module**: Import `openDB`, `storeChunk`, `getChunksBySession` from `recording-db.ts` (remove local duplicates)
5. **Remove `blobToBase64` utility**: Delete the function entirely — it's no longer needed

---

**File**: `extension/src/upload-queue.ts`

**Interface**: `UploadJob`

**Specific Changes**:
1. **Remove `blobBase64` field**: Delete from `UploadJob` interface — the queue stores only a reference (sessionId) to the recording
2. **Update `EnqueueUploadInput`**: Remove `blobBase64` from the Pick type
3. **Remove `blobBase64` from `enqueueUpload`**: Don't assign it in the job creation

---

**File**: `extension/src/background.ts`

**Function**: `handleRecordingStopped`

**Specific Changes**:
1. **Remove `base64Data` parameter**: Accept only `size`, `mimeType`, `sessionId`
2. **Remove `blobBase64` from enqueue call**: Pass only `sessionId`, `claveIdempotencia`, `mimeType`

**Function**: `uploadRecording`

**Specific Changes**:
3. **Remove `base64Data` parameter**: Accept only `mimeType`, `sessionId`, `notificationEmittedAt`
4. **Read Blob from IndexedDB**: Import `assembleBlob` from `recording-db.ts` and call it with sessionId to get the Blob directly
5. **Remove atob() decoding**: Delete the entire base64→Uint8Array→Blob conversion block
6. **Clear chunks after success**: After successful upload (HTTP 2xx), call `clearSession(sessionId)` from `recording-db.ts`

**Function**: `processUploadQueue`

**Specific Changes**:
7. **Update upload call**: Pass `job.mimeType` and `job.sessionId` instead of `job.blobBase64`

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that simulate the `uploadRecording` function receiving a large base64 string and calling `atob()`. Run these tests on the UNFIXED code to observe memory failures and understand the root cause.

**Test Cases**:
1. **Large recording decode**: Call `uploadRecording` with a 15MB base64 string — observe atob() failure (will fail on unfixed code)
2. **Medium recording decode**: Call `uploadRecording` with a 5MB base64 string — may succeed but wastes memory (demonstrates inefficiency)
3. **Message size limit**: Simulate sendMessage with a 50MB base64 payload — observe transfer failure (will fail on unfixed code)
4. **Queue storage bloat**: Enqueue a job with 14MB blobBase64 — observe excessive IndexedDB usage (demonstrates waste)

**Expected Counterexamples**:
- `atob()` throws "Failed to execute 'atob': The string to be decoded is not correctly encoded" or memory allocation error for large payloads
- Possible causes: MV3 service worker memory limit (~128MB shared), string allocation during atob, double allocation for Uint8Array construction

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  // Store chunks in sauri-recordings IndexedDB
  storeChunksInDB(input.sessionId, input.chunks)
  
  // Fixed upload reads directly from IndexedDB
  result := uploadRecording_fixed(input.mimeType, input.sessionId)
  
  ASSERT result.blobReadFromDB == true
  ASSERT result.noBase64Used == true
  ASSERT result.uploadSuccessful == true
  ASSERT result.chunksCleared == true (only after success)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  // Queue operations, alarm recovery, retry logic
  ASSERT queueBehavior_original(input) = queueBehavior_fixed(input)
  // FIFO order, retry count, state transitions
  ASSERT uploadQueueState_original(input) = uploadQueueState_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (various session states, retry counts, queue sizes)
- It catches edge cases like concurrent uploads, alarm triggers during processing, and restart recovery
- It provides strong guarantees that queue behavior is unchanged for all non-transfer operations

**Test Plan**: Observe behavior on UNFIXED code first for queue operations (enqueue, dequeue, retry, alarm processing), then write property-based tests capturing that behavior.

**Test Cases**:
1. **Queue FIFO preservation**: Enqueue N jobs in order → verify oldest pending is always dequeued first (unchanged by fix)
2. **Retry mechanism preservation**: Fail a job repeatedly → verify retryCount increments and status transitions match original behavior
3. **Idempotency preservation**: Same sessionId → same claveIdempotencia → backend deduplicates (unchanged by fix)
4. **Alarm recovery preservation**: Simulate service worker restart → verify pending/stale jobs are reprocessed

### Unit Tests

- Test `assembleBlob`: reads chunks from IndexedDB, assembles in timestamp order, returns correct mimeType
- Test `clearSession`: removes all chunks for a sessionId, leaves other sessions intact
- Test `uploadRecording` (fixed): reads Blob from DB, constructs correct FormData, sends multipart request
- Test `handleRecordingStopped` (fixed): receives metadata-only message, enqueues job without blobBase64
- Test `offscreen.onstop` (fixed): sends metadata-only message, does NOT clear chunks

### Property-Based Tests

- Generate random recording sizes (1KB–500MB metadata) and verify the upload path never uses base64 encoding
- Generate random queue states (multiple jobs at various statuses) and verify FIFO + retry semantics are preserved
- Generate random sessionIds and verify chunks are cleared only after successful upload confirmation
- Generate random failure scenarios (network errors, service worker restarts) and verify recovery works

### Integration Tests

- End-to-end: record → stop → enqueue → upload → verify backend receives correct multipart data
- Recovery: record → stop → simulate service worker kill → restart → verify upload completes from IndexedDB
- Large recording: record 50MB+ → stop → upload → verify no memory errors and successful backend receipt
- Concurrent sessions: multiple recordings queued → verify all upload correctly in FIFO order
