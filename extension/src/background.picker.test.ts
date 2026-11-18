import { readFileSync } from "node:fs";
import { Blob as NativeBlob } from "node:buffer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";
import { cancelCountdown, hideRecordingUI, showCountdown, syncRecordingUI } from "./overlay/recording";
import { COMPLETION_STORE, getCompletion, getChunksBySession, openDB } from "./recording-db";

// Real muxed test media; browser APIs are synthetic, persistence/upload code is not.
const media = new NativeBlob([readFileSync("src/fixtures/synthetic-av.webm")], { type: "video/webm" });
type Message = { type: string; sessionId?: string; [key: string]: unknown };
type Listener = (message: Message, sender: chrome.runtime.MessageSender, reply: (value: any) => void) => boolean | void;

class Track extends EventTarget {
  readyState = "live";
  stop = vi.fn(() => { this.readyState = "ended"; });
  constructor(public kind: string) { super(); }
  getSettings() { return { displaySurface: "browser" }; }
}
class Stream {
  constructor(private tracks: Track[]) {}
  getTracks() { return this.tracks; }
  getAudioTracks() { return this.tracks.filter(track => track.kind === "audio"); }
  getVideoTracks() { return this.tracks.filter(track => track.kind === "video"); }
}
class AudioContextMock {
  destination = {};
  createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
  createMediaStreamDestination = vi.fn(() => ({ stream: new Stream([new Track("audio")]) }));
  close = vi.fn();
}
class Recorder {
  static last: Recorder;
  static isTypeSupported() { return true; }
  state = "inactive";
  ondataavailable?: (event: { data: NativeBlob }) => void;
  onstop?: () => Promise<void>;
  onerror?: () => void;
  constructor(public stream: Stream, public options: { mimeType: string }) { Recorder.last = this; }
  start = vi.fn(() => { this.state = "recording"; });
  pause = vi.fn(() => { this.state = "paused"; });
  resume = vi.fn(() => { this.state = "recording"; });
  stop = vi.fn(() => {
    this.state = "inactive";
    this.ondataavailable?.({ data: media });
    void this.onstop?.();
  });
}

