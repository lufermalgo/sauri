import { readFileSync } from "node:fs";
import { Blob as NativeBlob } from "node:buffer";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IDBFactory, IDBKeyRange } from "fake-indexeddb";
import { COMPLETION_STORE, getCompletion, openDB } from "./recording-db";

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

async function setup({ url = "https://meet.google.com/test-picker", existing = false, recording = false, liveOffscreen = false, captureMode = "screen_audio" } = {}) {
  vi.resetModules();
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
  const video = new Track("video");
  const audio = new Track("audio");
  const stream = new Stream([audio, video]);
  const display = vi.fn(async () => stream);
  let locked = false;
  const userMedia = vi.fn(async (_constraints: MediaStreamConstraints) => stream);
  vi.stubGlobal("navigator", {
    mediaDevices: { getDisplayMedia: display, getUserMedia: userMedia },
    locks: { request: vi.fn(async (_name, _options, callback) => {
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
  function dispatch(listener: Listener, message: Message, sender = {}) {
    return new Promise<any>(resolve => {
      const pending = listener(message, sender, resolve);
      if (!pending) resolve(undefined);
    });
  }
  const send = vi.fn(async (message: Message) => {
    const toOffscreen = ["start-recording", "stop-recording", "get-capture-status"].includes(message.type);
    if (message.type === "get-capture-status" && liveOffscreen) return { active: true };
    return dispatch(listeners[toOffscreen ? 0 : 1], message);
  });
  const upload = vi.fn(async () => new Response(JSON.stringify({ recording_id: "server-picker", state: "queued" }), { status: 200 }));
  vi.stubGlobal("fetch", upload);
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
      session: {
        get: vi.fn(async () => ({ ...stored })),
        set: vi.fn(async (values: object) => { Object.assign(stored, values); }),
        remove: vi.fn(async (key: string) => { delete stored[key]; }),
      },
      sync: { get: vi.fn(async () => ({})) },
    },
    tabs: {
      query: vi.fn(async (query: { active?: boolean }) => query.active ? [{ id: 7, url }] : []),
      sendMessage: vi.fn(async () => ({ title: "Fresh Meet title" })),
      create: vi.fn(async () => ({ id: 80 })),
      onRemoved: { addListener: (listener: typeof removed) => { removed = listener; } },
    },
    action: { onClicked: { addListener: vi.fn() }, setBadgeText: vi.fn(), setBadgeBackgroundColor: vi.fn() },
    sidePanel: { setPanelBehavior: vi.fn(async () => undefined), open: vi.fn() },
    alarms: { create: vi.fn(), onAlarm: { addListener: vi.fn() } },
  });
  await import("./offscreen");
  const startupProcessing = vi.spyOn(await import("./recording-db"), "getProcessingCompletions");
  await import("./background");
  await vi.waitFor(() => expect(startupProcessing).toHaveBeenCalled());
  await startupProcessing.mock.results[0].value;
  return {
    display, userMedia, original, stored, stream, audio, video, upload, send,
    start: (source: "picker" | "current-tab" = "picker", micDeviceId?: string) => dispatch(listeners[1], { type: "start-capture", source, micDeviceId }),
    stop: () => dispatch(listeners[1], { type: "stop-capture" }),
    close: (id = 7) => removed(id),
    message: (message: Message, sender: chrome.runtime.MessageSender) => dispatch(listeners[1], message, sender),
  };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("#994: native picker to durable upload", () => {
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
    expect(chrome.tabs.create).toHaveBeenCalledWith({ url: `http://localhost:5173/?meetingId=${completion!.meetingId}` });
    await h.close();
    await h.stop();
    h.video.dispatchEvent(new Event("ended"));
    expect(Recorder.last.stop).toHaveBeenCalledOnce();
    expect(h.upload).toHaveBeenCalledOnce();
  });

  it("captures from a non-Meet origin without title/banner messages or a stale Meet URL", async () => {
    const h = await setup({ url: "https://example.com" });
    const result = await h.start();
    expect(result).toMatchObject({ ok: true });
    expect(h.stored.sauriState).toMatchObject({ provider: "meet", tabId: 7, meetingUrl: "" });
    expect(h.stored.sauriState.meetingTitle).toBeUndefined();
    expect(chrome.tabs.sendMessage).not.toHaveBeenCalled();
    h.video.dispatchEvent(new Event("ended"));
    await vi.waitFor(() => expect(h.upload).toHaveBeenCalledOnce());
    await vi.waitFor(() => expect(h.stored.sauriState.status).toBe("idle"));
    expect(chrome.tabs.sendMessage).not.toHaveBeenCalled();
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
