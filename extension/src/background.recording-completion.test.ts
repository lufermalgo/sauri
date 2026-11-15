import { afterEach, expect, it, vi } from "vitest";
import * as fc from "fast-check";
import { IDBFactory } from "fake-indexeddb";
import { createCompletion, settleCapture, getCompletion, claimCompletion } from "./recording-db";
import { getUploadJob } from "./upload-queue";

// Each property executes 100 real IndexedDB/restart sequences. The default
// five-second test deadline can expire while those sequences are still running,
// leaking their async work into the next test's replacement Chrome/IDB globals.
// Keep every sequence/assertion; allow the property to finish under suite load.
vi.setConfig({ testTimeout: 30_000 });

type Event = "stop" | "close" | "meeting-ended";

async function harness(sessionId: string, tabId: number, legacy = false) {
  vi.resetModules();
  vi.stubGlobal("indexedDB", new IDBFactory());
  if (!legacy) await createCompletion({ sessionId, provider: "meet", meetingId: `meeting-${sessionId}`, capturedTabId: tabId, status: "capturing", updatedAt: 1 });
  let state: Record<string, unknown> = { status: "recording", sessionId, tabId };
  let onRemoved: (id: number, info: object) => unknown;
  let onMessage: (message: object, sender: object, reply: () => void) => unknown;
  const sendMessage = vi.fn(async (message?: { type: string; sessionId?: string }) => {
    if (message?.type === "stop-recording" && message.sessionId) await settleCapture(message.sessionId);
    return { ok: true };
  });
  vi.stubGlobal("chrome", {
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    runtime: {
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: vi.fn() },
      onMessage: { addListener: (fn: typeof onMessage) => { onMessage = fn; } },
      getURL: (path: string) => path, getContexts: vi.fn(async () => []), sendMessage,
    },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    storage: {
      session: {
        get: vi.fn(async () => ({ sauriState: structuredClone(state) })),
        set: vi.fn(async (value: { sauriState: Record<string, unknown> }) => { state = structuredClone(value.sauriState); }),
      },
      sync: { get: vi.fn(async () => ({})) },
    },
    tabs: {
      onRemoved: { addListener: (fn: typeof onRemoved) => { onRemoved = fn; } },
      query: vi.fn(async () => []), sendMessage: vi.fn(async () => undefined),
    },
  });
  await import("./background");
  return {
    state: () => state,
    sendMessage,
    async message(message: object) {
      onMessage(message, {}, () => {});
      await new Promise(resolve => setTimeout(resolve, 15));
    },
    async restartWithoutProjection() {
      state = { status: "idle" };
      vi.resetModules();
      await import("./background");
      await new Promise(resolve => setTimeout(resolve, 15));
    },
    stops: () => sendMessage.mock.calls.filter(([message]) => (message as unknown as { type: string })?.type === "stop-recording").length,
    async event(event: Event) {
      if (event === "close") await onRemoved(tabId, { windowId: 1, isWindowClosing: false });
      else await new Promise<void>((resolve) => { onMessage({ type: event === "stop" ? "stop-capture" : "meet-ended" }, {}, resolve); });
      // Existing listeners start async handlers without returning their promise.
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    },
  };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const identity = fc.tuple(fc.uuid(), fc.integer({ min: 1, max: 100000 }));

it.each(["stop", "close"] as const)("%s independently finalizes the active capture", async (event) => {
  await fc.assert(fc.asyncProperty(identity, async ([session, tab]) => {
    const h = await harness(session, tab);
    await h.event(event);
    expect(h.stops()).toBe(1);
  }), { numRuns: 100 });
});

it("tab close finds the durable capture after worker reload without UI state", async () => {
  await fc.assert(fc.asyncProperty(identity, async ([session, tab]) => {
    const h = await harness(session, tab);
    await h.restartWithoutProjection();
    await h.event("close");
    expect(h.stops()).toBe(1);
    await h.restartWithoutProjection();
    await h.event("close");
    expect(h.stops()).toBe(1);
  }), { numRuns: 100 });
});

it("concurrent Stop and tab close dispatch only one finalization", async () => {
  await fc.assert(fc.asyncProperty(identity, async ([session, tab]) => {
    const h = await harness(session, tab);
    await Promise.all([h.event("stop"), h.event("close"), h.event("stop")]);
    expect(h.stops()).toBe(1);
  }), { numRuns: 100 });
});

it("both trigger orders and duplicates converge on one finalization", async () => {
  await fc.assert(fc.asyncProperty(identity, fc.boolean(), fc.integer({ min: 1, max: 8 }), async ([session, tab], stopFirst, repeats) => {
    const h = await harness(session, tab);
    for (let i = 0; i < repeats; i++) {
      await h.event(stopFirst ? "stop" : "close");
      await h.event(stopFirst ? "close" : "stop");
    }
    expect(h.stops()).toBe(1);
    expect(h.state().sessionId).toBe(session);
  }), { numRuns: 100 });
});

it.each(["stop", "close"] as const)("%s preserves a live legacy session without inventing a mapping", async event => {
  const h = await harness("legacy", 41, true);
  await h.event(event);
  expect(h.sendMessage).toHaveBeenCalledWith({ type: "stop-recording", sessionId: "legacy" });
  expect(await getCompletion("legacy")).toBeUndefined();
});

it("replays a committed intent after crash before dispatch, preserving identity", async () => {
  const h = await harness("crash-session", 42);
  await claimCompletion("crash-session", "stop");
  expect(h.stops()).toBe(0);
  await h.restartWithoutProjection();
  expect(h.sendMessage).toHaveBeenCalledWith({ type: "stop-recording", sessionId: "crash-session" });
  expect((await getCompletion("crash-session"))?.status).toBe("upload_pending");
});

it("retries delivery failure on worker restart without releasing the claim", async () => {
  const h = await harness("retry-session", 43);
  h.sendMessage.mockRejectedValueOnce(new Error("offscreen unavailable"));
  await h.event("stop");
  expect((await getCompletion("retry-session"))?.status).toBe("finalizing");
  await h.restartWithoutProjection();
  expect(h.stops()).toBe(2);
  expect((await getCompletion("retry-session"))?.status).toBe("upload_pending");
});

it("capture failure retires the tab lookup without discarding identity", async () => {
  const h = await harness("failed-session", 44);
  await h.message({ type: "recording-error", sessionId: "failed-session" });
  await h.event("close");
  expect(h.stops()).toBe(0);
  expect(await getCompletion("failed-session")).toMatchObject({ captureError: true, meetingId: "meeting-failed-session" });
});

it("meeting-ended preserves active identity and a later tab-close still finalizes", async () => {
  await fc.assert(fc.asyncProperty(identity, fc.integer({ min: 1, max: 8 }), async ([session, tab], repeats) => {
    const h = await harness(session, tab);
    for (let i = 0; i < repeats; i++) await h.event("meeting-ended");
    expect(h.stops()).toBe(0);
    expect(h.state()).toMatchObject({ status: "recording", sessionId: session, tabId: tab });
    expect(await getCompletion(session)).toMatchObject({ status: "capturing", meetingId: `meeting-${session}` });
    expect(await getUploadJob(session)).toBeUndefined();
    await h.event("close");
    expect(h.stops()).toBe(1);
  }), { numRuns: 100 });
});
