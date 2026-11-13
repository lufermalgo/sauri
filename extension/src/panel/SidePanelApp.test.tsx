// Side Panel composition and chrome-recording-completion T1.9 (#618).
// Exercise the public panel until RecordingCompletionStatus exists: missing
// production UI must fail a visible assertion, not an unresolved import.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { COMPLETION_STORE, createCompletion, getCompletion, openDB, type RecordingCompletion } from "../recording-db";
import { SidePanelApp } from "./SidePanelApp";

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
    runtime: { sendMessage: vi.fn() },
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
      runtime: { sendMessage: vi.fn() },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })));
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
    const region = outcome(/upload.*(fail|could not)/i, "session-618-next");
    expect(region).not.toHaveTextContent("session-618-current");
    expect(region).not.toHaveTextContent(/review ready|review opened/i);
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
