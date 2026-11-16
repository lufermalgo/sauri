import { readFileSync } from "node:fs";
import { Blob as NativeBlob } from "node:buffer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";
import { createCompletion, getChunksBySession, getCompletion, storeChunk } from "./recording-db";
import { getNextPendingJob, type UploadJob } from "./upload-queue";

const active = {
  sessionId: "capture-session-617", meetingId: "persisted-meeting-617",
  provider: "meet" as const, capturedTabId: 617, status: "capturing" as const, updatedAt: 1,
};
const unrelated = {
  sessionId: "other-session-617", meetingId: "other-meeting-617",
  provider: "meet" as const, capturedTabId: 618, status: "capturing" as const, updatedAt: 1,
};
// Generated with ffmpeg: 0.2 s black VP8 video + 440 Hz Opus audio; ffprobe confirms both tracks.
// fake-indexeddb structuredClone preserves Node Blob, unlike jsdom's Blob.
const media = new NativeBlob([readFileSync("src/fixtures/synthetic-av.webm")], { type: "video/webm" });

type Message = { type: string; sessionId?: string; size?: number; mimeType?: string };
type MessageListener = (message: Message, sender: object, reply: (value: unknown) => void) => boolean;
type RemovedListener = (tabId: number, info: { windowId: number; isWindowClosing: boolean }) => Promise<void>;

