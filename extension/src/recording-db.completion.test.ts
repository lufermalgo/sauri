import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { openDB, DB_NAME, createCompletion, getCompletion, claimCompletion, getCapturingCompletion, settleCapture, getPendingFinalizations } from "./recording-db";
import * as fc from "fast-check";

beforeEach(() => { vi.stubGlobal("indexedDB", new IDBFactory()); });
afterEach(() => { vi.unstubAllGlobals(); });

it("upgrades populated v1 without changing chunks or synthesizing completion identities", async () => {
  const old = await new Promise<IDBDatabase>((resolve) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore("chunks", { keyPath: "id", autoIncrement: true });
      store.createIndex("by_session", "sessionId", { unique: false });
      store.add({ sessionId: "synthetic", timestamp: 1, blob: "preserved-media" });
    };
    request.onsuccess = () => resolve(request.result);
  });
  old.close();
  const db = await openDB();
  expect(db.version).toBe(2);
  expect(db.objectStoreNames.contains("completion_records")).toBe(true);
  const tx = db.transaction(["chunks", "completion_records"], "readonly");
  expect(tx.objectStore("chunks").keyPath).toBe("id");
  expect(tx.objectStore("chunks").index("by_session").keyPath).toBe("sessionId");
  expect(tx.objectStore("completion_records").keyPath).toBe("sessionId");
  expect(tx.objectStore("completion_records").index("capturedTabId").unique).toBe(false);
  const chunks = tx.objectStore("chunks").getAll();
  const rows = tx.objectStore("completion_records").count();
  await new Promise<void>((resolve) => { tx.oncomplete = () => resolve(); });
  expect(chunks.result).toEqual([{ id: 1, sessionId: "synthetic", timestamp: 1, blob: "preserved-media" }]);
  expect(rows.result).toBe(0);
  db.close();
});

it("commits only one concurrent claim and preserves identity across reopened connections", async () => {
  await fc.assert(fc.asyncProperty(fc.uuid(), fc.constantFrom("meet" as const, "teams" as const), fc.integer({ min: 1, max: 100000 }), async (sessionId, provider, capturedTabId) => {
    const record = { sessionId, provider, capturedTabId, meetingId: `meeting-${sessionId}`, status: "capturing" as const, updatedAt: 1 };
    await createCompletion(record);
    expect(await getCapturingCompletion(capturedTabId)).toEqual(record);
    expect(await claimCompletion(sessionId, "meeting-ended")).toBe(false);
    const results = await Promise.all([claimCompletion(sessionId, "stop"), claimCompletion(sessionId, "captured-tab-close"), claimCompletion(sessionId, "stop")]);
    expect(results.filter(Boolean)).toHaveLength(1);
    const saved = await getCompletion(sessionId);
    expect(saved).toMatchObject({ sessionId, provider, capturedTabId, meetingId: record.meetingId, status: "finalizing" });
    expect(await createCompletion(record)).toEqual(saved);
    await expect(createCompletion({ ...record, meetingId: "different" })).rejects.toThrow("identity mismatch");
    expect(await getCompletion(sessionId)).toEqual(saved);
    expect(await claimCompletion(sessionId, "stop")).toBe(false);
  }), { numRuns: 100 });
});

it("fails closed on missing and ambiguous captures without guessing a session", async () => {
  expect(await claimCompletion("missing", "stop")).toBe(false);
  for (const sessionId of ["one", "two"]) await createCompletion({ sessionId, provider: "meet", meetingId: sessionId, capturedTabId: 11, status: "capturing", updatedAt: 1 });
  await expect(getCapturingCompletion(11)).rejects.toThrow("Ambiguous");
  expect((await getCompletion("one"))?.status).toBe("capturing");
});

it("retains failed capture identity without poisoning the next capture on that tab", async () => {
  const record = { sessionId: "failed", provider: "meet" as const, capturedTabId: 11, meetingId: "first", status: "capturing" as const, updatedAt: 1 };
  await createCompletion(record);
  await settleCapture("failed", true);
  await settleCapture("failed");
  await createCompletion({ ...record, sessionId: "next", meetingId: "second" });
  expect((await getCapturingCompletion(11))?.sessionId).toBe("next");
  expect(await claimCompletion("failed", "stop")).toBe(false);
  expect(await getPendingFinalizations()).toEqual([]);
  expect(await getCompletion("failed")).toMatchObject({ meetingId: "first", captureError: true });
});

it("reports a blocked upgrade and preserves legacy chunks when retried", async () => {
  const old = await new Promise<IDBDatabase>(resolve => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore("chunks", { keyPath: "id", autoIncrement: true });
      store.createIndex("by_session", "sessionId");
      store.add({ sessionId: "legacy", blob: "media", timestamp: 1 });
    };
    request.onsuccess = () => resolve(request.result);
  });
  await expect(openDB()).rejects.toThrow("upgrade blocked");
  old.close();
  const db = await openDB();
  const request = db.transaction("chunks").objectStore("chunks").getAll();
  const rows = await new Promise(resolve => { request.onsuccess = () => resolve(request.result); });
  expect(rows).toEqual([{ id: 1, sessionId: "legacy", blob: "media", timestamp: 1 }]);
  db.close();
});

it("closes its connection on versionchange so a later upgrade is not blocked", async () => {
  const db = await openDB();
  const upgraded = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 3);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("connection failed to close"));
  });
  expect(() => db.transaction("chunks")).toThrow();
  upgraded.close();
});
