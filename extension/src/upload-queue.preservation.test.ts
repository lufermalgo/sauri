/**
 * Preservation Property Tests — Upload Queue Idempotent Retry and FIFO Recovery
 *
 * **Validates: Requirements 3.2, 3.4, 3.5, 3.6**
 *
 * These tests capture queue behavior that must NOT change after the base64 fix:
 * - enqueueUpload creates jobs with correct initial state
 * - getNextPendingJob returns FIFO (oldest createdAt)
 * - markFailed increments retryCount, transitions correctly
 * - markProcessing sets status and lastAttemptAt
 * - markDone sets status to "done"
 * - Duplicate idempotencyKey is rejected (unique index)
 *
 * Written BEFORE the fix — must pass on UNFIXED code and continue to pass after fix.
 */

import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";

import {
  enqueueUpload,
  getNextPendingJob,
  markFailed,
  markProcessing,
  markDone,
  type EnqueueUploadInput,
} from "./upload-queue";

/**
 * Replace global indexedDB and IDBKeyRange with fresh fake-indexeddb instances.
 * This provides complete isolation without deleteDatabase hanging issues.
 */
beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  globalThis.IDBKeyRange = IDBKeyRange;
});

/**
 * Helper: Generate a valid EnqueueUploadInput for property tests.
 */
function arbEnqueueInput(): fc.Arbitrary<EnqueueUploadInput> {
  return fc.record({
    sessionId: fc.uuid(),
    idempotencyKey: fc.uuid(),
    mimeType: fc.constantFrom(
      "video/webm;codecs=vp8,opus",
      "audio/webm;codecs=opus",
      "video/webm"
    ),
    notificationEmittedAt: fc.option(fc.date().map((d) => d.toISOString()), {
      nil: undefined,
    }),
  });
}

