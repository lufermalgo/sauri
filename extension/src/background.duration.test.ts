import { Blob as NativeBlob } from "node:buffer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";

interface Message { type: string; sessionId?: string; size?: number; mimeType?: string; durationSeconds?: unknown }
type Listener = (message: Message, sender: object, reply: (value: unknown) => void) => unknown;

const ok = () => new Response(JSON.stringify({ recording_id: "rec-1", state: "queued" }), { status: 200 });

// One browser profile: the IndexedDB factory survives restart() like the real stores do.
function profile() {
  const idb = new IDBFactory();
  const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ok());
  let listener!: Listener;
  let startup!: () => void;

  async function boot() {
    vi.resetModules();
    vi.stubGlobal("indexedDB", idb);
    vi.stubGlobal("IDBKeyRange", IDBKeyRange);
    vi.stubGlobal("Blob", NativeBlob);
    vi.stubGlobal("FormData", class {
      private fields = new Map<string, unknown>();
      append(name: string, value: unknown) { this.fields.set(name, value); }
      get(name: string) { return this.fields.get(name); }
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("chrome", {
      runtime: {
        onMessage: { addListener: (handler: Listener) => { listener = handler; } },
        onInstalled: { addListener: vi.fn() }, onStartup: { addListener: (handler: () => void) => { startup = handler; } },
        sendMessage: vi.fn(), getURL: (path: string) => path, getContexts: vi.fn(async () => []),
      },
      action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
      sidePanel: { setPanelBehavior: vi.fn(async () => undefined) },
      alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
      tabs: { onRemoved: { addListener: vi.fn() }, onUpdated: { addListener: vi.fn() }, query: vi.fn(async () => []), create: vi.fn(async () => ({ id: 80 })), sendMessage: vi.fn() },
      storage: {
      local: { get: vi.fn(async () => ({ sauriLocalToken: "synthetic-token" })), set: vi.fn(async () => {}), remove: vi.fn(async () => {}), setAccessLevel: vi.fn(async () => {}) },
      sync: { remove: vi.fn(async () => {}) },
        session: { remove: vi.fn(async () => {}), get: vi.fn(async () => ({ sauriState: { status: "idle", paused: false } })), set: vi.fn(async () => undefined) },
      },
    });
    const db = await import("./recording-db");
    const queue = await import("./upload-queue");
    await import("./background");
    return { db, queue };
  }

  const sentDurations = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/ingestion/upload")).map(([, init]) => JSON.parse(((init.body as unknown as { get(n: string): string }).get("data"))).duration_seconds);
  const sentPayloads = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/ingestion/upload")).map(([, init]) => JSON.parse(((init.body as unknown as { get(n: string): string }).get("data"))));
  return {
    boot, fetchMock, sentDurations, sentPayloads,
    message: (message: Message) => new Promise(resolve => listener(message, {}, resolve)),
    startup: () => startup(),
  };
}

async function seedCapture(db: typeof import("./recording-db"), sessionId: string, startedAt?: number) {
  await db.createCompletion({ sessionId, meetingId: `meeting-${sessionId}`, provider: "meet", capturedTabId: 7, status: "finalizing", updatedAt: 1, startedAt });
  await db.storeChunk(sessionId, new NativeBlob(["media"]) as Blob);
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("recorded duration in the upload payload", () => {
  it("persists the reported duration on the job and sends it instead of 0", async () => {
    const p = profile();
    const { db, queue } = await p.boot();
    await seedCapture(db, "s1");
    await p.message({ type: "recording-stopped", sessionId: "s1", size: 5, mimeType: "video/webm", durationSeconds: 37 });
    await vi.waitFor(async () => expect(await queue.getUploadJob("s1")).toMatchObject({ status: "done", durationSeconds: 37 }));
    expect(p.sentDurations()).toEqual([37]);
  });

  it("keeps the value across failed attempts and a manual retry", async () => {
    const p = profile();
    p.fetchMock.mockImplementation(async url => String(url).endsWith("/health") ? new Response("{}") : new Response("down", { status: 503 }));
    const { db, queue } = await p.boot();
    await seedCapture(db, "s2");
    await p.message({ type: "recording-stopped", sessionId: "s2", size: 5, mimeType: "video/webm", durationSeconds: 120 });
    await vi.waitFor(async () => expect(await queue.getUploadJob("s2")).toMatchObject({ status: "pending", retryCount: 1, durationSeconds: 120 }));
    for (let attempt = 1; attempt < 3; attempt++) {
      await queue.markProcessing((await queue.getUploadJob("s2"))!.id);
      await queue.markFailed((await queue.getUploadJob("s2"))!.id, "still down");
    }
    expect(await queue.getUploadJob("s2")).toMatchObject({ status: "failed", durationSeconds: 120 });

    p.fetchMock.mockImplementation(async () => ok());
    expect(await p.message({ type: "retry-upload", sessionId: "s2" })).toEqual({ ok: true });
    await vi.waitFor(async () => expect(await queue.getUploadJob("s2")).toMatchObject({ status: "done", durationSeconds: 120 }));
    expect(p.sentDurations().at(-1)).toBe(120);
  });

  it("sends the persisted value after a service worker restart", async () => {
    const p = profile();
    p.fetchMock.mockImplementation(async () => { throw new TypeError("offline"); });
    const first = await p.boot();
    await seedCapture(first.db, "s3");
    await p.message({ type: "recording-stopped", sessionId: "s3", size: 5, mimeType: "video/webm", durationSeconds: 61 });
    await vi.waitFor(async () => expect(await first.queue.getUploadJob("s3")).toMatchObject({ status: "pending", durationSeconds: 61 }));

    p.fetchMock.mockClear();
    p.fetchMock.mockImplementation(async () => ok());
    const restarted = await p.boot();
    p.startup();
    await vi.waitFor(async () => expect(await restarted.queue.getUploadJob("s3")).toMatchObject({ status: "done" }));
    expect(p.sentDurations()).toEqual([61]);
  });

  it.each([0, -3, 2.5, "9", null, undefined])("does not persist an invalid duration (%s)", async invalid => {
    const p = profile();
    const { db, queue } = await p.boot();
    await seedCapture(db, "s4");
    await p.message({ type: "recording-stopped", sessionId: "s4", size: 5, mimeType: "video/webm", durationSeconds: invalid });
    await vi.waitFor(async () => expect(await queue.getUploadJob("s4")).toMatchObject({ status: "done" }));
    expect((await queue.getUploadJob("s4"))!.durationSeconds).toBeUndefined();
    expect(p.sentDurations()).toEqual([0]);
  });

  it("still uploads a job queued before the field existed", async () => {
    const p = profile();
    const { db, queue } = await p.boot();
    await seedCapture(db, "legacy");
    await queue.enqueueUpload({ sessionId: "legacy", meetingId: "meeting-legacy", idempotencyKey: "legacy", mimeType: "video/webm" });
    p.startup();
    await vi.waitFor(async () => expect(await queue.getUploadJob("legacy")).toMatchObject({ status: "done" }));
    expect(p.sentDurations()).toEqual([0]);
  });

  it("sends the moment capture began as the recording date", async () => {
    const p = profile();
    const { db, queue } = await p.boot();
    await seedCapture(db, "s5", Date.UTC(2026, 10, 3, 15, 30, 0));
    await p.message({ type: "recording-stopped", sessionId: "s5", size: 5, mimeType: "video/webm", durationSeconds: 20 });
    await vi.waitFor(async () => expect(await queue.getUploadJob("s5")).toMatchObject({ status: "done" }));
    expect(p.sentPayloads().map(payload => payload.recorded_at)).toEqual(["2026-11-03T15:30:00.000Z"]);
  });

  it("leaves the recording date out when the capture record has no start", async () => {
    const p = profile();
    const { db, queue } = await p.boot();
    await seedCapture(db, "s6");
    await p.message({ type: "recording-stopped", sessionId: "s6", size: 5, mimeType: "video/webm", durationSeconds: 20 });
    await vi.waitFor(async () => expect(await queue.getUploadJob("s6")).toMatchObject({ status: "done" }));
    expect(p.sentPayloads()[0]).not.toHaveProperty("recorded_at");
  });
});
