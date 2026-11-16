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

import { describe, it, expect, beforeEach, beforeAll, afterAll, vi } from "vitest";
import * as fc from "fast-check";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";

import { enqueueUpload, getPendingAndFailedJobs, getUploadJob, markProcessing, type EnqueueUploadInput, type UploadJob } from "./upload-queue";
import { createCompletion, getCompletion } from "./recording-db";

const { assembleBlob, clearSession } = vi.hoisted(() => ({
  assembleBlob: vi.fn(async () => new Blob(["synthetic media"], { type: "video/webm" })),
  clearSession: vi.fn(async () => undefined),
}));
vi.mock("./recording-db", async (importOriginal) => ({
  ...await importOriginal<typeof import("./recording-db")>(), assembleBlob, clearSession,
}));

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

  it("atomically claims one attempt under concurrent queue drains (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(fc.uuid(), fc.uuid(), async (sessionId, meetingId) => {
      globalThis.indexedDB = new IDBFactory();
      const job = await enqueueUpload({ sessionId, meetingId, idempotencyKey: sessionId, mimeType: "video/webm" });
      const claims = await Promise.all(Array.from({ length: 3 }, () => markProcessing(job.id)));
      expect(claims.filter(Boolean)).toHaveLength(1);
      expect(await getUploadJob(sessionId)).toMatchObject({ id: job.id, meetingId, status: "processing" });
    }), { numRuns: 100 });
  });
});

// T1.3 (#612): uploadRecording/processUploadQueue are private to background.ts,
// so exercise the real worker via its existing onStartup listener (no invented export).
// The ingestion response contract is { recording_id, state }; meeting_id is
// supplied by the request and must match the persisted completion record.
type Identity = { sessionId: string; meetingId: string; recordingId: string };
const arbIdentity: fc.Arbitrary<Identity> = fc.record({
  sessionId: fc.uuid(), meetingId: fc.uuid(), recordingId: fc.uuid(),
});
const accepted = (recordingId: string) => new Response(
  JSON.stringify({ recording_id: recordingId, state: "queued" }), { status: 200 },
);