async function completions() {
  const db = await openDB();
  return new Promise<unknown[]>((resolve, reject) => {
    const tx = db.transaction(COMPLETION_STORE, "readonly");
    const request = tx.objectStore(COMPLETION_STORE).getAll();
    tx.oncomplete = () => { db.close(); resolve(request.result); };
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}

async function setup({ url = "https://meet.google.com/test-picker", existing = false, recording = false, liveOffscreen = false, captureMode = "screen_audio", countdownSeconds = 0, showControlBar = true, realUI = false, title = "Example page", injectable = true, appAvailable = true } = {}) {
  vi.resetModules();
  Recorder.last = undefined as unknown as Recorder;
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("IDBKeyRange", IDBKeyRange);
  vi.stubGlobal("Blob", NativeBlob);
  vi.stubGlobal("FormData", class {
    private values = new Map<string, unknown>();
    append(key: string, value: unknown) { this.values.set(key, value); }
    get(key: string) { return this.values.get(key); }
  });
  const original = { status: recording ? "recording" : "pending", meetingTitle: "Prior title", meetingUrl: "https://meet.google.com/previous", captureMode };
  const stored: Record<string, any> = { sauriState: original };
  let alarm!: (value: { name: string }) => void;
  const video = new Track("video");
  const audio = new Track("audio");
  const stream = new Stream([audio, video]);
  const display = vi.fn(async () => stream);
  let locked = false;
  const userMedia = vi.fn(async (_constraints: MediaStreamConstraints) => stream);
  vi.stubGlobal("navigator", {
    permissions: { query: vi.fn(async () => ({ state: "granted" })) },
    mediaDevices: { getDisplayMedia: display, getUserMedia: userMedia },
    locks: { request: vi.fn(async (_name, _options, callback) => {
      if (typeof _options === "function") return _options({ name: _name });
      if (locked) return callback(null);
      locked = true;
      try { return await callback({ name: "sauri-capture-start" }); }
      finally { locked = false; }
    }) },
  });
  vi.stubGlobal("MediaStream", Stream);
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal("AudioContext", AudioContextMock);
  const listeners: Listener[] = [];
  let removed!: (tabId: number) => Promise<void>;
  let updated!: (tabId: number, change: { status?: string }, tab: { url?: string }) => Promise<void>;
  const executeScript = vi.fn(async (_injection: unknown) => { if (!injectable) throw new Error("Cannot access contents of the page"); return []; });
  function dispatch(listener: Listener, message: Message, sender = {}) {
    return new Promise<any>(resolve => {
      const pending = listener(message, sender, resolve);
      if (!pending) resolve(undefined);
    });
  }
  const send = vi.fn(async (message: Message) => {
    const toOffscreen = ["start-recording", "stop-recording", "pause-recording", "resume-recording", "cancel-recording", "check-microphone-permission", "get-capture-status"].includes(message.type);
    if (message.type === "get-capture-status" && liveOffscreen) return { active: true };
    return dispatch(listeners[toOffscreen ? 0 : 1], message);
  });
  const upload = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ recording_id: "server-picker", state: "queued" }), { status: 200 }));
  // Only ingestion uploads count; the later processing-status reads are answered with a failure.
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    if (!appAvailable) return Promise.reject(new TypeError("Desktop app closed"));
    if (String(url).endsWith("/health")) return Promise.resolve(new Response("{}"));
    return String(url).endsWith("/ingestion/upload") ? upload(url, init) : Promise.resolve(new Response("", { status: 503 }));
  });
  vi.stubGlobal("chrome", {
    runtime: {
      ContextType: { OFFSCREEN_DOCUMENT: "OFFSCREEN_DOCUMENT" },
      getURL: (path: string) => `chrome-extension://test/${path}`,
      getContexts: vi.fn(async () => existing ? [{ contextType: "OFFSCREEN_DOCUMENT" }] : []),
      onMessage: { addListener: (listener: Listener) => listeners.push(listener) },
      onInstalled: { addListener: vi.fn() }, onStartup: { addListener: vi.fn() },
      sendMessage: send,
    },
    tabCapture: { getMediaStreamId: vi.fn((_options, callback) => callback("direct-stream")) },
    offscreen: {
      Reason: { DISPLAY_MEDIA: "DISPLAY_MEDIA", USER_MEDIA: "USER_MEDIA" },
      createDocument: vi.fn(async () => { existing = true; }),
      closeDocument: vi.fn(async () => { existing = false; }),
    },
    storage: {
      // Existing picker tests explicitly opt out of the new countdown.
      sync: { remove: vi.fn(async () => {}) },
      local: { remove: vi.fn(async () => {}), setAccessLevel: vi.fn(async () => {}), get: vi.fn(async () => ({ sauriLocalToken: "synthetic-token", recordingSettings: { countdownSeconds, showControlBar } })), set: vi.fn(async () => {}) },
      session: {
        get: vi.fn(async () => ({ ...stored })),
        set: vi.fn(async (values: object) => { Object.assign(stored, values); }),
        remove: vi.fn(async (key: string) => { delete stored[key]; }),
      },
    },
    tabs: {
      query: vi.fn(async (query: { active?: boolean }) => query.active ? [{ id: 7, url, title }] : []),
      sendMessage: vi.fn(async (_tabId: number, message: Message): Promise<any> => {
        if (realUI && message.type === "show-countdown") return showCountdown(message.seconds as number, message.requestId as string);
        if (realUI && message.type === "cancel-countdown") { cancelCountdown(); return { ok: true }; }
        if (realUI && message.type === "recording-ui") syncRecordingUI(message.state as any);
        if (realUI && message.type === "hide-consent-banner") hideRecordingUI();
        return { ok: true, title: "Fresh Meet title" };
      }),
      create: vi.fn(async () => ({ id: 80 })),
      onRemoved: { addListener: (listener: typeof removed) => { removed = listener; } },
      onUpdated: { addListener: (listener: typeof updated) => { updated = listener; } },
    },
    scripting: { executeScript },
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: (fn: typeof alarm) => { alarm = fn; } } },
  });
  await import("./offscreen");
  const startupProcessing = vi.spyOn(await import("./recording-db"), "getProcessingCompletions");
  await import("./background");
  await vi.waitFor(() => expect(startupProcessing).toHaveBeenCalled());
  await startupProcessing.mock.results[0].value;
  return {
    display, userMedia, original, stored, stream, audio, video, upload, send,
    setAppAvailable: (value: boolean) => { appAvailable = value; },
    alarm: () => alarm({ name: "sauri-upload-check" }),
    start: (source: "picker" | "current-tab" = "picker", micDeviceId?: string, resolution?: unknown) => dispatch(listeners[1], { type: "start-capture", source, micDeviceId, ...(resolution === undefined ? {} : { resolution }) }),
    stop: () => dispatch(listeners[1], { type: "stop-capture" }),
    close: (id = 7) => removed(id),
    executeScript,
    navigate: (url: string, tabId = 7) => updated(tabId, { status: "complete" }, { url }),
    message: (message: Message, sender: chrome.runtime.MessageSender) => dispatch(listeners[1], message, sender),
  };
}

