import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";
import { createCompletion } from "./recording-db";

const { assembleBlob, clearSession } = vi.hoisted(() => ({
  assembleBlob: vi.fn(async () => new Blob(["synthetic recording"])),
  clearSession: vi.fn(async () => undefined),
}));
vi.mock("./recording-db", async (importOriginal) => ({
  ...await importOriginal<typeof import("./recording-db")>(), assembleBlob, clearSession,
}));

interface ChromeMessageListener {
  (message: { type: string; size?: number; mimeType?: string; sessionId?: string }, sender: unknown, sendResponse: (response: unknown) => void): void;
}

async function readStoredJobs(): Promise<Array<{ status: string; retryCount: number; errorMessage?: string }>> {
  try {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("sauri-upload-queue", 2);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    if (!db.objectStoreNames.contains("jobs")) { db.close(); return []; }
    return await new Promise((resolve, reject) => {
      const request = db.transaction("jobs", "readonly").objectStore("jobs").getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.transaction!.oncomplete = () => db.close();
    });
  } catch {
    return [];
  }
}

async function waitForStoredStatus(status: string) {
  // Let the recording-stopped listener enqueue before inspection opens the database.
  await new Promise((resolve) => setTimeout(resolve, 30));
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const jobs = await readStoredJobs();
    if (jobs.some((job) => job.status === status)) return jobs;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  return readStoredJobs();
}

async function runUpload(fetchImplementation: typeof fetch) {
  vi.resetModules();
  globalThis.indexedDB = new IDBFactory();
  globalThis.IDBKeyRange = IDBKeyRange;
  globalThis.fetch = ((url: string, init?: RequestInit) => url.endsWith("/health") ? Promise.resolve(new Response("{}")) : fetchImplementation(url, init)) as typeof fetch;
  assembleBlob.mockClear();
  clearSession.mockClear();
  await createCompletion({
    sessionId: "synthetic-session", meetingId: "synthetic-meeting", provider: "meet",
    capturedTabId: 7, status: "finalizing", updatedAt: 1,
  });

  let messageListener: ChromeMessageListener | undefined;
  vi.stubGlobal("chrome", {
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    runtime: {
      onInstalled: { addListener: vi.fn() }, onMessage: { addListener: (listener: ChromeMessageListener) => { messageListener = listener; } },
      onStartup: { addListener: vi.fn() }, getURL: (path: string) => path, getContexts: vi.fn(async () => []), sendMessage: vi.fn(),
    },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    storage: {
      local: { get: vi.fn(async () => ({ sauriLocalToken: "synthetic-token" })), set: vi.fn(async () => {}), remove: vi.fn(async () => {}), setAccessLevel: vi.fn(async () => {}) },
      sync: { remove: vi.fn(async () => {}) },
      session: { remove: vi.fn(async () => {}), get: vi.fn(async () => ({ sauriState: { status: "idle" } })), set: vi.fn(async () => undefined) },
    },
    tabs: { onRemoved: { addListener: vi.fn() }, onUpdated: { addListener: vi.fn() }, query: vi.fn(async () => []), create: vi.fn(async () => ({ id: 614 })), sendMessage: vi.fn(async () => undefined) },
  });

  await import("./background");
  messageListener!({ type: "recording-stopped", size: 20, mimeType: "video/webm", sessionId: "synthetic-session" }, {}, vi.fn());
}

describe("upload failures must remain retryable", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it.each([
    ["HTTP rejection", vi.fn(async () => new Response("rejected", { status: 503 })), 1],
    ["network rejection", vi.fn(async () => { throw new TypeError("synthetic network failure"); }), 0],
  ])("keeps %s retryable and preserves the recording", async (_label, fetchImplementation, retryCount) => {
    await runUpload(fetchImplementation as typeof fetch);
    const jobs = await waitForStoredStatus("pending");
    expect(jobs).toHaveLength(1);
    expect(jobs[0]).toMatchObject({ status: "pending", retryCount });
    if (retryCount) expect(jobs[0].errorMessage).toBeTruthy();
    expect(clearSession).not.toHaveBeenCalled();
    expect(chrome.tabs.create).not.toHaveBeenCalled();
  });

  it("persists a successful upload as done and clears its recording", async () => {
    await runUpload(vi.fn(async () => new Response(JSON.stringify({ recording_id: "synthetic-recording", state: "queued" }), { status: 200 })) as typeof fetch);
    const jobs = await waitForStoredStatus("done");
    expect(jobs).toHaveLength(1);
    expect(jobs[0]).toMatchObject({ status: "done", retryCount: 0 });
    expect(clearSession).toHaveBeenCalledWith("synthetic-session");
    expect(chrome.tabs.create).toHaveBeenCalledTimes(1);
    expect(chrome.tabs.create).toHaveBeenCalledWith({ url: "http://localhost:8000/?meetingId=synthetic-meeting" });
  });
});