async function storedUploadJob(): Promise<UploadJob | undefined> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open("sauri-upload-queue", 2);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return new Promise((resolve, reject) => {
    const tx = db.transaction("jobs", "readonly");
    const req = tx.objectStore("jobs").getAll();
    req.onsuccess = () => resolve((req.result as UploadJob[])[0]);
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}

async function awaitStatus(status: "pending" | "done", retryCount: number): Promise<UploadJob> {
  let job: UploadJob | undefined;
  await vi.waitFor(async () => {
    job = await storedUploadJob();
    expect(job).toMatchObject({ status, retryCount });
  }, { interval: 5, timeout: 800 });
  return job!;
}

async function awaitSettled(): Promise<UploadJob> {
  let job: UploadJob | undefined;
  await vi.waitFor(async () => {
    job = await storedUploadJob();
    expect(job?.status === "done" || job?.retryCount === 1).toBe(true);
  }, { interval: 5, timeout: 800 });
  return job!;
}

describe("T1.3 (#612): truthful upload result and stable retry identity (RED)", () => {
  let startup: (() => void) | undefined;
  const nativeFetch = globalThis.fetch;

  beforeAll(async () => {
    vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.stubGlobal("chrome", {
      action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
      alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
      runtime: {
        onInstalled: { addListener: vi.fn() }, onMessage: { addListener: vi.fn() },
        onStartup: { addListener: (listener: () => void) => { startup = listener; } },
        getContexts: vi.fn(async () => []), getURL: (path: string) => path, sendMessage: vi.fn(),
      },
      sidePanel: { setPanelBehavior: vi.fn(async () => undefined) },
      storage: { session: { get: vi.fn(async () => ({ sauriSessionToken: "synthetic-token" })) } },
      tabs: { onRemoved: { addListener: vi.fn() }, onUpdated: { addListener: vi.fn() } },
    });
    await import("./background");
    expect(startup).toBeTypeOf("function");
  });
  afterAll(() => {
    globalThis.fetch = nativeFetch;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function enqueueFor(identity: Identity): Promise<void> {
    globalThis.indexedDB = new IDBFactory();
    globalThis.IDBKeyRange = IDBKeyRange;
    clearSession.mockClear();
    await createCompletion({
      sessionId: identity.sessionId, meetingId: identity.meetingId,
      provider: "meet", capturedTabId: 123, status: "upload_pending", updatedAt: 1,
    });
    await enqueueUpload({ sessionId: identity.sessionId, meetingId: identity.meetingId, idempotencyKey: identity.sessionId, mimeType: "video/webm" });
  }

  it("settles a valid response only for the persisted meeting/session mapping (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(arbIdentity, async (identity) => {
      await enqueueFor(identity);
      const requests: Array<{ meeting_id: string; idempotency_key: string }> = [];
      globalThis.fetch = vi.fn(async (_url, init) => {
        requests.push(JSON.parse((init!.body as FormData).get("data") as string));
        return accepted(identity.recordingId);
      }) as typeof fetch;
      startup!();
      await awaitStatus("done", 0);
      await vi.waitFor(() => expect(clearSession).toHaveBeenCalledWith(identity.sessionId));
      await vi.waitFor(async () => expect(await getCompletion(identity.sessionId)).toMatchObject({
        status: "processing_status_unavailable", recordingId: identity.recordingId,
      })); // Upload settled; no auth token means protected processing state is unavailable, not ready.
      expect(requests).toHaveLength(1);
      expect(requests[0]).toMatchObject({ meeting_id: identity.meetingId, idempotency_key: identity.sessionId });
    }), { numRuns: 100 });
  });

  it("persists the accepted recordingId for recovery of the same recording (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(arbIdentity, async (identity) => {
      await enqueueFor(identity);
      globalThis.fetch = vi.fn(async () => accepted(identity.recordingId)) as typeof fetch;
      startup!();
      await awaitStatus("done", 0);
      await vi.waitFor(() => expect(clearSession).toHaveBeenCalledWith(identity.sessionId));
      expect(await getCompletion(identity.sessionId)).toMatchObject({
        sessionId: identity.sessionId, meetingId: identity.meetingId, recordingId: identity.recordingId,
      });
    }), { numRuns: 100 });
  });

  it("rejects a response that would replace an already bound recordingId (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(arbIdentity, fc.uuid(), async (identity, differentRecordingId) => {
      fc.pre(differentRecordingId !== identity.recordingId);
      await enqueueFor(identity);
      // Use the real durable fixture, not a mock of the production binding API.
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const req = indexedDB.open("sauri-recordings", 2);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction("completion_records", "readwrite");
        tx.objectStore("completion_records").put({
          sessionId: identity.sessionId, meetingId: identity.meetingId, recordingId: identity.recordingId,
          provider: "meet", capturedTabId: 123, status: "upload_pending", updatedAt: 1,
        });
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = tx.onabort = () => { db.close(); reject(tx.error); };
      });
      globalThis.fetch = vi.fn(async () => accepted(differentRecordingId)) as typeof fetch;
      startup!();
      const job = await awaitSettled();
      const durable = await getCompletion(identity.sessionId);
      // Check preservation even when the subsequent queue-result assertion fails.
      expect(durable?.recordingId).toBe(identity.recordingId);
      expect(durable?.meetingId).toBe(identity.meetingId);
      expect(job).toMatchObject({ status: "pending", retryCount: 1, sessionId: identity.sessionId });
      expect(clearSession).not.toHaveBeenCalled();
    }), { numRuns: 100 });
  });

  it("keeps network errors retryable without clearing media (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(arbIdentity, fc.string({ minLength: 1, maxLength: 30 }), async (identity, reason) => {
      await enqueueFor(identity);
      globalThis.fetch = vi.fn(async () => { throw new TypeError(`synthetic network failure: ${reason}`); }) as typeof fetch;
      startup!();
      const job = await awaitStatus("pending", 1);
      expect(job.sessionId).toBe(identity.sessionId);
      expect(job.errorMessage).toContain("synthetic network failure");
      expect(clearSession).not.toHaveBeenCalled();
    }), { numRuns: 100 });
  });

  it("keeps non-2xx responses retryable without clearing media (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(arbIdentity, fc.constantFrom(400, 401, 403, 409, 429, 500, 503), async (identity, code) => {
      await enqueueFor(identity);
      globalThis.fetch = vi.fn(async () => new Response("rejected", { status: code })) as typeof fetch;
      startup!();
      const job = await awaitStatus("pending", 1);
      expect(job.sessionId).toBe(identity.sessionId);
      expect(clearSession).not.toHaveBeenCalled();
    }), { numRuns: 100 });
  });

  it("never reports success for a 2xx response with invalid recording_id/state (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(arbIdentity, fc.constantFrom(
      JSON.stringify({ accepted: true }), JSON.stringify({ recording_id: "", state: "queued" }),
      JSON.stringify({ recording_id: "unrelated", state: "unknown" }), "not-json",
    ), async (identity, body) => {
      await enqueueFor(identity);
      globalThis.fetch = vi.fn(async () => new Response(body, { status: 200 })) as typeof fetch;
      startup!();
      const job = await awaitSettled();
      expect(job).toMatchObject({ status: "pending", retryCount: 1, sessionId: identity.sessionId });
      expect(await getCompletion(identity.sessionId)).toMatchObject({ meetingId: identity.meetingId, status: "upload_failed" });
      expect((await getCompletion(identity.sessionId))?.recordingId).toBeUndefined();
      expect(clearSession).not.toHaveBeenCalled();
    }), { numRuns: 100 });
  });

  it("retries the same persisted meeting_id and session id before settling (100 cases)", async () => {
    await fc.assert(fc.asyncProperty(arbIdentity, fc.constantFrom(408, 503), async (identity, firstStatus) => {
      await enqueueFor(identity);
      const attempts: Array<{ meeting_id: string; idempotency_key: string }> = [];
      globalThis.fetch = vi.fn(async (_url, init) => {
        attempts.push(JSON.parse((init!.body as FormData).get("data") as string));
        return attempts.length === 1 ? new Response("retry", { status: firstStatus }) : accepted(identity.recordingId);
      }) as typeof fetch;
      startup!();
      await awaitStatus("pending", 1);
      startup!();
      const job = await awaitStatus("done", 1);
      expect(job.sessionId).toBe(identity.sessionId);
      expect(attempts).toHaveLength(2);
      expect(attempts[0]).toMatchObject({ idempotency_key: identity.sessionId, meeting_id: identity.meetingId });
      expect(attempts[1]).toMatchObject(attempts[0]);
      await vi.waitFor(() => expect(clearSession).toHaveBeenCalledWith(identity.sessionId));
      expect(clearSession).toHaveBeenCalledTimes(1);
    }), { numRuns: 100 });
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
