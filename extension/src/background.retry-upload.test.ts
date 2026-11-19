import { readFileSync } from "node:fs";
import { Blob as NativeBlob } from "node:buffer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sauriHealth } from "./test-backend";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";

interface Message { type: string; sessionId?: string }
type Listener = (message: Message, sender: object, reply: (value: unknown) => void) => boolean;

async function setup() {
  vi.resetModules();
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("IDBKeyRange", IDBKeyRange);
  vi.stubGlobal("Blob", NativeBlob);
  vi.stubGlobal("FormData", class {
    private fields = new Map<string, unknown>();
    append(name: string, value: unknown) { this.fields.set(name, value); }
    get(name: string) { return this.fields.get(name); }
  });
  let listener!: Listener;
  const upload = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ recording_id: "retried-recording", state: "queued" }), { status: 200 }));
  // Only ingestion uploads count; the later processing-status reads are answered with a failure.
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => String(url).endsWith("/health") ? Promise.resolve(sauriHealth()) : String(url).endsWith("/ingestion/upload") ? upload(url, init) : Promise.resolve(new Response("", { status: 503 })));
  vi.stubGlobal("chrome", {
    runtime: {
      onMessage: { addListener: (handler: Listener) => { listener = handler; } },
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: vi.fn() },
      sendMessage: vi.fn(), getURL: (path: string) => path,
    },
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined) },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    tabs: { onRemoved: { addListener: vi.fn() }, onUpdated: { addListener: vi.fn() }, query: vi.fn(async () => []), create: vi.fn(async () => ({ id: 80 })) },
    storage: {
      local: { get: vi.fn(async () => ({ sauriLocalToken: "synthetic-token" })), set: vi.fn(async () => {}), remove: vi.fn(async () => {}), setAccessLevel: vi.fn(async () => {}) },
      sync: { remove: vi.fn(async () => {}) },
      session: { remove: vi.fn(async () => {}), get: vi.fn(async () => ({ sauriState: { status: "idle", paused: false } })) },
    },
  });
  const db = await import("./recording-db");
  const queue = await import("./upload-queue");
  const startup = vi.spyOn(db, "getProcessingCompletions");
  await import("./background");
  await vi.waitFor(() => expect(startup).toHaveBeenCalledOnce());
  await startup.mock.results[0].value;

  async function seed(sessionId: string, failed: boolean) {
    await db.createCompletion({ sessionId, meetingId: `meeting-${sessionId}`, provider: "meet", capturedTabId: 7, status: "upload_failed", updatedAt: 1 });
    const job = await queue.enqueueUpload({ sessionId, meetingId: `meeting-${sessionId}`, idempotencyKey: sessionId, mimeType: "video/webm" });
    if (failed) {
      for (let attempt = 0; attempt < job.maxRetries; attempt++) await queue.markFailed(job.id, "Synthetic upload failure");
    }
    return job;
  }
  return {
    db, queue, upload, seed,
    message: (message: Message, sender = {}) => new Promise(resolve => listener(message, sender, resolve)),
  };
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("manual upload retry", () => {
  it("commits failed jobs as pending with zero attempts before using the existing processor", async () => {
    const h = await setup();
    const job = await h.seed("retry-session", true);
    await h.seed("unrelated-session", true);
    const media = new NativeBlob([readFileSync("src/fixtures/synthetic-av.webm")], { type: "video/webm" });
    await h.db.storeChunk(job.sessionId, media as Blob);
    const next = h.queue.getNextPendingJob;
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const processor = vi.spyOn(h.queue, "getNextPendingJob").mockImplementationOnce(async () => { await gate; return next(); });
    try {
      expect(await h.message({ type: "retry-upload", sessionId: job.sessionId })).toEqual({ ok: true });
      expect(processor).toHaveBeenCalledOnce();
      expect(await h.queue.getUploadJob(job.sessionId)).toMatchObject({ status: "pending", retryCount: 0, maxRetries: job.maxRetries, id: job.id, idempotencyKey: job.sessionId });
      expect(await h.queue.getUploadJob("unrelated-session")).toMatchObject({ status: "failed", retryCount: 3 });
      expect(h.upload).not.toHaveBeenCalled();
    } finally { release(); }
    await vi.waitFor(async () => expect(await h.queue.getUploadJob(job.sessionId)).toMatchObject({ status: "done", retryCount: 0 }));
    await vi.waitFor(() => expect(chrome.tabs.create).toHaveBeenCalledOnce());
    await vi.waitFor(async () => expect(await h.db.getCompletion(job.sessionId)).toMatchObject({ status: "processing_status_unavailable" }));
    expect(h.upload).toHaveBeenCalledOnce();
    const [, init] = (h.upload.mock.calls as unknown as [string, RequestInit][])[0];
    const form = init.body as FormData;
    expect((form.get("audio") as Blob).size).toBe(media.size);
    expect(JSON.parse(form.get("data") as string)).toMatchObject({ idempotency_key: job.sessionId, meeting_id: job.meetingId });
  });

  it("does not reset or process a session without failed jobs", async () => {
    const h = await setup();
    const job = await h.seed("pending-session", false);
    await h.queue.markFailed(job.id, "Transient failure");
    const before = await h.queue.getUploadJob(job.sessionId);
    const processor = vi.spyOn(h.queue, "getNextPendingJob");
    expect(await h.message({ type: "retry-upload", sessionId: job.sessionId })).toEqual({ ok: false, reason: "nothing-to-retry" });
    expect(await h.queue.getUploadJob(job.sessionId)).toEqual(before);
    expect(processor).not.toHaveBeenCalled();
    expect(h.upload).not.toHaveBeenCalled();
  });

  it.each(["unknown-session", undefined])("handles unknown or missing session %s without an uncontrolled error", async sessionId => {
    const h = await setup();
    expect(await h.message({ type: "retry-upload", sessionId })).toEqual({ ok: false, reason: "nothing-to-retry" });
    expect(h.upload).not.toHaveBeenCalled();
  });

  it("resets every failed job for the session without changing other statuses or sessions", async () => {
    const h = await setup();
    const jobs = [];
    for (const status of ["failed", "failed", "pending", "processing", "done"] as const) {
      const job = await h.queue.enqueueUpload({ sessionId: "shared-session", idempotencyKey: `legacy-${jobs.length}`, mimeType: "video/webm" });
      if (status === "failed") {
        for (let attempt = 0; attempt < job.maxRetries; attempt++) await h.queue.markFailed(job.id, "Synthetic failure");
      } else if (status === "processing") await h.queue.markProcessing(job.id);
      else if (status === "done") await h.queue.markDone(job.id);
      jobs.push((await h.queue.getUploadJob(job.idempotencyKey))!);
    }
    const unrelated = await h.seed("other-session", true);
    expect(await h.queue.resetFailedJobsForSession("shared-session")).toBe(2);
    for (const job of jobs) {
      const expected = job.status === "failed" ? { ...job, status: "pending", retryCount: 0 } : job;
      expect(await h.queue.getUploadJob(job.idempotencyKey)).toEqual(expected);
    }
    expect(await h.queue.getUploadJob(unrelated.idempotencyKey)).toMatchObject({ status: "failed", retryCount: unrelated.maxRetries });
  });

  it("reports a storage failure instead of rejecting the message handler", async () => {
    const h = await setup();
    vi.spyOn(h.queue, "resetFailedJobsForSession").mockRejectedValueOnce(new Error("Synthetic database failure"));
    expect(await h.message({ type: "retry-upload", sessionId: "retry-session" })).toEqual({ ok: false, reason: "retry-unavailable" });
    expect(h.upload).not.toHaveBeenCalled();
  });

  it("does not allow page contexts to request manual uploads", async () => {
    const h = await setup();
    await h.seed("retry-session", true);
    expect(await h.message({ type: "retry-upload", sessionId: "retry-session" }, { tab: { id: 7 } })).toMatchObject({ ok: false });
    expect(await h.queue.getUploadJob("retry-session")).toMatchObject({ status: "failed", retryCount: 3 });
    expect(h.upload).not.toHaveBeenCalled();
  });
});
