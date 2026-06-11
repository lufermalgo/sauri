/**
 * Bug Condition Exploration Test — Base64 Upload Memory Failure
 *
 * **Validates: Requirements 1.1, 1.2, 1.3**
 *
 * This test encodes the EXPECTED (correct) behavior:
 * - Recordings should upload without base64 encoding/decoding
 * - No base64Data should be transferred via chrome.runtime.sendMessage
 * - Upload queue should NOT store blobBase64 (33% overhead)
 *
 * On UNFIXED code, this test will FAIL — that failure CONFIRMS the bug exists.
 * After the fix is implemented, this test will PASS.
 *
 * Scoped PBT Approach: any recording where transferMethod == "base64_via_sendMessage"
 * and decodingMethod == "atob_in_service_worker" (i.e., all recordings on unfixed code)
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { readFileSync } from "fs";
import { resolve } from "path";

/**
 * Helper: Read source files to verify the bug condition structurally.
 * This is a static analysis approach — we verify the source code does NOT
 * contain the buggy patterns (atob decoding, base64 transfer, blobBase64 storage).
 */
function readSource(filename: string): string {
  return readFileSync(resolve(__dirname, filename), "utf-8");
}

describe("Bug Condition Exploration: Base64 Upload Memory Failure", () => {
  /**
   * Property 1: Bug Condition — uploadRecording should NOT use atob()
   *
   * For any recording session where transferMethod == "base64_via_sendMessage"
   * and decodingMethod == "atob_in_service_worker", the upload function should
   * NOT decode base64 data using atob(). Instead it should read the Blob
   * directly from the shared sauri-recordings IndexedDB.
   *
   * On UNFIXED code: background.ts line ~82 calls `atob(base64Data)` inside
   * uploadRecording — this property FAILS, confirming the bug.
   */
  describe("Property: uploadRecording must NOT use atob() to decode recording data", () => {
    it("background.ts uploadRecording should not call atob() for base64 decoding", () => {
      fc.assert(
        fc.property(
          // Generate recording scenarios where the bug condition holds:
          // transferMethod == "base64_via_sendMessage" AND
          // decodingMethod == "atob_in_service_worker"
          fc.record({
            sizeBytes: fc.integer({ min: 10 * 1024 * 1024, max: 500 * 1024 * 1024 }),
            mimeType: fc.constantFrom(
              "video/webm;codecs=vp8,opus",
              "audio/webm;codecs=opus",
              "video/webm"
            ),
            sessionId: fc.uuid(),
            transferMethod: fc.constant("base64_via_sendMessage" as const),
            decodingMethod: fc.constant("atob_in_service_worker" as const),
          }),
          (input) => {
            // Verify the bug condition holds for this input
            expect(input.transferMethod).toBe("base64_via_sendMessage");
            expect(input.decodingMethod).toBe("atob_in_service_worker");

            // EXPECTED behavior: The uploadRecording function in background.ts
            // should NOT contain atob() calls for decoding recording data.
            // It should use assembleBlob(sessionId, mimeType) from recording-db.ts
            const backgroundSource = readSource("background.ts");

            // The upload function should NOT use atob to decode base64
            // Pattern: `atob(base64Data)` or `atob(` within uploadRecording
            const uploadFnMatch = backgroundSource.match(
              /async function uploadRecording\([^)]*\)[\s\S]*?^}/m
            );
            const uploadFnBody = uploadFnMatch?.[0] ?? "";

            // ASSERTION: uploadRecording should NOT call atob()
            // On UNFIXED code this FAILS because line ~82 has:
            //   const binaryString = atob(base64Data);
            expect(uploadFnBody).not.toMatch(/atob\(/);
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property: recording-stopped message should NOT carry base64Data
   *
   * The offscreen document should send only metadata (sessionId, size, mimeType)
   * when a recording stops. The full recording data should remain in IndexedDB.
   *
   * On UNFIXED code: offscreen.ts sends { type: "recording-stopped", base64Data, ... }
   * This property FAILS, confirming the bug.
   */
  describe("Property: recording-stopped message must NOT carry base64Data", () => {
    it("offscreen.ts should send metadata-only message on recording stop", () => {
      fc.assert(
        fc.property(
          fc.record({
            sizeBytes: fc.integer({ min: 10 * 1024 * 1024, max: 500 * 1024 * 1024 }),
            mimeType: fc.constantFrom(
              "video/webm;codecs=vp8,opus",
              "audio/webm;codecs=opus"
            ),
            sessionId: fc.uuid(),
          }),
          (_input) => {
            // EXPECTED behavior: The offscreen.ts recorder.onstop handler
            // should send ONLY metadata in the recording-stopped message:
            // { type: "recording-stopped", sessionId, size, mimeType }
            // It should NOT include base64Data.
            const offscreenSource = readSource("offscreen.ts");

            // Find the sendMessage call for "recording-stopped"
            const recordingStoppedMsg = offscreenSource.match(
              /chrome\.runtime\.sendMessage\(\{[^}]*type:\s*"recording-stopped"[^}]*\}/s
            );
            const msgBody = recordingStoppedMsg?.[0] ?? "";

            // ASSERTION: The message should NOT contain base64Data
            // On UNFIXED code this FAILS because offscreen.ts sends:
            //   chrome.runtime.sendMessage({
            //     type: "recording-stopped",
            //     base64Data: base64,  <-- BUG: transfers full recording as base64
            //     ...
            //   })
            expect(msgBody).not.toMatch(/base64Data/);
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property: Upload queue should NOT store blobBase64 field
   *
   * The UploadJob interface should not have a blobBase64 field. The queue
   * should store only a sessionId reference to resolve the Blob at upload time
   * from the shared sauri-recordings IndexedDB.
   *
   * On UNFIXED code: upload-queue.ts defines `blobBase64: string` in UploadJob
   * and enqueueUpload stores the full base64 string. This property FAILS.
   */
  describe("Property: upload queue must NOT store blobBase64 (33% storage overhead)", () => {
    it("upload-queue.ts UploadJob interface should not have blobBase64 field", () => {
      fc.assert(
        fc.property(
          fc.record({
            sizeBytes: fc.integer({ min: 10 * 1024 * 1024, max: 100 * 1024 * 1024 }),
            sessionId: fc.uuid(),
            // Base64 encoding adds ~33% overhead
            expectedOverheadPercent: fc.constant(33),
          }),
          (input) => {
            const uploadQueueSource = readSource("upload-queue.ts");

            // EXPECTED behavior: UploadJob should NOT have blobBase64 field
            // The queue should store only sessionId as a reference to the recording
            // and resolve the actual Blob from IndexedDB at upload time.
            //
            // For a recording of ${input.sizeBytes} bytes, base64 encoding adds
            // ~${input.expectedOverheadPercent}% overhead, meaning the queue would
            // waste ~${Math.round(input.sizeBytes * 0.33 / 1024 / 1024)}MB per job.

            // ASSERTION: UploadJob interface should NOT contain blobBase64
            // On UNFIXED code this FAILS because upload-queue.ts has:
            //   blobBase64: string;  (line ~21)
            const interfaceMatch = uploadQueueSource.match(
              /export interface UploadJob\s*\{[\s\S]*?\n\}/
            );
            const interfaceBody = interfaceMatch?.[0] ?? "";

            expect(interfaceBody).not.toMatch(/blobBase64/);
          }
        ),
        { numRuns: 10 }
      );
    });

    it("enqueueUpload should not accept or store blobBase64", () => {
      fc.assert(
        fc.property(
          fc.record({
            sizeBytes: fc.integer({ min: 10 * 1024 * 1024, max: 100 * 1024 * 1024 }),
            sessionId: fc.uuid(),
          }),
          (_input) => {
            const uploadQueueSource = readSource("upload-queue.ts");

            // EXPECTED behavior: EnqueueUploadInput should NOT include blobBase64
            // ASSERTION: The Pick type for enqueue input should not reference blobBase64
            const enqueueInputMatch = uploadQueueSource.match(
              /export type EnqueueUploadInput[\s\S]*?;/
            );
            const enqueueInputBody = enqueueInputMatch?.[0] ?? "";

            expect(enqueueInputBody).not.toMatch(/blobBase64/);
          }
        ),
        { numRuns: 10 }
      );
    });
  });
});
