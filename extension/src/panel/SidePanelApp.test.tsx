import { panelCopy as copy } from "../i18n/spanish";
// Side Panel composition and chrome-recording-completion T1.9 (#618).
// Exercise the public panel until RecordingCompletionStatus exists: missing
// production UI must fail a visible assertion, not an unresolved import.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { isHealth, sauriHealth } from "../test-backend";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { COMPLETION_STORE, createCompletion, getCompletion, openDB, type RecordingCompletion } from "../recording-db";
import { SidePanelApp } from "./SidePanelApp";
import { chooseSource, sourceTrigger } from "./test-helpers";

function mockTabs() {
  return {
    query: vi.fn(async () => [{ id: 7, url: "https://meet.google.com/test" }] as chrome.tabs.Tab[]),
    onActivated: { addListener: vi.fn(), removeListener: vi.fn() },
    onUpdated: { addListener: vi.fn(), removeListener: vi.fn() },
  };
}

function mockChrome(_appAvailable: boolean) {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      local: { setAccessLevel: vi.fn(async () => {}), get: vi.fn(async () => ({ sauriLocalToken: "synthetic-local", recordingSettings: { countdownSeconds: 3, showControlBar: true, skipMicWarning: false } })), set: vi.fn(async () => {}), remove: vi.fn(async () => {}) },
      session: {
        get: vi.fn(async () => ({ sauriState: { status: "idle" },  })),
      },
      onChanged: { addListener: vi.fn(), removeListener: vi.fn() },
    },
    tabs: mockTabs(),
    runtime: { sendMessage: vi.fn(), openOptionsPage: vi.fn(async () => undefined) },
  };
  global.fetch = vi.fn(async (url: string) => isHealth(url) ? sauriHealth() : new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SidePanelApp", () => {
  beforeEach(() => {
    vi.stubGlobal("navigator", {
      permissions: { query: vi.fn(async () => ({ state: "granted" })) },
      mediaDevices: {
        getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
        enumerateDevices: vi.fn(async () => []),
      },
    });
  });

  it("shows the desktop-app notice without hiding recording controls when offline", async () => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    mockChrome(false);
    vi.mocked(fetch).mockRejectedValue(new TypeError("offline"));
    render(<SidePanelApp />);
    expect(await screen.findByText(copy.openLocalApp)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeInTheDocument();
    expect(screen.queryByLabelText(/password|correo/i)).not.toBeInTheDocument();
  });

  it("recovers on focus when the app opens and pairs without credentials", async () => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    vi.stubGlobal("indexedDB", new IDBFactory());
    mockChrome(false);
    vi.mocked(fetch).mockRejectedValue(new TypeError("offline"));
    render(<SidePanelApp />);
    await screen.findByText(copy.openLocalApp);
    vi.mocked(chrome.storage.local.get).mockResolvedValue({} as never);
    vi.mocked(fetch).mockImplementation(async url => String(url).endsWith("/pair")
      ? new Response(JSON.stringify({ token: "paired" }), { status: 200 })
      : isHealth(url) ? sauriHealth() : new Response("[]", { status: 200 }));
    fireEvent.focus(window);
    expect(await screen.findByText(copy.recordings)).toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/meetings/"), expect.objectContaining({ headers: { Authorization: "Bearer paired" } })));
    expect(screen.queryByText(copy.openLocalApp)).not.toBeInTheDocument();
  });

  it("explains a refused extension copy instead of a generic list error", async () => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    mockChrome(true);
    vi.mocked(chrome.storage.local.get).mockResolvedValue({} as never);
    vi.mocked(fetch).mockImplementation(async url => String(url).endsWith("/pair")
      ? new Response(JSON.stringify({ detail: "extension_not_allowed" }), { status: 403 })
      : isHealth(url) ? sauriHealth() : new Response("{}", { status: 200 }));
    render(<SidePanelApp />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.extensionNotAllowed);
    expect(screen.queryByText(copy.listError)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.openLocalApp)).not.toBeInTheDocument();
  });

  it("renders Header + Controls + List with an active session (Req. 1.4)", async () => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    mockChrome(true);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByText(copy.panelTitle)).toBeInTheDocument());
    // The recordings section renders after the stored sessions load, a step after the header.
    expect(await screen.findByText(copy.recordings)).toBeInTheDocument();
    expect(screen.getByText(copy.screenAudio)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    expect(screen.queryByText("Sauri")).not.toBeInTheDocument();
  });

  it("opens the recording settings menu from the toolbar button only, without leaving the panel", async () => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    mockChrome(true);
    render(<SidePanelApp />);
    // Wait until the stored sessions have loaded, as a person would, before using the toolbar.
    await screen.findByText(copy.recordings);
    const settings = screen.getByRole("button", { name: copy.settings });
    expect(screen.getAllByRole("button", { name: copy.settings })).toHaveLength(1);
    fireEvent.click(settings);
    expect(await screen.findByRole("dialog", { name: copy.settings })).toBeInTheDocument();
    expect(screen.getByLabelText(copy.countdown)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeInTheDocument();
  });
});

