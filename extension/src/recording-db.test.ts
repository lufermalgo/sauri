import { IDBFactory } from "fake-indexeddb";
import * as fc from "fast-check";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  DB_NAME, openDB, createCompletion, getCompletion, getChunksBySession,
  claimCompletion, bindRecordingId, claimReviewLaunch,
} from "./recording-db";

beforeEach(() => { vi.stubGlobal("indexedDB", new IDBFactory()); });
afterEach(() => { vi.unstubAllGlobals(); });

it("preserves populated v1 chunks and indexes without inventing completion rows", async () => {
  const legacy = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const chunks = request.result.createObjectStore("chunks", { keyPath: "id", autoIncrement: true });
      chunks.createIndex("by_session", "sessionId", { unique: false });
      chunks.add({ sessionId: "legacy", blob: "part-one", timestamp: 1 });
      chunks.add({ sessionId: "legacy", blob: "part-two", timestamp: 2 });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  legacy.close();
  const db = await openDB();
  expect(db.version).toBe(2);
  const tx = db.transaction(["chunks", "completion_records"], "readonly");
  expect(tx.objectStore("chunks").keyPath).toBe("id");
  expect(tx.objectStore("chunks").index("by_session").keyPath).toBe("sessionId");
  expect(tx.objectStore("completion_records").keyPath).toBe("sessionId");
  expect(tx.objectStore("completion_records").index("capturedTabId").unique).toBe(false);
  const count = tx.objectStore("completion_records").count();
  await new Promise<void>(resolve => { tx.oncomplete = () => resolve(); });
  expect(count.result).toBe(0);
  db.close();
  expect(await getChunksBySession("legacy")).toEqual(["part-one", "part-two"]);
});

it("keeps one mapping and exactly one claim across retries, reloads and either capture provider (100 cases)", async () => {
  await fc.assert(fc.asyncProperty(
    fc.uuid(), fc.uuid(), fc.uuid(), fc.constantFrom("meet" as const, "teams" as const),
    fc.integer({ min: 1, max: 100000 }),
    async (sessionId, meetingId, recordingId, provider, capturedTabId) => {
      vi.stubGlobal("indexedDB", new IDBFactory());
      const record = { sessionId, meetingId, provider, capturedTabId, status: "capturing" as const, updatedAt: 1 };
      expect(await createCompletion(record)).toEqual(record);
      expect(await createCompletion(record)).toEqual(record);
      const bound = await bindRecordingId(sessionId, meetingId, recordingId);
      expect(bound.recordingId).toBe(recordingId);
      expect(await bindRecordingId(sessionId, meetingId, recordingId)).toEqual(bound);
      await expect(bindRecordingId(sessionId, `${meetingId}-wrong`, recordingId)).rejects.toThrow();
      await expect(bindRecordingId(sessionId, meetingId, `${recordingId}-wrong`)).rejects.toThrow();
      await expect(createCompletion({ ...record, meetingId: `${meetingId}-wrong` })).rejects.toThrow();
      expect((await getCompletion(sessionId))?.recordingId).toBe(recordingId);
      const claims = await Promise.all([claimCompletion(sessionId, "stop"), claimCompletion(sessionId, "captured-tab-close")]);
      expect(claims.filter(Boolean)).toHaveLength(1);
      expect((await getCompletion(sessionId))?.meetingId).toBe(meetingId);
      expect(await claimReviewLaunch(sessionId)).toBe(false);
    },
  ), { numRuns: 100 });
});

it("does not reuse a meeting across sessions or accept invalid or missing server IDs", async () => {
  const record = { sessionId: "session-a", meetingId: "meeting-a", provider: "meet" as const, capturedTabId: 12, status: "capturing" as const, updatedAt: 1 };
  await createCompletion(record);
  await expect(createCompletion({ ...record, sessionId: "session-b" })).rejects.toThrow();
  await expect(createCompletion({ ...record, sessionId: "session-c", meetingId: "" })).rejects.toThrow();
  await expect(bindRecordingId("session-a", "meeting-a", " ")).rejects.toThrow();
  await expect(bindRecordingId("missing", "meeting-a", "recording-a")).rejects.toThrow();
  expect(await getCompletion("session-b")).toBeUndefined();
  expect((await getCompletion("session-a"))?.recordingId).toBeUndefined();
  const concurrent = await Promise.allSettled([
    createCompletion({ ...record, sessionId: "session-d", meetingId: "shared" }),
    createCompletion({ ...record, sessionId: "session-e", meetingId: "shared" }),
  ]);
  expect(concurrent.filter(outcome => outcome.status === "fulfilled")).toHaveLength(1);
  expect(concurrent.filter(outcome => outcome.status === "rejected")).toHaveLength(1);
  expect(await getCompletion("session-a")).toEqual(record);
  await bindRecordingId("session-a", "meeting-a", "server-a");
  await expect(bindRecordingId("session-d", "shared", "server-a")).rejects.toThrow();
  await expect(bindRecordingId("session-e", "shared", "server-a")).rejects.toThrow();
  expect((await getCompletion("session-a"))?.recordingId).toBe("server-a");
});

it("only commits a single review claim after verified success, including concurrent attempts", async () => {
  const record = { sessionId: "review", meetingId: "meeting", provider: "teams" as const, capturedTabId: 9, status: "capturing" as const, updatedAt: 1 };
  await createCompletion(record);
  await bindRecordingId(record.sessionId, record.meetingId, "recording");
  expect(await claimReviewLaunch(record.sessionId)).toBe(false);
  const db = await openDB();
  const tx = db.transaction("completion_records", "readwrite");
  tx.objectStore("completion_records").put({ ...record, recordingId: "recording", status: "processing_succeeded" });
  await new Promise<void>(resolve => { tx.oncomplete = () => resolve(); });
  db.close();
  const claims = await Promise.all(Array.from({ length: 10 }, () => claimReviewLaunch(record.sessionId)));
  expect(claims.filter(Boolean)).toHaveLength(1);
  expect((await getCompletion(record.sessionId))?.status).toBe("review_launch_pending");
  expect(await claimReviewLaunch(record.sessionId)).toBe(false);
});
