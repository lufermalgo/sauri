/**
 * Property test for upload queue idempotency (upload-queue.ts).
 *
 * Feature: meeting-capture-transcription, Property 14: Idempotency of pipeline
 * and ingestion handlers — Task: 14.9 (client facet) — Validates: Requirements 2.3, 4.1
 *
 * For any sequence of retries against the IndexedDB queue with the same
 * idempotencyKey, the extension emits at most one effective upload
 * (no duplicate job in the queue).
 */

import { describe, it, expect, beforeEach } from "vitest";
import * as fc from "fast-check";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";

import { enqueueUpload, getPendingAndFailedJobs, type EnqueueUploadInput } from "./upload-queue";

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  globalThis.IDBKeyRange = IDBKeyRange;
});

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

describe("Property 14 (client facet): upload queue idempotency", () => {
  it("for any number of upload retries with the same idempotencyKey, at most one is effective", async () => {
    await fc.assert(
      fc.asyncProperty(
        arbEnqueueInput(),
        fc.integer({ min: 1, max: 8 }),
        async (input, retries) => {
          globalThis.indexedDB = new IDBFactory();
          globalThis.IDBKeyRange = IDBKeyRange;

          let successful = 0;
          let ids = new Set<string>();

          for (let i = 0; i < retries; i++) {
            try {
              const job = await enqueueUpload(input);
              successful += 1;
              ids.add(job.id);
            } catch {
              // Retry rejected by the idempotencyKey unique index — expected.
            }
          }

          // At most one retry produces an effectively enqueued job.
          expect(successful).toBe(1);
          expect(ids.size).toBe(1);
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("Property 6: IndexedDB migration preserves pending jobs", () => {
  const DB_NAME = "sauri-upload-queue";
  const STORE_NAME = "jobs";

  interface LegacyUploadJobV1 {
    id: string;
    sessionId: string;
    claveIdempotencia: string;
    status: "pending" | "processing" | "done" | "failed";
    retryCount: number;
    maxRetries: number;
    createdAt: number;
    mimeType: string;
    notificationEmittedAt?: string;
    titulo?: string;
    enlaceMeet?: string;
  }

  function arbLegacyJob(): fc.Arbitrary<LegacyUploadJobV1> {
    return fc.record({
      id: fc.uuid(),
      sessionId: fc.uuid(),
      claveIdempotencia: fc.uuid(),
      status: fc.constant("pending" as const),
      retryCount: fc.constant(0),
      maxRetries: fc.constant(3),
      createdAt: fc.integer({ min: 1, max: Date.now() }),
      mimeType: fc.constantFrom("video/webm", "audio/webm;codecs=opus"),
      notificationEmittedAt: fc.option(fc.date().map((d) => d.toISOString()), {
        nil: undefined,
      }),
      titulo: fc.option(fc.string({ minLength: 1, maxLength: 40 }), { nil: undefined }),
      enlaceMeet: fc.option(
        fc.webUrl().map((u) => u),
        { nil: undefined }
      ),
    });
  }

  /**
   * Seeds a v1-schema IndexedDB database directly (old field names,
   * pre-migration index) with the given legacy jobs.
   */
  async function seedLegacyDatabase(jobs: LegacyUploadJobV1[]): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("status", "status", { unique: false });
        store.createIndex("createdAt", "createdAt", { unique: false });
        store.createIndex("claveIdempotencia", "claveIdempotencia", { unique: true });
      };
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction(STORE_NAME, "readwrite");
        const store = tx.objectStore(STORE_NAME);
        for (const job of jobs) store.add(job);
        tx.oncomplete = () => {
          db.close();
          resolve();
        };
        tx.onerror = () => reject(tx.error);
      };
      request.onerror = () => reject(request.error);
    });
  }

  it("for any set of v1 UploadJob records, opening the DB migrates them to the new field names with the same values", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.uniqueArray(arbLegacyJob(), { minLength: 1, maxLength: 5, selector: (j) => j.id }),
        async (legacyJobs) => {
          globalThis.indexedDB = new IDBFactory();
          globalThis.IDBKeyRange = IDBKeyRange;

          await seedLegacyDatabase(legacyJobs);

          // Opening the module's own DB (whose onupgradeneeded must migrate
          // v1 -> v2) is triggered by any exported operation.
          const migrated = await getPendingAndFailedJobs();

          expect(migrated).toHaveLength(legacyJobs.length);
          for (const legacy of legacyJobs) {
            const found = migrated.find((j) => j.id === legacy.id);
            expect(found).toBeDefined();
            expect(found?.idempotencyKey).toBe(legacy.claveIdempotencia);
            expect(found?.title).toBe(legacy.titulo);
            expect(found?.meetLink).toBe(legacy.enlaceMeet);
            expect(found?.sessionId).toBe(legacy.sessionId);
            expect(found?.status).toBe(legacy.status);
            // Old field names must no longer be present after migration.
            expect((found as unknown as Record<string, unknown>).claveIdempotencia).toBeUndefined();
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
