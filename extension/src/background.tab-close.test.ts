import { afterEach, describe, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import * as fc from "fast-check";
import { createCompletion, getCompletion, getChunksBySession, storeChunk, settleCapture } from "./recording-db";

type Provider = "meet" | "teams";
type Handle = { provider: Provider; capturedTabId: number; sessionId: string };
type TabRemovedListener = (tabId: number, info: { windowId: number; isWindowClosing: boolean }) => Promise<void>;
type MessageListener = (message: { type: string }, sender: object, reply: (result: unknown) => void) => boolean;

async function loadBackgroundWithHandles(handles: Handle[], projected?: Handle, mediaOwnerAvailable = true) {
  vi.resetModules();
  vi.stubGlobal("indexedDB", new IDBFactory());
  for (const handle of handles) {
    await createCompletion({
      ...handle, meetingId: `meeting-${handle.sessionId}`, status: "capturing", updatedAt: 1,
    });
  }
  let state: { status: string; tabId?: number; sessionId?: string; provider?: Provider; notificationEmittedAt?: string } = projected
    ? { status: "recording", tabId: projected.capturedTabId, sessionId: projected.sessionId, provider: projected.provider }
    : { status: "idle" };
  let tabRemovedListener: TabRemovedListener | undefined;
  let messageListener: MessageListener | undefined;
  const sendMessage = vi.fn(async (message: { type: string; sessionId?: string }) => {
    if (message.type === "stop-recording") {
      if (!mediaOwnerAvailable) return { ok: false };
      if (message.sessionId) await settleCapture(message.sessionId);
    }
    return { ok: true };
  });
  vi.stubGlobal("chrome", {
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    runtime: {
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: vi.fn() },
      onMessage: { addListener: (listener: MessageListener) => { messageListener = listener; } },
      getURL: (path: string) => path, getContexts: vi.fn(async () => []), sendMessage,
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
      onRemoved: { addListener: (listener: TabRemovedListener) => { tabRemovedListener = listener; } },
      query: vi.fn(async () => []), sendMessage: vi.fn(async () => undefined),
    },
  });
  await import("./background");
  expect(tabRemovedListener).toBeDefined();
  expect(messageListener).toBeDefined();
  return {
    state: () => state,
    sendMessage,
    async message(type: string, sender: object = {}, payload: { sessionId?: string; emittedAt?: string } = {}) {
      const reply = vi.fn();
      messageListener!({ type, ...payload }, sender, reply);
      await vi.waitFor(() => expect(reply).toHaveBeenCalled());
      // The real listener starts async handlers without returning their promise.
      await new Promise(resolve => setTimeout(resolve, 0));
      return reply.mock.lastCall?.[0];
    },
    async close(tabId: number) {
      await tabRemovedListener!(tabId, { windowId: 5, isWindowClosing: false });
    },
    async restartWithoutProjection() {
      state = { status: "idle" };
      vi.resetModules();
      await import("./background");
      expect(tabRemovedListener).toBeDefined();
    },
    stops() {
      return sendMessage.mock.calls.filter(([message]) => message.type === "stop-recording").map(([message]) => message.sessionId);
    },
  };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("an unsupported Teams tab without a capture handle cannot complete a Meet recording", async () => {
  const meet: Handle = { provider: "meet", capturedTabId: 41, sessionId: "meet-only-session" };
  const h = await loadBackgroundWithHandles([meet], meet);
  await h.message("teams-ended");
  await h.close(99);
  expect(h.stops()).toEqual([]);
  expect(await getCompletion(meet.sessionId)).toMatchObject({ ...meet, status: "capturing" });
});

const providers: Provider[] = ["meet", "teams"];

describe.each(providers)("%s captured-tab completion adapter", provider => {
  const active: Handle = { provider, capturedTabId: 41, sessionId: `session-${provider}` };
  const other: Handle = { provider, capturedTabId: 99, sessionId: `other-${provider}` };

  it("does not finalize or detach on meeting-ended, then closes the same durable session after restart", async () => {
    const h = await loadBackgroundWithHandles([active, other], active);
    await h.message(provider === "meet" ? "meet-ended" : "teams-ended");
    expect(h.stops()).toEqual([]);
    expect(h.state()).toMatchObject({ status: "recording", sessionId: active.sessionId, tabId: active.capturedTabId });
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "capturing" });

    await h.restartWithoutProjection();
    await h.close(876);
    expect(h.stops()).toEqual([]);
    await h.close(active.capturedTabId);
    expect(h.stops()).toEqual([active.sessionId]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "upload_pending", trigger: "captured_tab_closed" });
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
  });

  it("Stop and tab-close claim the exact same stored binding once", async () => {
    const h = await loadBackgroundWithHandles([active, other], active);
    await h.message("stop-capture");
    await vi.waitFor(() => expect(h.stops()).toEqual([active.sessionId]));
    await h.close(active.capturedTabId);
    expect(h.stops()).toEqual([active.sessionId]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, trigger: "stop" });
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
  });

  it("an unresolved active handle never finalizes the projected or another session", async () => {
    const ambiguous: Handle = { provider, capturedTabId: active.capturedTabId, sessionId: `ambiguous-${provider}` };
    const h = await loadBackgroundWithHandles([active, other, ambiguous], active);
    await storeChunk(active.sessionId, new Blob(["synthetic-media"]));
    await h.close(active.capturedTabId);
    expect(h.stops()).toEqual([]);
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
    expect(await getCompletion(ambiguous.sessionId)).toMatchObject({ ...ambiguous, status: "capturing" });
    // The unresolved adapter must leave an observable, non-successful error for the panel.
    expect(await getCompletion(active.sessionId)).toMatchObject({ captureError: true });
    expect(await getCompletion(ambiguous.sessionId)).toMatchObject({ captureError: true });
    // A retry/worker restart must not pick the other ambiguous candidate.
    await h.restartWithoutProjection();
    await h.close(active.capturedTabId);
    expect(h.stops()).toEqual([]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "capturing", captureError: true });
    expect(await getChunksBySession(active.sessionId)).toHaveLength(1);
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
  });

  it("does not stop either session when the projected tab has two durable handles", async () => {
    const ambiguous: Handle = { ...active, sessionId: `ambiguous-stop-${provider}` };
    const h = await loadBackgroundWithHandles([active, ambiguous, other], active);
    await h.message("stop-capture");
    expect(h.stops()).toEqual([]);
    for (const handle of [active, ambiguous]) {
      expect(await getCompletion(handle.sessionId)).toMatchObject({ ...handle, status: "capturing", captureError: true });
    }
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
  });

  it("never trusts a stale projected tab/provider over the durable handle", async () => {
    const wrongTab = await loadBackgroundWithHandles([active, other], { ...active, capturedTabId: 888 });
    await wrongTab.message("stop-capture");
    expect(wrongTab.stops()).toEqual([]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "capturing" });

    const wrongProvider = await loadBackgroundWithHandles([active, other], {
      ...active, provider: provider === "meet" ? "teams" : "meet",
    });
    await wrongProvider.message("stop-capture");
    expect(wrongProvider.stops()).toEqual([]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "capturing" });
  });

  it("does not accept a foreign page's media-owner completion or failure", async () => {
    const h = await loadBackgroundWithHandles([active, other], active);
    const sender = { tab: { id: other.capturedTabId } };
    expect(await h.message("recording-error", sender, { sessionId: active.sessionId })).toMatchObject({ ok: false });
    expect(await h.message("recording-stopped", sender, { sessionId: active.sessionId })).toMatchObject({ ok: false });
    await h.message("notification-emitted", sender, { emittedAt: "2026-11-12T00:00:00Z" });
    expect(h.state().notificationEmittedAt).toBeUndefined();
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "capturing" });
    expect(h.state()).toMatchObject({ status: "recording", sessionId: active.sessionId });
  });

  it("cannot be stopped by a provider page forging a panel stop message", async () => {
    const h = await loadBackgroundWithHandles([active, other], active);
    await h.message("stop-capture", { tab: { id: other.capturedTabId } });
    expect(h.stops()).toEqual([]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "capturing" });
  });

  it("does not claim success if the existing media owner rejects the exact handle", async () => {
    const h = await loadBackgroundWithHandles([active, other], active, false);
    await storeChunk(active.sessionId, new Blob(["synthetic-media"]));
    await h.message("stop-capture");
    expect(h.stops()).toEqual([active.sessionId]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "finalizing", captureError: true });
    expect(await getChunksBySession(active.sessionId)).toHaveLength(1);
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
  });

  it("retains a non-successful error if tab-close cannot stop the exact media owner after restart", async () => {
    const h = await loadBackgroundWithHandles([active, other], active, false);
    await h.restartWithoutProjection();
    await h.close(active.capturedTabId);
    expect(h.stops()).toEqual([active.sessionId]);
    expect(await getCompletion(active.sessionId)).toMatchObject({ ...active, status: "finalizing", captureError: true });
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
  });

  it("rejects a mismatched projected tab across 100 synthetic handles", async () => {
    await fc.assert(fc.asyncProperty(
      fc.uuid(), fc.integer({ min: 1, max: 1000000 }),
      async (sessionId, capturedTabId) => {
        const handle = { provider, sessionId, capturedTabId };
        const h = await loadBackgroundWithHandles([handle], { ...handle, capturedTabId: capturedTabId + 1 });
        await h.message("stop-capture");
        expect(h.stops()).toEqual([]);
        expect(await getCompletion(sessionId)).toMatchObject({ ...handle, status: "capturing" });
      },
    ), { numRuns: 100 });
  }, 30000);

  it("persists ambiguity without a projected session, including concurrent close events", async () => {
    const ambiguous: Handle = { ...active, sessionId: `unprojected-${provider}` };
    const h = await loadBackgroundWithHandles([active, ambiguous, other]);
    await Promise.all([h.close(active.capturedTabId), h.close(active.capturedTabId)]);
    expect(h.stops()).toEqual([]);
    for (const handle of [active, ambiguous]) {
      expect(await getCompletion(handle.sessionId)).toMatchObject({ ...handle, captureError: true, status: "capturing" });
    }
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
  });
});