afterEach(() => { cancelCountdown(); hideRecordingUI(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("#994: native picker to durable upload", () => {
  it("records with the desktop closed and automatically sends the retained bytes when it opens", async () => {
    const h = await setup({ appAvailable: false });
    const result = await h.start();
    expect(result.ok).toBe(true);
    await h.stop();
    const { getUploadJob } = await import("./upload-queue");
    await vi.waitFor(async () => expect(await getUploadJob(result.sessionId)).toMatchObject({ status: "pending", retryCount: 0 }));
    expect(await getChunksBySession(result.sessionId)).toHaveLength(1);
    expect(h.upload).not.toHaveBeenCalled();
    h.setAppAvailable(true);
    h.alarm();
    await vi.waitFor(async () => expect(await getUploadJob(result.sessionId)).toMatchObject({ status: "done", retryCount: 0 }));
    expect(h.upload).toHaveBeenCalledOnce();
    const payload = h.upload.mock.calls[0][1]!.body as FormData;
    expect(await (payload.get("audio") as Blob).arrayBuffer()).toEqual(await media.arrayBuffer());
    await vi.waitFor(async () => expect(await getChunksBySession(result.sessionId)).toHaveLength(0));
  });

  it("creates a DISPLAY_MEDIA + USER_MEDIA offscreen and binds only after selection", async () => {
    const h = await setup();
    let select!: (stream: Stream) => void;
    h.display.mockImplementationOnce(() => new Promise(resolve => { select = resolve; }));
    const pending = h.start();
    await vi.waitFor(() => expect(h.display).toHaveBeenCalledOnce());
    expect(h.stored.sauriState).toEqual(h.original);
    expect(await completions()).toEqual([]);
    expect(await h.start()).toEqual({ ok: false, reason: "busy" });
    expect(h.display).toHaveBeenCalledOnce();
    select(h.stream);
    const result = await pending;
    expect(result).toMatchObject({ ok: true });
    expect(chrome.offscreen.createDocument).toHaveBeenCalledWith({ url: "src/offscreen.html", reasons: ["DISPLAY_MEDIA", "USER_MEDIA"], justification: "Recording tab audio and video" });
    expect(h.stored.sauriState).toMatchObject({ status: "recording", pickerSource: "picker", tabId: 7, meetingTitle: "Fresh Meet title", videoPresence: "muxed" });
    expect(await getCompletion(result.sessionId)).toMatchObject({ capturedTabId: 7, provider: "meet", status: "capturing" });
    expect(h.send.mock.calls.find(([message]) => message.type === "start-recording")![0]).not.toHaveProperty("streamId");
    expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(7, { type: "show-consent-banner" });
    expect(h.stored.sauriCaptureRequest).toBeUndefined();
  });

  it.each(["NotAllowedError", "AbortError"])("%s preserves prior state and creates no session", async name => {
    const h = await setup();
    h.display.mockRejectedValueOnce(new DOMException("Dismissed", name));
    expect(await h.start()).toEqual({ ok: false, reason: "cancelled" });
    expect(h.stored.sauriState).toEqual(h.original);
    expect(h.stored.sauriCaptureRequest).toBeUndefined();
    expect(await completions()).toEqual([]);
    expect(chrome.action.setBadgeText).not.toHaveBeenCalled();
    expect(chrome.tabs.sendMessage).not.toHaveBeenCalledWith(7, { type: "show-consent-banner" });
    expect(await h.start()).toMatchObject({ ok: true });
  });

  it("returns the actionable missing-audio outcome without changing state or creating a session", async () => {
    const h = await setup();
    h.display.mockResolvedValueOnce(new Stream([h.video]));
    expect(await h.start()).toEqual({ ok: false, reason: "no-tab-audio" });
    expect(h.video.stop).toHaveBeenCalledOnce();
    expect(h.stored.sauriState).toEqual(h.original);
    expect(await completions()).toEqual([]);
    expect(chrome.action.setBadgeText).not.toHaveBeenCalled();
  });

  it("recreates an idle legacy offscreen with the current reasons", async () => {
    const h = await setup({ existing: true });
    expect(await h.start()).toMatchObject({ ok: true });
    expect(chrome.offscreen.closeDocument).toHaveBeenCalledOnce();
    expect(chrome.offscreen.createDocument).toHaveBeenCalledOnce();
    expect(vi.mocked(chrome.offscreen.closeDocument).mock.invocationCallOrder[0])
      .toBeLessThan(vi.mocked(chrome.offscreen.createDocument).mock.invocationCallOrder[0]);
  });

  it.each([{ recording: true }, { liveOffscreen: true }])("preserves an active legacy or offscreen capture (%j)", async options => {
    const h = await setup({ existing: true, ...options });
    expect(await h.start()).toEqual({ ok: false, reason: "busy" });
    expect(chrome.offscreen.closeDocument).not.toHaveBeenCalled();
    expect(chrome.offscreen.createDocument).not.toHaveBeenCalled();
    expect(h.display).not.toHaveBeenCalled();
    expect(h.stored.sauriState).toEqual(h.original);
  });

  it.each(["ended", "origin-close"])("%s finalizes and uploads the same bytes and opens its portal review once", async trigger => {
    const h = await setup();
    const result = await h.start();
    const completion = await getCompletion(result.sessionId);
    expect(completion?.status).toBe("capturing");
    await h.close(99);
    expect(Recorder.last.stop).not.toHaveBeenCalled();
    if (trigger === "ended") h.video.dispatchEvent(new Event("ended"));
    else await h.close();
    await vi.waitFor(() => expect(h.upload).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(chrome.tabs.create).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
    const [, init] = (h.upload.mock.calls as unknown as [string, RequestInit][])[0];
    const payload = init.body as FormData;
    expect((payload.get("audio") as Blob).size).toBe(media.size);
    expect(JSON.parse(payload.get("data") as string)).toMatchObject({ meeting_id: completion!.meetingId, idempotency_key: result.sessionId, video_presence: "muxed" });
    expect(await getCompletion(result.sessionId)).toMatchObject({ recordingId: "server-picker", reviewStatus: "review_opened", trigger: "captured_tab_closed" });
    expect(chrome.tabs.create).toHaveBeenCalledWith({ url: `http://localhost:8000/?meetingId=${completion!.meetingId}` });
    await h.close();
    await h.stop();
    h.video.dispatchEvent(new Event("ended"));
    expect(Recorder.last.stop).toHaveBeenCalledOnce();
    expect(h.upload).toHaveBeenCalledOnce();
  });

  describe("any browser tab, not only Google Meet", () => {
    const uploaded = async (h: Awaited<ReturnType<typeof setup>>) => {
      h.video.dispatchEvent(new Event("ended"));
      await vi.waitFor(() => expect(h.upload).toHaveBeenCalledOnce());
      const [, init] = (h.upload.mock.calls as unknown as [string, RequestInit][])[0];
      return JSON.parse((init.body as FormData).get("data") as string);
    };

    it("injects the overlay before recording and records a regular tab as a tab capture", async () => {
      const h = await setup({ url: "https://example.com/talk", title: "  Conference talk  " });
      const result = await h.start();
      expect(result).toMatchObject({ ok: true });
      expect(h.executeScript).toHaveBeenCalledOnce();
      expect(h.executeScript).toHaveBeenCalledWith({ target: { tabId: 7 }, files: [expect.stringContaining("entry")] });
      expect(h.executeScript.mock.invocationCallOrder[0]).toBeLessThan(h.send.mock.invocationCallOrder[0]);
      expect(h.stored.sauriState).toMatchObject({ provider: "tab", tabId: 7, meetingUrl: "", meetingTitle: "Conference talk", overlayAvailable: true });
      expect(await getCompletion(result.sessionId)).toMatchObject({ capturedTabId: 7, provider: "tab", status: "capturing" });
      expect(chrome.tabs.sendMessage).toHaveBeenCalledWith(7, { type: "show-consent-banner" });
      expect(chrome.tabs.sendMessage).not.toHaveBeenCalledWith(7, { type: "get-current-title" });
    });

    it("names the upload after the tab (trimmed, capped) and sends no meet_link", async () => {
      const h = await setup({ url: "https://example.com/talk", title: ` ${"x".repeat(300)} ` });
      await h.start();
      const payload = await uploaded(h);
      expect(payload.title).toBe("x".repeat(200));
      expect(payload.meet_link).toBeNull();
    });

    it("sends a null title when the tab has none", async () => {
      const h = await setup({ url: "https://example.com/talk", title: "   " });
      await h.start();
      expect((await uploaded(h)).title).toBeNull();
    });

    it("keeps the Meet title and link for a Meet tab without injecting anything", async () => {
      const h = await setup({ url: "https://meet.google.com/abc-defg-hij" });
      await h.start();
      expect(h.executeScript).not.toHaveBeenCalled();
      expect(h.stored.sauriState).toMatchObject({ provider: "meet", meetingTitle: "Fresh Meet title", overlayAvailable: true });
      const payload = await uploaded(h);
      expect(payload).toMatchObject({ title: "Fresh Meet title", meet_link: "https://meet.google.com/abc-defg-hij" });
    });

    it("shows the countdown on a regular tab and records only after it ends", async () => {
      const h = await setup({ url: "https://example.com/talk", countdownSeconds: 3, realUI: true });
      vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
      const pending = h.start();
      await vi.waitFor(() => expect(document.getElementById("sauri-countdown-host")).not.toBeNull());
      expect(await completions()).toEqual([]);
      await vi.advanceTimersByTimeAsync(3200);
      expect(await pending).toMatchObject({ ok: true });
      expect(document.getElementById("sauri-countdown-host")).toBeNull();
    });

    it.each([
      ["a browser page", "chrome://extensions", true],
      ["the Chrome Web Store", "https://chromewebstore.google.com/detail/x", true],
      ["a page that refuses injection", "https://example.com/doc.pdf", false],
    ])("records %s through the panel alone, with no overlay, banner or countdown", async (_name, url, injectable) => {
      const h = await setup({ url, injectable, countdownSeconds: 3 });
      const result = await h.start();
      expect(result).toMatchObject({ ok: true });
      if (injectable) expect(h.executeScript).not.toHaveBeenCalled();
      else expect(h.executeScript).toHaveBeenCalledOnce();
      expect(h.stored.sauriState).toMatchObject({ status: "recording", tabId: 7, overlayAvailable: false });
      expect(chrome.tabs.sendMessage).not.toHaveBeenCalled();
      await uploaded(h);
      await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
      expect(chrome.tabs.sendMessage).not.toHaveBeenCalled();
    });

    it("keeps recording without a countdown when the injected script stops answering", async () => {
      const h = await setup({ url: "https://example.com/talk", countdownSeconds: 3 });
      vi.mocked(chrome.tabs.sendMessage).mockRejectedValueOnce(new Error("Receiving end does not exist"));
      expect(await h.start()).toMatchObject({ ok: true });
    });

    it("injects again after a full page load in the recorded tab and records the new availability", async () => {
      const h = await setup({ url: "https://example.com/a", injectable: false });
      await h.start();
      expect(h.stored.sauriState.overlayAvailable).toBe(false);
      h.executeScript.mockResolvedValue([]);
      await h.navigate("https://example.com/b");
      expect(h.executeScript).toHaveBeenCalledTimes(2);
      expect(h.stored.sauriState.overlayAvailable).toBe(true);
      h.executeScript.mockRejectedValue(new Error("Cannot access contents of the page"));
      await h.navigate("https://example.com/c");
      expect(h.stored.sauriState.overlayAvailable).toBe(false);
    });

    it("does not inject for other tabs, unfinished loads or when nothing is recording", async () => {
      const h = await setup({ url: "https://example.com/a" });
      await h.navigate("https://example.com/idle");
      expect(h.executeScript).not.toHaveBeenCalled();
      await h.start();
      expect(h.executeScript).toHaveBeenCalledOnce();
      await h.navigate("https://example.com/other", 99);
      expect(h.executeScript).toHaveBeenCalledOnce();
    });

    it("lets the injected script recover the controls of its own recorded tab only", async () => {
      const h = await setup({ url: "https://example.com/a" });
      await h.start();
      const own = await h.message({ type: "get-recording-ui" }, { tab: { id: 7 } } as chrome.runtime.MessageSender);
      expect(own.state).toMatchObject({ showControlBar: true });
      const other = await h.message({ type: "get-recording-ui" }, { tab: { id: 8 } } as chrome.runtime.MessageSender);
      expect(other.state).toBeUndefined();
    });

    it("accepts overlay stop commands from the recorded regular tab", async () => {
      const h = await setup({ url: "https://example.com/a" });
      const { sessionId } = await h.start();
      const rejected = await h.message({ type: "stop-capture", sessionId }, { tab: { id: 8 } } as chrome.runtime.MessageSender);
      expect(rejected).toEqual({ ok: false });
      expect(Recorder.last.stop).not.toHaveBeenCalled();
      const accepted = await h.message({ type: "stop-capture", sessionId }, { tab: { id: 7 } } as chrome.runtime.MessageSender);
      expect(accepted).toEqual({ ok: true });
      expect(Recorder.last.stop).toHaveBeenCalledOnce();
      await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
      expect(h.upload).toHaveBeenCalledOnce();
    });
  });

  it("audio_only still opens the picker and records only audio", async () => {
    const h = await setup({ captureMode: "audio_only" });
    expect(await h.start()).toMatchObject({ ok: true });
    expect(h.display).toHaveBeenCalledOnce();
    expect(Recorder.last.stream.getVideoTracks()).toEqual([]);
    expect(Recorder.last.stream.getAudioTracks()).toEqual([h.audio]);
    expect(Recorder.last.options.mimeType).toBe("audio/webm;codecs=opus");
    expect(h.stored.sauriState.videoPresence).toBe("absent");
  });

  it("page scripts cannot bind a pending selection or start a picker", async () => {
    const h = await setup();
    for (const type of ["capture-ready", "start-capture"]) {
      expect(await h.message({ type, sessionId: "forged" }, { tab: { id: 7 } as chrome.tabs.Tab })).toMatchObject({ ok: false });
    }
    expect(h.display).not.toHaveBeenCalled();
    expect(await completions()).toEqual([]);
  });
});

describe("#994: current-tab shortcut", () => {
  it("obtains the active tab's stream ID and records its diagnostic source", async () => {
    const h = await setup();
    const result = await h.start("current-tab");
    expect(result).toMatchObject({ ok: true });
    expect(chrome.tabCapture.getMediaStreamId).toHaveBeenCalledWith({ targetTabId: 7 }, expect.any(Function));
    expect(h.display).not.toHaveBeenCalled();
    expect(h.userMedia).toHaveBeenCalledOnce();
    expect(h.stored.sauriState).toMatchObject({ pickerSource: "current-tab", tabId: 7 });
    expect(await getCompletion(result.sessionId)).toMatchObject({ status: "capturing", capturedTabId: 7 });
    expect(h.send).toHaveBeenCalledWith(expect.objectContaining({ type: "start-recording", source: "current-tab", streamId: "direct-stream" }));
  });

  it.each(["picker", "current-tab"] as const)("%s microphone denial returns permission guidance without a completion or changed state", async source => {
    const h = await setup();
    h.userMedia.mockImplementation(async constraints => {
      if (typeof constraints.audio === "object" && constraints.audio.deviceId) {
        throw new DOMException("Permission dismissed", "NotAllowedError");
      }
      return h.stream;
    });
    expect(await h.start(source, "mic")).toEqual({ ok: false, reason: "microphone-permission" });
    expect(h.stored.sauriState).toEqual(h.original);
    expect(h.stored.sauriCaptureRequest).toBeUndefined();
    expect(await completions()).toEqual([]);
    expect(h.video.stop).toHaveBeenCalled();
    expect(h.audio.stop).toHaveBeenCalled();
    expect(chrome.action.setBadgeText).not.toHaveBeenCalled();
  });

  it("getMediaStreamId failure returns an actionable outcome with no orphaned session", async () => {
    const h = await setup();
    vi.mocked(chrome.tabCapture.getMediaStreamId).mockImplementation((_options, callback) => {
      Object.defineProperty(chrome.runtime, "lastError", { configurable: true, value: { message: "Extension has not been invoked for the current page" } });
      callback!("");
      Object.defineProperty(chrome.runtime, "lastError", { configurable: true, value: undefined });
    });
    expect(await h.start("current-tab")).toEqual({ ok: false, reason: "current-tab-unavailable" });
    expect(h.stored.sauriState).toEqual(h.original);
    expect(h.stored.sauriCaptureRequest).toBeUndefined();
    expect(await completions()).toEqual([]);
    expect(h.userMedia).not.toHaveBeenCalled();
    expect(chrome.action.setBadgeText).not.toHaveBeenCalled();
  });

  it.each(["chrome://settings", "chrome-extension://test/options.html", "https://chromewebstore.google.com/detail/test", "about:blank"])("rejects restricted current-tab URL %s before requesting a stream", async url => {
    const h = await setup({ url });
    expect(await h.start("current-tab")).toEqual({ ok: false, reason: "current-tab-unavailable" });
    expect(chrome.tabCapture.getMediaStreamId).not.toHaveBeenCalled();
    expect(await completions()).toEqual([]);
    expect(h.stored.sauriState).toEqual(h.original);
  });

  it.each(["ended", "origin-close"])("direct capture %s finalizes and uploads exactly once", async trigger => {
    const h = await setup();
    const { sessionId } = await h.start("current-tab");
    if (trigger === "ended") h.video.dispatchEvent(new Event("ended"));
    else await h.close();
    await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
    expect(h.upload).toHaveBeenCalledOnce();
    expect(await getCompletion(sessionId)).toMatchObject({ trigger: "captured_tab_closed", recordingId: "server-picker", reviewStatus: "review_opened" });
    await h.close();
    await h.stop();
    expect(Recorder.last.stop).toHaveBeenCalledOnce();
    expect(h.upload).toHaveBeenCalledOnce();
  });
});


describe("Meet recording controls", () => {
  it("waits three seconds after selection before recording or creating a durable session", async () => {
    const h = await setup({ countdownSeconds: 3, realUI: true });
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    const pending = h.start();
    await vi.waitFor(() => expect(document.getElementById("sauri-countdown-host")).not.toBeNull());
    expect(h.display).toHaveBeenCalledOnce();
    expect(Recorder.last?.state).not.toBe("recording");
    expect(await completions()).toEqual([]);
    const countdown = document.getElementById("sauri-countdown-host")!.shadowRoot!;
    expect(countdown.querySelector("strong")!.textContent).toBe("3");
    await vi.advanceTimersByTimeAsync(2000);
    expect(countdown.querySelector("strong")!.textContent).toBe("1");
    expect(await completions()).toEqual([]);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await pending).toMatchObject({ ok: true });
    expect(document.getElementById("sauri-countdown-host")).toBeNull();
  });

  it.each([5, 10])("shows a %s second countdown from the stored setting", async seconds => {
    const h = await setup({ countdownSeconds: seconds, realUI: true });
    const pending = h.start();
    await vi.waitFor(() => expect(document.getElementById("sauri-countdown-host")).not.toBeNull());
    expect(document.getElementById("sauri-countdown-host")!.shadowRoot!.querySelector("strong")!.textContent).toBe(String(seconds));
    expect(h.stored.sauriCaptureRequest.countdownSeconds).toBe(seconds);
    cancelCountdown();
    expect(await pending).toEqual({ ok: false, reason: "cancelled" });
  });

  it("zero seconds starts without a countdown", async () => {
    const h = await setup({ countdownSeconds: 0 });
    expect(await h.start()).toMatchObject({ ok: true });
    expect(chrome.tabs.sendMessage).not.toHaveBeenCalledWith(7, expect.objectContaining({ type: "show-countdown" }));
  });

  it.each(["overlay", "panel"])("cancelling the countdown from %s leaves no capture or session", async source => {
    const h = await setup({ countdownSeconds: 3, realUI: true });
    const pending = h.start();
    await vi.waitFor(() => expect(document.getElementById("sauri-countdown-host")).not.toBeNull());
    if (source === "overlay") document.getElementById("sauri-countdown-host")!.shadowRoot!.querySelector("button")!.click();
    else expect(await h.message({ type: "cancel-capture" }, {})).toEqual({ ok: true });
    expect(await pending).toEqual({ ok: false, reason: "cancelled" });
    expect(await completions()).toEqual([]);
    expect(h.stored.sauriCaptureRequest).toBeUndefined();
    expect(h.stored.sauriCountdown).toBeUndefined();
    expect(h.video.stop).toHaveBeenCalledOnce();
    expect(h.audio.stop).toHaveBeenCalledOnce();
    expect(h.upload).not.toHaveBeenCalled();
  });

  it("pauses and resumes the actual media owner and projects an honest timer", async () => {
    const h = await setup({ realUI: true });
    const { sessionId } = await h.start();
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    const startAt = h.stored.sauriState.segmentStartedAt;
    vi.setSystemTime(startAt + 4000);
    expect(await h.message({ type: "pause-capture", sessionId }, { tab: { id: 7 } as chrome.tabs.Tab })).toEqual({ ok: true });
    expect(Recorder.last.pause).toHaveBeenCalledOnce();
    expect(h.stored.sauriState).toMatchObject({ paused: true, elapsedMs: 4000 });
    const root = document.getElementById("sauri-recording-host")!.shadowRoot!;
    expect(root.querySelector(".time")!.textContent).toBe("00:04");
    await vi.advanceTimersByTimeAsync(5000);
    expect(root.querySelector(".time")!.textContent).toBe("00:04");
    expect(await h.message({ type: "resume-capture" }, {})).toEqual({ ok: true });
    expect(Recorder.last.resume).toHaveBeenCalledOnce();
    expect(h.stored.sauriState.paused).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(root.querySelector(".time")!.textContent).toBe("00:06");
  });

  it("discards committed and final chunks without uploading or leaving a durable record", async () => {
    const h = await setup();
    const { sessionId } = await h.start();
    Recorder.last.ondataavailable!({ data: media });
    expect(await h.message({ type: "cancel-capture" }, {})).toEqual({ ok: true });
    expect(Recorder.last.stop).toHaveBeenCalledOnce();
    expect(await getCompletion(sessionId)).toBeUndefined();
    expect(await getChunksBySession(sessionId)).toEqual([]);
    const { getUploadJob } = await import("./upload-queue");
    expect(await getUploadJob(sessionId)).toBeUndefined();
    expect(h.send).not.toHaveBeenCalledWith(expect.objectContaining({ type: "recording-stopped" }));
    h.video.dispatchEvent(new Event("ended"));
    await h.close();
    expect(h.upload).not.toHaveBeenCalled();
    expect(h.stored.sauriState).toMatchObject({ status: "idle", paused: false });
  });

  it("stop while paused retains the existing upload path and bytes", async () => {
    const h = await setup();
    const { sessionId } = await h.start();
    await h.message({ type: "pause-capture" }, {});
    expect(await h.stop()).toEqual({ ok: true });
    await vi.waitFor(() => expect(h.upload).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
    expect(await getCompletion(sessionId)).toMatchObject({ trigger: "stop", recordingId: "server-picker" });
    const [, init] = (h.upload.mock.calls as unknown as [string, RequestInit][])[0];
    expect(((init.body as FormData).get("audio") as Blob).size).toBe(media.size);
  });

  it("hidden controls do not prevent recording or finalization on sharing ended", async () => {
    const h = await setup({ showControlBar: false, realUI: true });
    expect(await h.start()).toMatchObject({ ok: true });
    expect(document.getElementById("sauri-recording-host")).toBeNull();
    h.video.dispatchEvent(new Event("ended"));
    await vi.waitFor(() => expect(h.upload).toHaveBeenCalledOnce());
  });

  it("rejects controls from other tabs and stale sessions", async () => {
    const h = await setup();
    const { sessionId } = await h.start();
    for (const type of ["pause-capture", "resume-capture", "cancel-capture", "stop-capture"]) {
      expect(await h.message({ type, sessionId }, { tab: { id: 99 } as chrome.tabs.Tab })).toEqual({ ok: false });
      expect(await h.message({ type, sessionId: "stale" }, { tab: { id: 7 } as chrome.tabs.Tab })).toEqual({ ok: false });
      expect(await h.message({ type }, { tab: { id: 7 } as chrome.tabs.Tab })).toEqual({ ok: false });
    }
    expect(Recorder.last.pause).not.toHaveBeenCalled();
    expect(Recorder.last.stop).not.toHaveBeenCalled();
  });

  it.each(["prompt", "denied"])("microphone permission %s blocks capture without prompting", async permission => {
    const h = await setup();
    vi.mocked(navigator.permissions.query).mockResolvedValue({ state: permission } as PermissionStatus);
    expect(await h.start("picker", "mic")).toEqual({ ok: false, reason: "microphone-permission" });
    expect(h.display).not.toHaveBeenCalled();
    expect(h.userMedia).not.toHaveBeenCalled();
    expect(await completions()).toEqual([]);
  });
});


describe("recording resolution", () => {
  const recordedResolution = (h: Awaited<ReturnType<typeof setup>>) => h.send.mock.calls.find(([message]) => message.type === "start-recording")![0].resolution;

  it.each([[{ width: 854, height: 480 }], [{ width: 1280, height: 720 }], [{ width: 1920, height: 1080 }]])("passes the allowed size %j to the recorder and the session state", async size => {
    const h = await setup();
    expect(await h.start("picker", undefined, size)).toMatchObject({ ok: true });
    expect(recordedResolution(h)).toEqual(size);
    expect(h.stored.sauriState.resolution).toEqual(size);
  });

  it.each([undefined, { width: 3840, height: 2160 }, { width: 1280, height: 1080 }, "1080p", null])("falls back to 720p for %j", async size => {
    const h = await setup();
    expect(await h.start("picker", undefined, size)).toMatchObject({ ok: true });
    expect(recordedResolution(h)).toEqual({ width: 1280, height: 720 });
  });
});

describe("recording control bar setting changed mid-recording", () => {
  const storeControlBar = (showControlBar: boolean) => vi.mocked(chrome.storage.local.get).mockImplementation(async () => ({ sauriLocalToken: "synthetic-token", recordingSettings: { countdownSeconds: 0, showControlBar } }));

  it("hides and shows the floating bar without touching the recording", async () => {
    const h = await setup({ realUI: true });
    expect(await h.start()).toMatchObject({ ok: true });
    expect(document.getElementById("sauri-recording-host")).not.toBeNull();
    storeControlBar(false);
    expect(await h.message({ type: "recording-settings-changed" }, {})).toEqual({ ok: true });
    expect(document.getElementById("sauri-recording-host")).toBeNull();
    expect(h.stored.sauriState).toMatchObject({ status: "recording", showControlBar: false });
    expect(Recorder.last.stop).not.toHaveBeenCalled();
    storeControlBar(true);
    expect(await h.message({ type: "recording-settings-changed" }, {})).toEqual({ ok: true });
    expect(document.getElementById("sauri-recording-host")).not.toBeNull();
  });

  it("does nothing while idle and ignores page senders", async () => {
    const h = await setup({ realUI: true });
    storeControlBar(false);
    expect(await h.message({ type: "recording-settings-changed" }, {})).toEqual({ ok: true });
    expect(h.stored.sauriState).toEqual(h.original);
    expect(await h.message({ type: "recording-settings-changed" }, { tab: { id: 7 } as chrome.tabs.Tab })).toEqual({ ok: false, error: "Message requires an extension capture context" });
  });
});

describe("recording control edge cases", () => {
  it.each([undefined, { countdownSeconds: 7, showControlBar: "invalid" }])("uses safe defaults for missing or malformed preferences (%j)", async settings => {
    const h = await setup({ realUI: true });
    vi.mocked(chrome.storage.local.get).mockImplementationOnce(async () => ({ sauriLocalToken: "synthetic-token", recordingSettings: settings }));
    const pending = h.start();
    await vi.waitFor(() => expect(document.getElementById("sauri-countdown-host")).not.toBeNull());
    expect(document.getElementById("sauri-countdown-host")!.shadowRoot!.querySelector("strong")!.textContent).toBe("3");
    expect(h.stored.sauriCaptureRequest.state.showControlBar).toBe(true);
    cancelCountdown();
    expect(await pending).toEqual({ ok: false, reason: "cancelled" });
  });

  it("ending sharing during countdown cancels without recording or uploading", async () => {
    const h = await setup({ countdownSeconds: 3, realUI: true });
    const pending = h.start();
    await vi.waitFor(() => expect(document.getElementById("sauri-countdown-host")).not.toBeNull());
    h.video.dispatchEvent(new Event("ended"));
    expect(await pending).toEqual({ ok: false, reason: "sharing-ended" });
    expect(await completions()).toEqual([]);
    expect(h.upload).not.toHaveBeenCalled();
    expect(Recorder.last).toBeUndefined();
  });

  it("recovers a Meet tab whose page script stopped answering by reinjecting it", async () => {
    const h = await setup({ countdownSeconds: 3 });
    const original = vi.mocked(chrome.tabs.sendMessage).getMockImplementation()!;
    let failed = false;
    vi.mocked(chrome.tabs.sendMessage).mockImplementation(async (tabId: number, message: any) => {
      if (message.type === "show-countdown" && !failed) { failed = true; throw new Error("Receiving end does not exist"); }
      return (original as (...args: unknown[]) => Promise<unknown>)(tabId, message);
    });
    expect(await h.start()).toMatchObject({ ok: true });
    expect(h.executeScript).toHaveBeenCalledWith({ target: { tabId: 7 }, files: [expect.stringContaining("entry")] });
    const logged = vi.mocked(chrome.storage.local.set).mock.calls.map(call => JSON.stringify(call[0])).join("");
    expect(logged).toContain("countdown-unreachable");
    expect(logged).not.toContain("countdown-skipped");
  });

  it("records without a countdown on Meet when the page script cannot be recovered", async () => {
    const h = await setup({ countdownSeconds: 3, injectable: false });
    const original = vi.mocked(chrome.tabs.sendMessage).getMockImplementation()!;
    vi.mocked(chrome.tabs.sendMessage).mockImplementation(async (tabId: number, message: any) => {
      if (message.type === "show-countdown") { throw new Error("Receiving end does not exist"); }
      return (original as (...args: unknown[]) => Promise<unknown>)(tabId, message);
    });
    expect(await h.start()).toMatchObject({ ok: true });
    expect(await completions()).toHaveLength(1);
    const logged = vi.mocked(chrome.storage.local.set).mock.calls.map(call => JSON.stringify(call[0])).join("");
    expect(logged).toContain("countdown-unreachable");
    expect(logged).toContain("countdown-skipped");
  });

  it("retains a real recording state when MediaRecorder cannot pause", async () => {
    const h = await setup();
    await h.start();
    Recorder.last.pause.mockImplementationOnce(() => { throw new DOMException("Unsupported pause", "NotSupportedError"); });
    expect(await h.message({ type: "pause-capture" }, {})).toEqual({ ok: false });
    expect(h.stored.sauriState.paused).toBe(false);
    expect(Recorder.last.state).toBe("recording");
    expect(await h.stop()).toEqual({ ok: true });
    await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
    expect(h.upload).toHaveBeenCalledOnce();
  });

  it("keeps discarding when sharing ends concurrently and permits a fresh session", async () => {
    const h = await setup();
    const { sessionId } = await h.start();
    const discarding = h.message({ type: "cancel-capture" }, {});
    await vi.waitFor(() => expect(h.send).toHaveBeenCalledWith({ type: "cancel-recording", sessionId }));
    h.video.dispatchEvent(new Event("ended"));
    expect(await discarding).toEqual({ ok: true });
    expect(h.upload).not.toHaveBeenCalled();
    expect(await getCompletion(sessionId)).toBeUndefined();
    h.display.mockResolvedValueOnce(new Stream([new Track("audio"), new Track("video")]));
    expect(await h.start()).toMatchObject({ ok: true });
  });

  it("cannot discard a recording after the media owner has accepted stop", async () => {
    const h = await setup();
    const { sessionId } = await h.start();
    expect(await h.stop()).toEqual({ ok: true });
    expect(await h.message({ type: "cancel-capture", sessionId }, {})).toEqual({ ok: false });
    await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
    expect(h.upload).toHaveBeenCalledOnce();
    expect(await getCompletion(sessionId)).toMatchObject({ trigger: "stop", recordingId: "server-picker" });
  });
});
