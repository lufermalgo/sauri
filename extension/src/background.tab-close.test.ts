import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type TabRemovedListener = (tabId: number, removeInfo: { windowId: number; isWindowClosing: boolean }) => void;

async function loadBackgroundWithRecording(tabId: number) {
  vi.resetModules();
  let tabRemovedListener: TabRemovedListener | undefined;
  const sendMessage = vi.fn();

  vi.stubGlobal("chrome", {
    action: {
      onClicked: { addListener: vi.fn() },
      setBadgeText: vi.fn(),
      setBadgeBackgroundColor: vi.fn(),
    },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
    runtime: {
      onInstalled: { addListener: vi.fn() },
      onMessage: { addListener: vi.fn() },
      onStartup: { addListener: vi.fn() },
      getURL: vi.fn((path: string) => path),
      getContexts: vi.fn(async () => []),
      sendMessage,
    },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    storage: {
      session: {
        get: vi.fn(async () => ({ sauriState: { status: "recording", tabId, sessionId: "session-active" } })),
        set: vi.fn(async () => undefined),
      },
      sync: { get: vi.fn(async () => ({})) },
    },
    tabs: {
      onRemoved: {
        addListener: (listener: TabRemovedListener) => {
          tabRemovedListener = listener;
        },
      },
      query: vi.fn(async () => []),
      sendMessage: vi.fn(async () => undefined),
    },
  });

  await import("./background");
  return { tabRemovedListener, sendMessage };
}

describe("Meet tab close capture lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stops the active recording when its captured tab closes", async () => {
    const { tabRemovedListener, sendMessage } = await loadBackgroundWithRecording(41);

    expect(tabRemovedListener).toBeDefined();
    await tabRemovedListener!(41, { windowId: 5, isWindowClosing: false });

    expect(sendMessage).toHaveBeenCalledWith({ type: "stop-recording" });
  });

  it("does not stop capture when an unrelated tab closes", async () => {
    const { tabRemovedListener, sendMessage } = await loadBackgroundWithRecording(41);

    expect(tabRemovedListener).toBeDefined();
    await tabRemovedListener!(99, { windowId: 5, isWindowClosing: false });

    expect(sendMessage).not.toHaveBeenCalledWith({ type: "stop-recording" });
  });
});