describe("Preservation: Upload Queue Idempotent Retry and FIFO Recovery", () => {
  /**
   * Property: For all valid enqueue inputs, job is created with correct initial state.
   * - status: "pending"
   * - retryCount: 0
   * - maxRetries: 3
   */
  describe("Property: enqueueUpload creates job with correct initial state", () => {
    it("job has status='pending', retryCount=0, maxRetries=3 for any valid input", async () => {
      await fc.assert(
        fc.asyncProperty(arbEnqueueInput(), async (input) => {
          const job = await enqueueUpload(input);

          expect(job.status).toBe("pending");
          expect(job.retryCount).toBe(0);
          expect(job.maxRetries).toBe(3);
          expect(job.sessionId).toBe(input.sessionId);
          expect(job.idempotencyKey).toBe(input.idempotencyKey);
          expect(job.mimeType).toBe(input.mimeType);
          expect(job.id).toMatch(
            /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
          );
          expect(job.createdAt).toBeGreaterThan(0);
          expect(job.createdAt).toBeLessThanOrEqual(Date.now());
        }),
        { numRuns: 20 }
      );
    });
  });

  /**
   * Property: For any N jobs enqueued in sequence, getNextPendingJob always
   * returns the one with smallest createdAt (FIFO ordering).
   */
  describe("Property: getNextPendingJob returns oldest pending job (FIFO)", () => {
    it("for N sequentially enqueued jobs, next pending is always the oldest", async () => {
      await fc.assert(
        fc.asyncProperty(
          fc.integer({ min: 2, max: 5 }),
          async (n) => {
            // Reset DB for each property run to test FIFO correctly
            globalThis.indexedDB = new IDBFactory();
            globalThis.IDBKeyRange = IDBKeyRange;

            const jobs = [];
            for (let i = 0; i < n; i++) {
              const input: EnqueueUploadInput = {
                sessionId: crypto.randomUUID(),
                idempotencyKey: crypto.randomUUID(),
                mimeType: "video/webm",
                notificationEmittedAt: undefined,
              };
              const job = await enqueueUpload(input);
              jobs.push(job);
              // Small delay to ensure distinct createdAt timestamps
              await new Promise((r) => setTimeout(r, 2));
            }

            // getNextPendingJob should return the one with smallest createdAt
            const next = await getNextPendingJob();
            expect(next).not.toBeNull();

            // The first enqueued job has the smallest createdAt
            const oldest = jobs.reduce((a, b) =>
              a.createdAt < b.createdAt ? a : b
            );

            expect(next!.id).toBe(oldest.id);
            expect(next!.createdAt).toBe(oldest.createdAt);
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property: For any job failed K times where K < maxRetries,
   * status returns to "pending" (retryable).
   */
  describe("Property: markFailed with retryCount < maxRetries resets to pending", () => {
    it("job remains retryable (pending) when failed fewer than maxRetries times", async () => {
      await fc.assert(
        fc.asyncProperty(
          arbEnqueueInput(),
          fc.integer({ min: 1, max: 2 }), // K < maxRetries (3)
          async (input, failCount) => {
            globalThis.indexedDB = new IDBFactory();
            globalThis.IDBKeyRange = IDBKeyRange;

            const job = await enqueueUpload(input);

            // Fail the job K times (K < 3)
            for (let i = 0; i < failCount; i++) {
              await markFailed(job.id, `error attempt ${i + 1}`);
            }

            // After K failures where K < maxRetries, job should still be pending
            const next = await getNextPendingJob();
            expect(next).not.toBeNull();
            expect(next!.id).toBe(job.id);
            expect(next!.status).toBe("pending");
            expect(next!.retryCount).toBe(failCount);
          }
        ),
        { numRuns: 15 }
      );
    });
  });

  /**
   * Property: For any job failed K times where K >= maxRetries,
   * status becomes "failed" (permanent failure).
   */
  describe("Property: markFailed with retryCount >= maxRetries sets status to failed", () => {
    it("job becomes permanently failed after maxRetries failures", async () => {
      await fc.assert(
        fc.asyncProperty(
          arbEnqueueInput(),
          fc.integer({ min: 3, max: 5 }), // K >= maxRetries (3)
          async (input, failCount) => {
            globalThis.indexedDB = new IDBFactory();
            globalThis.IDBKeyRange = IDBKeyRange;

            const job = await enqueueUpload(input);

            // Fail the job K times (K >= 3)
            for (let i = 0; i < failCount; i++) {
              await markFailed(job.id, `error attempt ${i + 1}`);
            }

            // After K >= maxRetries failures, job should NOT appear as pending
            const next = await getNextPendingJob();
            if (next !== null) {
              expect(next.id).not.toBe(job.id);
            }
          }
        ),
        { numRuns: 15 }
      );
    });
  });

  /**
   * Property: For any job with a given idempotencyKey,
   * a duplicate enqueue is rejected (unique index constraint).
   */
  describe("Property: duplicate idempotencyKey is rejected (unique index)", () => {
    it("second enqueue with same idempotencyKey throws", async () => {
      await fc.assert(
        fc.asyncProperty(arbEnqueueInput(), async (input) => {
          globalThis.indexedDB = new IDBFactory();
          globalThis.IDBKeyRange = IDBKeyRange;

          // First enqueue succeeds
          await enqueueUpload(input);

          // Second enqueue with same idempotencyKey should be rejected
          await expect(enqueueUpload(input)).rejects.toThrow();
        }),
        { numRuns: 15 }
      );
    });
  });

  /**
   * Property: markProcessing sets status to "processing".
   * Job is no longer returned by getNextPendingJob.
   */
  describe("Property: markProcessing sets status to processing", () => {
    it("job transitions to processing and is no longer pending", async () => {
      await fc.assert(
        fc.asyncProperty(arbEnqueueInput(), async (input) => {
          globalThis.indexedDB = new IDBFactory();
          globalThis.IDBKeyRange = IDBKeyRange;

          const job = await enqueueUpload(input);
          await markProcessing(job.id);

          // The only job is now "processing", so no pending jobs
          const next = await getNextPendingJob();
          expect(next).toBeNull();
        }),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property: markDone sets status to "done".
   * Job is no longer returned by getNextPendingJob.
   */
  describe("Property: markDone sets status to done", () => {
    it("job transitions to done and is no longer pending", async () => {
      await fc.assert(
        fc.asyncProperty(arbEnqueueInput(), async (input) => {
          globalThis.indexedDB = new IDBFactory();
          globalThis.IDBKeyRange = IDBKeyRange;

          const job = await enqueueUpload(input);
          await markProcessing(job.id);
          await markDone(job.id);

          // Job should not appear as pending
          const next = await getNextPendingJob();
          expect(next).toBeNull();
        }),
        { numRuns: 10 }
      );
    });
  });
});
