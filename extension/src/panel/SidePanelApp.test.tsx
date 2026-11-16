// Side Panel composition and chrome-recording-completion T1.9 (#618).
// Exercise the public panel until RecordingCompletionStatus exists: missing
// production UI must fail a visible assertion, not an unresolved import.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { COMPLETION_STORE, createCompletion, getCompletion, openDB, type RecordingCompletion } from "../recording-db";
import { SidePanelApp } from "./SidePanelApp";

function mockTabs() {
  return {
    query: vi.fn(async () => [{ id: 7, url: "https://meet.google.com/test" }] as chrome.tabs.Tab[]),
    onActivated: { addListener: vi.fn(), removeListener: vi.fn() },
    onUpdated: { addListener: vi.fn(), removeListener: vi.fn() },
  };
}

function mockChrome(sessionActive: boolean) {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      session: {
        get: vi.fn(async () => ({ sauriState: { status: "idle" } })),
      },
      sync: {
        get: vi.fn(async () => (sessionActive ? { authToken: "token-x" } : {})),
        set: vi.fn(async () => {}),
        remove: vi.fn(async () => {}),
      },
      onChanged: { addListener: vi.fn(), removeListener: vi.fn() },
    },
    tabs: mockTabs(),
    runtime: { sendMessage: vi.fn(), openOptionsPage: vi.fn(async () => undefined) },
  };
  global.fetch = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })) as unknown as typeof fetch;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SidePanelApp", () => {
  beforeEach(() => {
    vi.stubGlobal("navigator", {
      mediaDevices: {
        getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
        enumerateDevices: vi.fn(async () => []),
      },
    });
  });

  it("blocks the Notes_List without an active User_Session (Req. 13.2)", async () => {
    mockChrome(false);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument());
    expect(screen.queryByText("My Notes")).not.toBeInTheDocument();
  });

  it("renders Header + Controls + List with an active session (Req. 1.4)", async () => {
    mockChrome(true);
    render(<SidePanelApp />);
    await waitFor(() => expect(screen.getByText("REC Notes")).toBeInTheDocument());
    expect(screen.getByText("My Notes")).toBeInTheDocument();
    expect(screen.getByText("Screen + audio")).toBeInTheDocument();
  });
});

