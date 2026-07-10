# Bugfix Requirements Document

## Introduction

The Chrome extension crashes with a `atob()` error when uploading recordings larger than ~10MB. The MV3 service worker has memory constraints that cause `atob()` to fail when decoding large base64 strings. Additionally, the current flow transfers the entire recording as a base64 string via `chrome.runtime.sendMessage`, which is unreliable for large payloads (~64MB theoretical limit but practically fails much sooner). The fix eliminates the base64 encoding/decoding path entirely by leveraging shared IndexedDB access between the offscreen document and the service worker.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a recording larger than ~10MB is stopped THEN the system converts the assembled Blob to base64 in the offscreen document and sends the entire base64 string (~14MB for a 10MB recording) via `chrome.runtime.sendMessage` to the background service worker

1.2 WHEN the background service worker receives a large base64 string and calls `atob()` to decode it back to binary for upload THEN the system crashes with a memory allocation failure due to MV3 service worker memory constraints

1.3 WHEN the upload queue stores a large recording THEN the system stores the full base64 string in the `blobBase64` field of the UploadJob in IndexedDB, wasting ~33% additional storage compared to binary

### Expected Behavior (Correct)

2.1 WHEN a recording is stopped THEN the system SHALL send only metadata (sessionId, size, mimeType) from the offscreen document to the background service worker via `chrome.runtime.sendMessage`, without transferring the recording data itself

2.2 WHEN the background service worker processes an upload THEN the system SHALL read the recording Blob directly from the shared `sauri-recordings` IndexedDB (accessible from the same extension origin) instead of decoding base64

2.3 WHEN the upload queue stores a recording job THEN the system SHALL store only a sessionId reference in the UploadJob instead of the full base64 data, and resolve the actual Blob from `sauri-recordings` IndexedDB at upload time

2.4 WHEN an upload completes successfully THEN the system SHALL clear the recording chunks from the `sauri-recordings` IndexedDB for that sessionId

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a recording is in progress THEN the system SHALL CONTINUE TO store chunks in the `sauri-recordings` IndexedDB with 5-second timeslice via the offscreen document

3.2 WHEN the upload queue processes jobs THEN the system SHALL CONTINUE TO use the idempotent retry mechanism (pending → processing → done/failed) with the same clave_idempotencia

3.3 WHEN a recording smaller than 10MB is uploaded THEN the system SHALL CONTINUE TO successfully upload the recording to the backend endpoint `POST /api/v1/ingesta/subir` as multipart form data

3.4 WHEN the browser restarts or the service worker wakes up THEN the system SHALL CONTINUE TO recover pending upload jobs via `chrome.alarms` and `chrome.runtime.onStartup`

3.5 WHEN multiple recordings are queued THEN the system SHALL CONTINUE TO process them in FIFO order (oldest pending first)

3.6 WHEN an upload fails THEN the system SHALL CONTINUE TO retry up to maxRetries (3) before marking the job as permanently failed