describe("native sharing picker feedback", () => {
  beforeEach(() => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    vi.stubGlobal("navigator", {
      permissions: { query: vi.fn(async () => ({ state: "granted" })) }, mediaDevices: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
      enumerateDevices: vi.fn(async () => []),
    } });
    mockChrome(true);
  });

  it("shows selection without a recording timer, disables the start controls, and cancels silently", async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(chrome.runtime.sendMessage).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<SidePanelApp />);
    const record = await screen.findByRole("button", { name: copy.newRecording });
    fireEvent.click(record);
    expect(await screen.findByText(copy.choosing)).toBeInTheDocument();
    expect(record).toBeDisabled();
    expect(sourceTrigger()).toBeDisabled();
    expect(screen.getByRole("switch", { name: copy.microphone })).toBeDisabled();
    fireEvent.click(record);
    expect(chrome.runtime.sendMessage).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("00:00")).not.toBeInTheDocument();
    await act(async () => finish({ ok: false, reason: "cancelled" }));
    expect(record).toBeEnabled();
    expect(sourceTrigger()).toBeEnabled();
    expect(screen.queryByText(copy.choosing)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => !String(url).endsWith("/health"))).toHaveLength(1); // Cancel is not a completed recording.
  });

  it("explains missing tab audio and permits choosing again", async () => {
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, reason: "no-tab-audio" });
    render(<SidePanelApp />);
    fireEvent.click(await screen.findByRole("button", { name: copy.newRecording }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.audioError);
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled();
    expect(screen.getByRole("switch", { name: copy.microphone })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("button", { name: copy.newRecording }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledTimes(2));
  });

  it("starts the timer only on the recording projection and removes picker feedback", async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(chrome.runtime.sendMessage).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<SidePanelApp />);
    fireEvent.click(await screen.findByRole("button", { name: copy.newRecording }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledOnce());
    await act(async () => {
      vi.mocked(chrome.storage.onChanged.addListener).mock.calls.forEach(([listener]) => listener({ sauriState: { newValue: { status: "recording", sessionId: "selected" } } }, "session"));
      finish({ ok: true, sessionId: "selected" });
    });
    expect(await screen.findByRole("button", { name: copy.stop })).toBeEnabled();
    expect(screen.getByText("00:00")).toBeInTheDocument();
    expect(screen.queryByText(copy.choosing)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("recovers an open picker when the panel is reopened", async () => {
    vi.mocked(chrome.storage.session.get).mockImplementation(async () => ({ sauriState: { status: "pending" }, sauriCaptureRequest: { state: { sessionId: "selection" } }, sauriSessionToken: "token-x" }));
    render(<SidePanelApp />);
    expect(await screen.findByText(copy.choosing)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeDisabled();
    await act(async () => vi.mocked(chrome.storage.onChanged.addListener).mock.calls.forEach(([listener]) => listener({ sauriCaptureRequest: { oldValue: {} } }, "session")));
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("current-tab shortcut and microphone permission", () => {
  beforeEach(() => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    vi.stubGlobal("navigator", {
      permissions: { query: vi.fn(async () => ({ state: "granted" })) },
      mediaDevices: {
        getUserMedia: vi.fn(),
        enumerateDevices: vi.fn(async () => [{ kind: "audioinput", deviceId: "mic-1", label: "Test microphone" }]),
      },
    });
    mockChrome(true);
  });

  async function clickStart(source: "picker" | "current-tab") {
    if (source === "current-tab") await chooseSource(copy.currentTab);
    const button = await screen.findByRole("button", { name: copy.newRecording });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
  }

  it("starts the picker with the selected mode and the current tab with video", async () => {
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: true });
    render(<SidePanelApp />);
    await chooseSource(copy.audioOnly);
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "set-capture-mode", captureMode: "audio_only" }));
    await waitFor(() => expect(sourceTrigger()).toHaveTextContent(copy.audioOnly));
    await clickStart("picker");
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "start-capture", source: "picker" })));
    await chooseSource(copy.currentTab);
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "set-capture-mode", captureMode: "screen_audio" }));
    await waitFor(() => expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: copy.newRecording }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenLastCalledWith(expect.objectContaining({ type: "start-capture", source: "current-tab" })));
  });

  it("chooses the input device and sends it when recording starts", async () => {
    vi.mocked(navigator.mediaDevices.enumerateDevices).mockResolvedValue([
      { kind: "audioinput", deviceId: "mic-1", label: "Test microphone" }, { kind: "audioinput", deviceId: "mic-2", label: "USB" },
    ] as MediaDeviceInfo[]);
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, reason: "cancelled" });
    render(<SidePanelApp />);
    const device = await screen.findByRole("button", { name: copy.microphoneSelector });
    await waitFor(() => expect(device).toBeEnabled());
    fireEvent.click(device);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "USB" }));
    await clickStart("picker");
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ source: "picker", micDeviceId: "mic-2" })));
  });

  it("disables the device control and starts without a microphone when the switch is off", async () => {
    mockChrome(true);
    vi.mocked(chrome.storage.local.get).mockResolvedValue({ sauriLocalToken: "synthetic-local", recordingSettings: { countdownSeconds: 3, showControlBar: true, skipMicWarning: true } } as never);
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, reason: "cancelled" });
    render(<SidePanelApp />);
    fireEvent.click(await screen.findByRole("switch", { name: copy.microphone }));
    expect(screen.getByRole("switch", { name: copy.microphone })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("button", { name: copy.microphoneSelector })).toBeDisabled();
    await clickStart("picker");
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ source: "picker", micDeviceId: null })));
  });

  it("uses a separate starting state for the shortcut and explains capture permission errors", async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(chrome.runtime.sendMessage).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<SidePanelApp />);
    await clickStart("current-tab");
    expect(await screen.findByText(copy.starting)).toBeInTheDocument();
    expect(screen.queryByText(copy.choosing)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeDisabled();
    expect(sourceTrigger()).toBeDisabled();
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "start-capture", source: "current-tab", resolution: { width: 1280, height: 720 }, micDeviceId: "mic-1" }));
    await act(async () => finish({ ok: false, reason: "current-tab-unavailable" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.tabError);
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled();
    expect(sourceTrigger()).toHaveTextContent(copy.currentTab);
    expect(screen.getByRole("switch", { name: copy.microphone })).toHaveAttribute("aria-checked", "true");
  });

  it("disables the current-tab option on restricted pages and refreshes on tab changes without disabling the picker", async () => {
    vi.mocked(chrome.tabs.query).mockImplementation(async () => [{ id: 7, url: "chrome://settings" }] as chrome.tabs.Tab[]);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled());
    fireEvent.click(sourceTrigger());
    const item = await screen.findByRole("menuitemradio", { name: copy.currentTab });
    expect(item).toBeDisabled();
    fireEvent.click(item);
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    vi.mocked(chrome.tabs.query).mockImplementation(async () => [{ id: 8, url: "https://example.com" }] as chrome.tabs.Tab[]);
    const listener = vi.mocked(chrome.tabs.onActivated.addListener).mock.calls[0][0];
    await act(async () => listener({ tabId: 8, windowId: 1 }));
    await waitFor(() => expect(screen.getByRole("menuitemradio", { name: copy.currentTab })).toBeEnabled());
  });

  it("blocks the primary button with an explanation when the selected tab becomes unavailable", async () => {
    render(<SidePanelApp />);
    await chooseSource(copy.currentTab);
    vi.mocked(chrome.tabs.query).mockImplementation(async () => [{ id: 9, url: "chrome://settings" }] as chrome.tabs.Tab[]);
    const listener = vi.mocked(chrome.tabs.onActivated.addListener).mock.calls[0][0];
    await act(async () => listener({ tabId: 9, windowId: 1 }));
    await waitFor(() => expect(screen.getByRole("button", { name: copy.newRecording })).toBeDisabled());
    expect(screen.getByRole("note")).toHaveTextContent(copy.tabUnavailable);
    await chooseSource(copy.screenAudio);
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it.each([
    ["picker", "prompt"], ["picker", "denied"],
    ["current-tab", "prompt"], ["current-tab", "denied"],
  ] as const)("%s with %s microphone permission opens options without starting, then permits retry", async (source, state) => {
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state } as PermissionStatus);
    render(<SidePanelApp />);
    await clickStart(source);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.permissionNeeded);
    expect(navigator.permissions.query).toHaveBeenCalledWith({ name: "microphone" });
    expect(chrome.runtime.openOptionsPage).toHaveBeenCalledTimes(1);
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled(); // No panel permission prompt.
    expect(screen.getByRole("switch", { name: copy.microphone })).toHaveAttribute("aria-checked", "true");
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "granted" } as PermissionStatus);
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: true, sessionId: "retried" });
    await clickStart(source);
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ type: "start-capture", source, micDeviceId: "mic-1" })));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it.each(["picker", "current-tab"] as const)("%s handles microphone NotAllowedError reported by the offscreen", async source => {
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, reason: "microphone-permission" });
    render(<SidePanelApp />);
    await clickStart(source);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.permissionNeeded);
    expect(chrome.runtime.openOptionsPage).toHaveBeenCalledOnce();
    expect(screen.getByRole("switch", { name: copy.microphone })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: copy.newRecording })).toBeEnabled();
  });

  it("checks permission for the default microphone even without enumerated devices", async () => {
    vi.mocked(navigator.mediaDevices.enumerateDevices).mockResolvedValue([]);
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, reason: "cancelled" });
    render(<SidePanelApp />);
    await clickStart("picker");
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ source: "picker", micDeviceId: "default" })));
    expect(navigator.permissions.query).toHaveBeenCalledWith({ name: "microphone" });
    expect(chrome.runtime.openOptionsPage).not.toHaveBeenCalled();
  });

  it("keeps an unlabeled microphone configured before permission instead of silently dropping it", async () => {
    vi.mocked(navigator.mediaDevices.enumerateDevices).mockResolvedValue([{ kind: "audioinput", deviceId: "", label: "" } as MediaDeviceInfo]);
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "prompt" } as PermissionStatus);
    render(<SidePanelApp />);
    await clickStart("picker");
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.permissionNeeded);
    expect(chrome.runtime.openOptionsPage).toHaveBeenCalledOnce();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });
});