describe("native sharing picker feedback", () => {
  beforeEach(() => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    vi.stubGlobal("navigator", { mediaDevices: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
      enumerateDevices: vi.fn(async () => []),
    } });
    mockChrome(true);
  });

  it("shows selection without a recording timer, disables both start buttons, and cancels silently", async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(chrome.runtime.sendMessage).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<SidePanelApp />);
    const record = await screen.findByRole("switch", { name: "Record" });
    fireEvent.click(record);
    expect(await screen.findByText("Choose the tab to record...")).toBeInTheDocument();
    expect(record).toBeDisabled();
    expect(record).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("button", { name: /New Note/ })).toBeDisabled();
    fireEvent.click(record);
    expect(chrome.runtime.sendMessage).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("00:00")).not.toBeInTheDocument();
    await act(async () => finish({ ok: false, reason: "cancelled" }));
    expect(record).toBeEnabled();
    expect(screen.getByRole("button", { name: /New Note/ })).toBeEnabled();
    expect(screen.queryByText("Choose the tab to record...")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(1); // Cancel is not a completed recording.
  });

  it("explains missing tab audio and permits choosing again", async () => {
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, reason: "no-tab-audio" });
    render(<SidePanelApp />);
    fireEvent.click(await screen.findByRole("switch", { name: "Record" }));
    expect(await screen.findByRole("alert")).toHaveTextContent('Choose the tab again and leave "Share tab audio" checked.');
    expect(screen.getByRole("switch")).toBeEnabled();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledTimes(2));
  });

  it("starts the timer only on the recording projection and removes picker feedback", async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(chrome.runtime.sendMessage).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<SidePanelApp />);
    fireEvent.click(await screen.findByRole("switch", { name: "Record" }));
    const listener = vi.mocked(chrome.storage.onChanged.addListener).mock.calls[0][0];
    await act(async () => {
      listener({ sauriState: { newValue: { status: "recording", sessionId: "selected" } } }, "session");
      finish({ ok: true, sessionId: "selected" });
    });
    expect(await screen.findByRole("switch", { name: "Stop" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("00:00")).toBeInTheDocument();
    expect(screen.queryByText("Choose the tab to record...")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("recovers an open picker when the panel is reopened", async () => {
    vi.mocked(chrome.storage.session.get).mockImplementation(async () => ({ sauriState: { status: "pending" }, sauriCaptureRequest: { state: { sessionId: "selection" } } }));
    render(<SidePanelApp />);
    expect(await screen.findByText("Choose the tab to record...")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Record" })).toBeDisabled();
    const listener = vi.mocked(chrome.storage.onChanged.addListener).mock.calls[0][0];
    await act(async () => listener({ sauriCaptureRequest: { oldValue: {} } }, "session"));
    expect(screen.getByRole("switch", { name: "Record" })).toBeEnabled();
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
    const button = source === "picker"
      ? await screen.findByRole("switch", { name: "Record" })
      : await screen.findByRole("button", { name: "Record this tab" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
  }

  it("uses a separate starting state for the shortcut and explains capture permission errors", async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(chrome.runtime.sendMessage).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<SidePanelApp />);
    await clickStart("current-tab");
    expect(await screen.findByText("Starting recording...")).toBeInTheDocument();
    expect(screen.queryByText("Choose the tab to record...")).not.toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Record this tab" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /New Note/ })).toBeDisabled();
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "start-capture", source: "current-tab", resolution: { width: 1280, height: 720 }, micDeviceId: "mic-1" }));
    await act(async () => finish({ ok: false, reason: "current-tab-unavailable" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Open sauri from its toolbar icon on a web tab and try again.");
    expect(screen.getByRole("button", { name: "Record this tab" })).toBeEnabled();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("disables the shortcut on restricted pages and refreshes on tab changes without disabling the picker", async () => {
    vi.mocked(chrome.tabs.query).mockImplementation(async () => [{ id: 7, url: "chrome://settings" }] as chrome.tabs.Tab[]);
    render(<SidePanelApp />);
    expect(await screen.findByRole("button", { name: "Record this tab" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("switch", { name: "Record" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Record this tab" }));
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    vi.mocked(chrome.tabs.query).mockImplementation(async () => [{ id: 8, url: "https://example.com" }] as chrome.tabs.Tab[]);
    const listener = vi.mocked(chrome.tabs.onActivated.addListener).mock.calls[0][0];
    await act(async () => listener({ tabId: 8, windowId: 1 }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Record this tab" })).toBeEnabled());
  });

  it.each([
    ["picker", "prompt"], ["picker", "denied"],
    ["current-tab", "prompt"], ["current-tab", "denied"],
  ] as const)("%s with %s microphone permission opens options without starting, then permits retry", async (source, state) => {
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state } as PermissionStatus);
    render(<SidePanelApp />);
    await clickStart(source);
    expect(await screen.findByRole("alert")).toHaveTextContent("Allow the microphone in the tab that opened, then click Record again.");
    expect(navigator.permissions.query).toHaveBeenCalledWith({ name: "microphone" });
    expect(chrome.runtime.openOptionsPage).toHaveBeenCalledTimes(1);
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled(); // No panel permission prompt.
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
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
    expect(await screen.findByRole("alert")).toHaveTextContent("Allow the microphone in the tab that opened, then click Record again.");
    expect(chrome.runtime.openOptionsPage).toHaveBeenCalledOnce();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("button", { name: "Record this tab" })).toBeEnabled();
  });

  it("does not request microphone permission for an unconfigured microphone", async () => {
    vi.mocked(navigator.mediaDevices.enumerateDevices).mockResolvedValue([]);
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, reason: "cancelled" });
    render(<SidePanelApp />);
    await clickStart("picker");
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({ source: "picker", micDeviceId: null })));
    expect(navigator.permissions.query).not.toHaveBeenCalled();
    expect(chrome.runtime.openOptionsPage).not.toHaveBeenCalled();
  });

  it("keeps an unlabeled microphone configured before permission instead of silently dropping it", async () => {
    vi.mocked(navigator.mediaDevices.enumerateDevices).mockResolvedValue([{ kind: "audioinput", deviceId: "", label: "" } as MediaDeviceInfo]);
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: "prompt" } as PermissionStatus);
    render(<SidePanelApp />);
    await clickStart("picker");
    expect(await screen.findByRole("alert")).toHaveTextContent("Allow the microphone");
    expect(chrome.runtime.openOptionsPage).toHaveBeenCalledOnce();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });
});

// Real IndexedDB records; only browser APIs/network are synthetic. No worker
// is imported, and no successful queue result or UI component is mocked.
describe("T1.9: durable same-recording completion feedback", () => {
  let projection: { status: "idle"; sessionId?: string };
  let listeners: Array<(changes: Record<string, chrome.storage.StorageChange>, area: string) => void>;

  function record(status: RecordingCompletion["status"], overrides: Partial<RecordingCompletion> = {}): RecordingCompletion {
    return {
      sessionId: "session-618-current", meetingId: "meeting-618-current",
      recordingId: "recording-618-current", capturedTabId: 618, provider: "meet",
      status, updatedAt: 100, ...overrides,
    };
  }

  async function mount() {
    const view = render(<SidePanelApp />);
    await screen.findByText("My Notes");
    // Drain the initial asynchronous auth/storage/list reads before assertions.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    return view;
  }

  function outcome(expected: RegExp, sessionId = "session-618-current") {
    // One accessible outcome, not a collection of stale successes/errors.
    const regions = [...screen.queryAllByRole("status"), ...screen.queryAllByRole("alert")];
    expect(regions).toHaveLength(1);
    expect(within(regions[0]).getByText(expected)).toBeInTheDocument();
    expect(regions[0]).toHaveTextContent(sessionId);
    return regions[0];
  }

  beforeEach(() => {
    vi.stubGlobal("indexedDB", new IDBFactory());
    vi.stubGlobal("navigator", { mediaDevices: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
      enumerateDevices: vi.fn(async () => []),
    } });
    projection = { status: "idle", sessionId: "session-618-current" };
    listeners = [];
    vi.stubGlobal("chrome", {
      storage: {
        session: { get: vi.fn(async () => ({ sauriState: projection })) },
        sync: { get: vi.fn(async () => ({ authToken: "synthetic-618" })) },
        onChanged: {
          addListener: vi.fn((listener) => listeners.push(listener)),
          removeListener: vi.fn((listener) => { listeners = listeners.filter((item) => item !== listener); }),
        },
      },
      tabs: mockTabs(),
      runtime: { sendMessage: vi.fn(), openOptionsPage: vi.fn(async () => undefined) },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })));
  });

  it("does not recover an unrelated success before the initial selected-session read resolves", async () => {
    await createCompletion(record("review_opened"));
    let resolveProjection!: (value: { sauriState: typeof projection }) => void;
    vi.mocked(chrome.storage.session.get).mockImplementationOnce(() => new Promise(resolve => { resolveProjection = resolve; }));
    await mount();
    expect(screen.queryByText(/review opened/i)).not.toBeInTheDocument();
    await act(async () => resolveProjection({ sauriState: { status: "idle", sessionId: "missing-selected" } }));
    expect(screen.queryByText(/review opened/i)).not.toBeInTheDocument();
  });

  it("keeps the newer selected session when the initial storage snapshot arrives late", async () => {
    await createCompletion(record("review_opened"));
    await createCompletion(record("upload_failed", { sessionId: "session-new", meetingId: "meeting-new", recordingId: "recording-new" }));
    let resolveProjection!: (value: { sauriState: typeof projection }) => void;
    vi.mocked(chrome.storage.session.get).mockImplementationOnce(() => new Promise(resolve => { resolveProjection = resolve; }));
    await mount();
    await act(async () => {
      listeners.forEach(listener => listener({ sauriState: { newValue: { status: "idle", sessionId: "session-new" } } }, "session"));
    });
    await waitFor(() => outcome(/upload failed/i, "session-new"));
    await act(async () => resolveProjection({ sauriState: { status: "idle", sessionId: "session-618-current" } }));
    outcome(/upload failed/i, "session-new");
    expect(screen.queryByText(/review opened/i)).not.toBeInTheDocument();
  });

  it.each<[RecordingCompletion["status"], RegExp]>([
    ["finalizing", /finaliz/i],
    ["upload_pending", /upload.*(pending|wait|progress)|waiting.*upload/i],
    ["uploading", /upload.*progress|uploading/i],
    ["upload_succeeded", /upload.*(succeed|complete|success)/i],
    ["upload_failed", /upload.*(fail|could not)/i],
    ["upload_outcome_unavailable", /upload.*(unavailable|not confirmed|unknown)/i],
    ["processing", /processing.*progress|processing recording/i],
    ["processing_failed", /processing.*(fail|could not)/i],
    ["processing_assets_unavailable", /processing.*unavailable|status.*unavailable/i],
    ["processing_succeeded", /review.*ready/i],
    ["review_launch_pending", /review.*(opening|pending)|opening.*review/i],
    ["review_opened", /review.*opened/i],
  ])("renders exactly one durable outcome for %s even when capture is idle", async (status, label) => {
    await createCompletion(record(status));
    await mount();
    outcome(label);
  });

  it("retains unresolved capture feedback without implying successful upload", async () => {
    await createCompletion(record("capturing", { captureError: true, recordingId: undefined }));
    await mount();
    const region = outcome(/recording could not be finalized/i);
    expect(region).toHaveTextContent(/saving has not been confirmed/i);
    expect(region).not.toHaveTextContent(/review ready|review opened/i);
  });

  it("recovers the same durable failure after panel reopen without a live worker", async () => {
    await createCompletion(record("upload_failed"));
    const first = await mount();
    first.unmount();
    await mount();
    outcome(/upload.*(fail|could not)/i);
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect((await getCompletion("session-618-current"))?.meetingId).toBe("meeting-618-current");
  });

  it("recovers durable feedback after worker projection disappears", async () => {
    await createCompletion(record("processing_assets_unavailable"));
    const first = await mount();
    first.unmount();
    projection = { status: "idle" }; // worker restart: no volatile session hint
    await mount();
    outcome(/processing.*unavailable|status.*unavailable/i);
  });

  it("refreshes a durable change for the same session without worker messages", async () => {
    await createCompletion(record("capturing", { recordingId: undefined }));
    await mount();
    // Mutate the real durable store: IndexedDB has no chrome.storage event.
    const db = await openDB();
    await act(async () => {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(COMPLETION_STORE, "readwrite");
        tx.objectStore(COMPLETION_STORE).put(record("upload_failed", { updatedAt: 400 }));
        tx.oncomplete = () => { db.close(); resolve(); };
        tx.onerror = () => { db.close(); reject(tx.error); };
      });
    });
    await waitFor(() => outcome(/upload.*(fail|could not)/i), { timeout: 2200 });
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });

  it("subscribes to session changes without leaking a different recording's ready state", async () => {
    await createCompletion(record("processing_succeeded"));
    await createCompletion(record("upload_failed", {
      sessionId: "session-618-next", meetingId: "meeting-618-next", recordingId: "recording-618-next",
      capturedTabId: 619, updatedAt: 200,
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
      const region = outcome(/upload.*(fail|could not)/i, "session-618-next");
      expect(region).not.toHaveTextContent("session-618-current");
      expect(region).not.toHaveTextContent(/review ready|review opened/i);
    });
  });

  it.each(["upload_pending", "upload_failed", "processing", "processing_assets_unavailable"] as const)(
    "does not promote %s to ready from another recording's completed assets", async (status) => {
      await createCompletion(record(status));
      await createCompletion(record("review_opened", {
        sessionId: "session-618-foreign", meetingId: "meeting-618-foreign", recordingId: "recording-618-foreign",
        capturedTabId: 620, updatedAt: 300,
      }));
      await mount();
      // Require real feedback first so a blank panel cannot pass a negative test.
      const regions = [...screen.queryAllByRole("status"), ...screen.queryAllByRole("alert")];
      expect(regions).toHaveLength(1);
      expect(regions[0]).toHaveTextContent("session-618-current");
      expect(regions[0]).not.toHaveTextContent(/review.*ready|review.*opened|session-618-foreign/i);
    },
  );
});