async function jobs(): Promise<UploadJob[]> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("sauri-upload-queue", 2);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  if (!db.objectStoreNames.contains("jobs")) { db.close(); return []; }
  return new Promise((resolve, reject) => {
    const tx = db.transaction("jobs", "readonly");
    const request = tx.objectStore("jobs").getAll();
    request.onsuccess = () => resolve(request.result as UploadJob[]);
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

async function setup() {
  vi.resetModules();
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("IDBKeyRange", IDBKeyRange);
  // jsdom's Blob is not structured-cloneable by fake-indexeddb. Use native
  // binary primitives at this storage/network boundary to verify real bytes.
  vi.stubGlobal("Blob", NativeBlob);
  vi.stubGlobal("FormData", class {
    private fields = new Map<string, string | NativeBlob>();
    append(name: string, value: string | NativeBlob) { this.fields.set(name, value); }
    get(name: string) { return this.fields.get(name) ?? null; }
  });
  await createCompletion(active);
  await createCompletion(unrelated);
  await storeChunk(active.sessionId, media as Blob); // Real muxed WebM contract: one audio+video container, not two uploads.
  await storeChunk(unrelated.sessionId, new Blob(["unrelated media"], { type: "video/webm" }));
  // Initialize the actual queue schema before inspecting it; do not create an empty v2 database.
  expect(await getNextPendingJob()).toBeNull();
  const queue = await import("./upload-queue");
  const actualEnqueue = queue.enqueueUpload;
  let firstJob: Awaited<ReturnType<typeof actualEnqueue>> | undefined;
  // Observe duplicate enqueue attempts without allowing the background listener's void
  // handler to reject asynchronously on the unique-index constraint.
  const enqueue = vi.spyOn(queue, "enqueueUpload").mockImplementation(async input => {
    if (firstJob) return firstJob;
    firstJob = await actualEnqueue(input);
    return firstJob;
  });

  let state: { status: string; sessionId?: string; tabId?: number; videoPresence?: string } = {
    status: "recording", sessionId: active.sessionId, tabId: active.capturedTabId, videoPresence: "muxed",
  };
  let onMessage: MessageListener | undefined;
  let onRemoved: RemovedListener | undefined;
  const stops: Message[] = [];
  const fetchMock = vi.fn(async (_url: string, _options: RequestInit) => new Response("offline", { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("chrome", {
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    runtime: {
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: vi.fn() },
      onMessage: { addListener: (listener: MessageListener) => { onMessage = listener; } },
      getURL: (path: string) => path, getContexts: vi.fn(async () => []),
      sendMessage: vi.fn(async (message: Message) => { if (message.type === "stop-recording") stops.push(message); return { ok: true }; }),
    },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    storage: {
      session: {
        get: vi.fn(async () => ({ sauriState: { ...state } })),
        set: vi.fn(async (value: { sauriState: typeof state }) => { state = { ...value.sauriState }; }),
      },
      sync: { get: vi.fn(async () => ({})) },
    },
    tabs: {
      onRemoved: { addListener: (listener: RemovedListener) => { onRemoved = listener; } },
      onUpdated: { addListener: vi.fn() },
      query: vi.fn(async () => []), sendMessage: vi.fn(async () => undefined),
    },
  });
  await import("./background");
  expect(onMessage).toBeDefined();
  expect(onRemoved).toBeDefined();
  return {
    stops, fetchMock, enqueue,
    async message(message: Message) {
      const reply = vi.fn();
      onMessage!(message, {}, reply);
      await vi.waitFor(() => expect(reply).toHaveBeenCalled());
    },
    async close() { await onRemoved!(active.capturedTabId, { windowId: 1, isWindowClosing: false }); },
    async finished() {
      await this.message({ type: "recording-stopped", sessionId: active.sessionId, size: media.size, mimeType: media.type });
      await vi.waitFor(async () => expect(await jobs()).toMatchObject([{ status: "pending", retryCount: 1 }]));
      await vi.waitFor(() => expect(state.status).toBe("idle"));
    },
  };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("T1.8 / #617: finalization to automatic upload queue (R1.3–4, R2.1–2, R2.6)", () => {
  it.each(["stop", "captured-tab-close"] as const)("%s enqueues the finalized muxed audio/video under its persisted identity without an upload action", async trigger => {
    const h = await setup();
    if (trigger === "stop") await h.message({ type: "stop-capture" });
    else await h.close();
    expect(h.stops).toEqual([{ type: "stop-recording", sessionId: active.sessionId }]);
    expect(await jobs()).toEqual([]); // A stop request alone is not finalized media.
    await h.finished(); // The offscreen boundary reports finalized media; no user upload message.
    const [job] = await jobs();
    expect(job).toMatchObject({
      sessionId: active.sessionId, idempotencyKey: active.sessionId,
      meetingId: active.meetingId, mimeType: media.type, videoPresence: "muxed",
    });
    expect(await getChunksBySession(active.sessionId)).toHaveLength(1);
    expect((await getChunksBySession(active.sessionId))[0]).toMatchObject({ size: media.size, type: media.type });
    expect(await getCompletion(active.sessionId)).toMatchObject({ meetingId: active.meetingId, status: "upload_failed" });
    expect(await getCompletion(unrelated.sessionId)).toMatchObject(unrelated);
    expect(await getChunksBySession(unrelated.sessionId)).toHaveLength(1);
    await vi.waitFor(() => expect(h.fetchMock).toHaveBeenCalledTimes(1));
    const payload = h.fetchMock.mock.calls[0][1].body as FormData;
    expect(JSON.parse(payload.get("data") as string)).toMatchObject({
      idempotency_key: active.sessionId, meeting_id: active.meetingId, video_presence: "muxed",
    });
    expect(payload.get("audio")).toBeInstanceOf(Blob); // One muxed WebM, not invented separate uploads.
    expect((payload.get("audio") as Blob).size).toBe(media.size);
  });

  it("repeated Stop, tab close and recording-stopped never enqueue another job for that session", async () => {
    const h = await setup();
    await h.message({ type: "stop-capture" });
    await h.close();
    await h.finished();
    const [original] = await jobs();
    await h.message({ type: "stop-capture" });
    await h.close();
    await h.message({ type: "recording-stopped", sessionId: active.sessionId, size: media.size, mimeType: media.type });
    await new Promise(resolve => setTimeout(resolve, 50)); // Allow the async recording-stopped handler to finish.
    expect((await jobs()).map(job => job.id)).toEqual([original.id]);
    expect(h.stops).toEqual([{ type: "stop-recording", sessionId: active.sessionId }]);
    expect(h.enqueue).toHaveBeenCalledTimes(1);
    expect(h.fetchMock).toHaveBeenCalledTimes(1);
    expect(await getCompletion(unrelated.sessionId)).toMatchObject(unrelated);
  });
});