// Real IndexedDB records; only browser APIs/network are synthetic. No worker
// is imported, and no successful queue result or UI component is mocked.
describe("T1.9: durable same-recording completion feedback", () => {
  // Recovered records older than seven days count as acknowledged, so use current times.
  const BASE = Date.now();
  let projection: { status: "idle"; sessionId?: string };
  let listeners: Array<(changes: Record<string, chrome.storage.StorageChange>, area: string) => void>;

  function record(status: RecordingCompletion["status"], overrides: Partial<RecordingCompletion> = {}): RecordingCompletion {
    return {
      sessionId: "session-618-current", meetingId: "meeting-618-current",
      recordingId: "recording-618-current", capturedTabId: 618, provider: "meet",
      status, updatedAt: BASE + 100, ...overrides,
    };
  }

  async function mount() {
    const view = render(<SidePanelApp />);
    await screen.findByText(copy.panelTitle);
    // Drain the initial asynchronous auth/storage/list reads before assertions.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    return view;
  }

  /** Holds back only the projection read; the session token read must still resolve. */
  function delayProjectionRead() {
    const get = vi.mocked(chrome.storage.session.get) as unknown as ReturnType<typeof vi.fn>;
    const original = get.getMockImplementation()!;
    let release!: (value: { sauriState: typeof projection }) => void;
    let delayed = false;
    get.mockImplementation((keys: unknown) => {
      if (Array.isArray(keys) && !delayed) {
        delayed = true;
        return new Promise(resolve => { release = resolve; });
      }
      return original(keys);
    });
    return (value: { sauriState: typeof projection }) => release(value);
  }

  function outcome(expected: RegExp, sessionId = "session-618-current") {
    // One accessible outcome, not a collection of stale successes/errors.
    const regions = [...screen.queryAllByRole("status"), ...screen.queryAllByRole("alert")];
    expect(regions).toHaveLength(1);
    expect(within(regions[0]).getByText(expected)).toBeInTheDocument();
    expect(regions[0].closest("[data-session-id]")).toHaveAttribute("data-session-id", sessionId);
    return regions[0];
  }

  beforeEach(() => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    vi.stubGlobal("navigator", {
      permissions: { query: vi.fn(async () => ({ state: "granted" })) }, mediaDevices: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
      enumerateDevices: vi.fn(async () => []),
    } });
    projection = { status: "idle", sessionId: "session-618-current" };
    listeners = [];
    vi.stubGlobal("chrome", {
      storage: {
      local: { setAccessLevel: vi.fn(async () => {}), get: vi.fn(async () => ({ sauriLocalToken: "synthetic-local", recordingSettings: { countdownSeconds: 3, showControlBar: true, skipMicWarning: false } })), set: vi.fn(async () => {}), remove: vi.fn(async () => {}) },
        session: { get: vi.fn(async () => ({ sauriState: projection, sauriSessionToken: "synthetic-618" })) },
        onChanged: {
          addListener: vi.fn((listener) => listeners.push(listener)),
          removeListener: vi.fn((listener) => { listeners = listeners.filter((item) => item !== listener); }),
        },
      },
      tabs: mockTabs(),
      runtime: { sendMessage: vi.fn(), openOptionsPage: vi.fn(async () => undefined) },
    });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => isHealth(url) ? sauriHealth() : new Response(JSON.stringify([]), { status: 200 })));
  });

  it("does not recover an unrelated success before the initial selected-session read resolves", async () => {
    await createCompletion(record("review_opened"));
    let resolveProjection!: (value: { sauriState: typeof projection }) => void;
    resolveProjection = delayProjectionRead();
    await mount();
    expect(screen.queryByText(new RegExp(copy.reviewOpened))).not.toBeInTheDocument();
    await act(async () => resolveProjection({ sauriState: { status: "idle", sessionId: "missing-selected" } }));
    expect(screen.queryByText(new RegExp(copy.reviewOpened))).not.toBeInTheDocument();
  });

  it("keeps the newer selected session when the initial storage snapshot arrives late", async () => {
    await createCompletion(record("review_opened"));
    await createCompletion(record("upload_failed", { sessionId: "session-new", meetingId: "meeting-new", recordingId: "recording-new" }));
    let resolveProjection!: (value: { sauriState: typeof projection }) => void;
    resolveProjection = delayProjectionRead();
    await mount();
    await act(async () => {
      listeners.forEach(listener => listener({ sauriState: { newValue: { status: "idle", sessionId: "session-new" } } }, "session"));
    });
    await waitFor(() => outcome(new RegExp(copy.uploadFailed), "session-new"));
    await act(async () => resolveProjection({ sauriState: { status: "idle", sessionId: "session-618-current" } }));
    outcome(new RegExp(copy.uploadFailed), "session-new");
    expect(screen.queryByText(new RegExp(copy.reviewOpened))).not.toBeInTheDocument();
  });

  it.each<[RecordingCompletion["status"], RegExp]>([
    ["finalizing", new RegExp(copy.saving)],
    ["upload_pending", new RegExp(copy.saving)],
    ["uploading", new RegExp(copy.saving)],
    ["upload_succeeded", new RegExp(copy.saved)],
    ["upload_failed", new RegExp(copy.uploadFailed)],
    ["upload_outcome_unavailable", new RegExp(copy.uploadUnknown)],
    ["processing", new RegExp(copy.saved)],
    ["processing_failed", new RegExp(copy.processingFailed)],
    ["processing_assets_unavailable", new RegExp(copy.processingUnavailable)],
    ["processing_succeeded", new RegExp(copy.reviewReady)],
    ["review_launch_pending", new RegExp(copy.reviewPending)],
    ["review_opened", new RegExp(copy.reviewOpened)],
  ])("renders exactly one durable outcome for %s even when capture is idle", async (status, label) => {
    await createCompletion(record(status));
    await mount();
    outcome(label);
  });

  it("retains unresolved capture feedback without implying successful upload", async () => {
    await createCompletion(record("capturing", { captureError: true, recordingId: undefined }));
    await mount();
    const region = outcome(new RegExp(copy.captureError));
    expect(region).toHaveTextContent(new RegExp(copy.captureErrorHelp));
    expect(region).not.toHaveTextContent(new RegExp(`${copy.reviewReady}|${copy.reviewOpened}`));
  });

  it("recovers the same durable failure after panel reopen without a live worker", async () => {
    await createCompletion(record("upload_failed"));
    const first = await mount();
    first.unmount();
    await mount();
    outcome(new RegExp(copy.uploadFailed));
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect((await getCompletion("session-618-current"))?.meetingId).toBe("meeting-618-current");
  });

  it("recovers durable feedback after worker projection disappears", async () => {
    await createCompletion(record("processing_assets_unavailable"));
    const first = await mount();
    first.unmount();
    projection = { status: "idle" }; // worker restart: no volatile session hint
    await mount();
    outcome(new RegExp(copy.processingUnavailable));
  });

  it("refreshes a durable change for the same session without worker messages", async () => {
    await createCompletion(record("capturing", { recordingId: undefined }));
    await mount();
    // Mutate the real durable store: IndexedDB has no chrome.storage event.
    const db = await openDB();
    await act(async () => {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(COMPLETION_STORE, "readwrite");
        tx.objectStore(COMPLETION_STORE).put(record("upload_failed", { updatedAt: BASE + 400 }));
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => { db.close(); reject(tx.error); };
      });
    });
    await waitFor(() => outcome(new RegExp(copy.uploadFailed)), { timeout: 2200 });
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });

  it("subscribes to session changes without leaking a different recording's ready state", async () => {
    await createCompletion(record("processing_succeeded"));
    await createCompletion(record("upload_failed", {
      sessionId: "session-618-next", meetingId: "meeting-618-next", recordingId: "recording-618-next",
      capturedTabId: 619, updatedAt: BASE + 200,
    }));
    await mount();
    // Switch the public panel's selected recording exactly as storage does.
    await act(async () => {
      const oldValue = projection;
      projection = { status: "idle", sessionId: "session-618-next" };
      listeners.forEach((listener) => listener({ sauriState: { oldValue, newValue: projection } }, "session"));
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    // The prior success must disappear immediately, even before the new IDB read.
    expect(screen.queryByText(/review ready/i)).not.toBeInTheDocument();
    await waitFor(() => {
      const region = outcome(new RegExp(copy.uploadFailed), "session-618-next");
      expect(region.closest("[data-session-id]")).not.toHaveAttribute("data-session-id", "session-618-current");
      expect(region).not.toHaveTextContent(new RegExp(`${copy.reviewReady}|${copy.reviewOpened}`));
    });
  });

  it.each(["upload_pending", "upload_failed", "processing", "processing_assets_unavailable"] as const)(
    "does not promote %s to ready from another recording's completed assets", async (status) => {
      await createCompletion(record(status));
      await createCompletion(record("review_opened", {
        sessionId: "session-618-foreign", meetingId: "meeting-618-foreign", recordingId: "recording-618-foreign",
        capturedTabId: 620, updatedAt: BASE + 300,
      }));
      await mount();
      // Require real feedback first so a blank panel cannot pass a negative test.
      const regions = [...screen.queryAllByRole("status"), ...screen.queryAllByRole("alert")];
      expect(regions).toHaveLength(1);
      expect(regions[0].closest("[data-session-id]")).toHaveAttribute("data-session-id", "session-618-current");
      expect(regions[0]).not.toHaveTextContent(/review.*ready|review.*opened/i);
      expect(regions[0].closest("[data-session-id]")).not.toHaveAttribute("data-session-id", "session-618-foreign");
    },
  );
});
