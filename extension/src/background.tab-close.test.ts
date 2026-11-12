import { afterEach, describe, expect, it, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import { createCompletion, getCompletion, settleCapture } from "./recording-db";

type Provider = "meet" | "teams";
type Handle = { provider: Provider; capturedTabId: number; sessionId: string };
type TabRemovedListener = (tabId: number, info: { windowId: number; isWindowClosing: boolean }) => Promise<void>;
type MessageListener = (message: { type: string }, sender: object, reply: (result: unknown) => void) => boolean;

async function loadBackgroundWithHandles(handles: Handle[], projected?: Handle) {
  vi.resetModules();
  vi.stubGlobal("indexedDB", new IDBFactory());
  for (const handle of handles) {
    await createCompletion({
      ...handle, meetingId: `meeting-${handle.sessionId}`, status: "capturing", updatedAt: 1,
    });
  }
  let state: { status: string; tabId?: number; sessionId?: string } = projected
    ? { status: "recording", tabId: projected.capturedTabId, sessionId: projected.sessionId }
    : { status: "idle" };
  let tabRemovedListener: TabRemovedListener | undefined;
  let messageListener: MessageListener | undefined;
  const sendMessage = vi.fn(async (message: { type: string; sessionId?: string }) => {
    if (message.type === "stop-recording" && message.sessionId) await settleCapture(message.sessionId);
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
    async message(type: string) {
      const reply = vi.fn();
      messageListener!({ type }, {}, reply);
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
    await h.close(active.capturedTabId);
    expect(h.stops()).toEqual([]);
    expect(await getCompletion(other.sessionId)).toMatchObject({ ...other, status: "capturing" });
    expect(await getCompletion(ambiguous.sessionId)).toMatchObject({ ...ambiguous, status: "capturing" });
    // The unresolved adapter must leave an observable, non-successful error for the panel.
    expect(await getCompletion(active.sessionId)).toMatchObject({ captureError: true });
  });
});
