/**
 * Tests for the offscreen document's capture layer (offscreen.ts).
 *
 * Feature: meeting-capture-transcription
 * Task: 14.8 — Validates: Requirements 2.1, 2.2
 *
 * Covers: A/V composition per capture mode, selected mimeType,
 * and mixing microphone audio with tab audio.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { IDBFactory } from "fake-indexeddb";
import { Blob as NodeBlob } from "node:buffer";
import { createCompletion, getCompletion } from "./recording-db";

type MessageListener = (
  message: Record<string, unknown>,
  sender: unknown,
  sendResponse: (response: unknown) => void
) => boolean | void;

let registeredListener: MessageListener | undefined;

class FakeTrack extends EventTarget {
  constructor(public kind: "audio" | "video") { super(); }
  getSettings = () => ({ displaySurface: "browser" });
  readyState = "live";
  stop = vi.fn();
}

class FakeMediaStream {
  private tracks: FakeTrack[];
  constructor(tracks: FakeTrack[] = []) {
    this.tracks = tracks;
  }
  getTracks() {
    return this.tracks;
  }
  getVideoTracks() {
    return this.tracks.filter((t) => t.kind === "video");
  }
  getAudioTracks() {
    return this.tracks.filter((t) => t.kind === "audio");
  }
}

class FakeAudioContext {
  static lastInstance: FakeAudioContext | null = null;
  constructor() { FakeAudioContext.lastInstance = this; }
  destination = {};
  createMediaStreamSource = vi.fn((_stream: FakeMediaStream) => ({
    connect: vi.fn(),
  }));
  createMediaStreamDestination = vi.fn(() => ({
    stream: new FakeMediaStream([new FakeTrack("audio")]),
  }));
  close = vi.fn();
}

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);
  static lastInstance: FakeMediaRecorder | null = null;
  ondataavailable: ((e: unknown) => void) | null = null;
  onstop: (() => void) | null = null;
  state = "inactive";
  constructor(
    public stream: FakeMediaStream,
    public options: { mimeType: string }
  ) {
    FakeMediaRecorder.lastInstance = this;
  }
  start = vi.fn(() => { this.state = "recording"; });
  stop = vi.fn(() => { this.state = "inactive"; });
  pause = vi.fn(() => { this.state = "paused"; });
  resume = vi.fn(() => { this.state = "recording"; });
}

async function loadOffscreenWithMocks(getUserMediaImpl: (constraints: unknown) => Promise<FakeMediaStream>) {
  vi.resetModules();
  registeredListener = undefined;
  vi.stubGlobal("indexedDB", new IDBFactory());

  vi.stubGlobal("chrome", {
    runtime: {
      onMessage: {
        addListener: (listener: MessageListener) => {
          registeredListener = listener;
        },
      },
      sendMessage: vi.fn(async () => ({ ok: true })),
    },
  });
  vi.stubGlobal("navigator", {
    permissions: { query: vi.fn(async () => ({ state: "granted" })) },
    mediaDevices: {
      // vitest 4 returns the same mock from vi.fn(mock), so wrap the implementation to keep two distinct mocks.
      getDisplayMedia: vi.fn((constraints: unknown) => getUserMediaImpl(constraints)),
      getUserMedia: vi.fn((constraints: unknown) => getUserMediaImpl(constraints)),
    },
  });
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("MediaStream", FakeMediaStream);

  await import("./offscreen");
}

describe("Offscreen document — A/V composition and capture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeAudioContext.lastInstance = null;
    FakeMediaRecorder.lastInstance = null;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ignores unbound/foreign stops and stops the same recorder only once", async () => {
    await loadOffscreenWithMocks(async () => new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]));
    await new Promise(resolve => registeredListener!({ type: "start-recording", sessionId: "active" }, {}, resolve));
    const recorder = FakeMediaRecorder.lastInstance!;
    registeredListener!({ type: "stop-recording", sessionId: "other" }, {}, vi.fn());
    registeredListener!({ type: "stop-recording" }, {}, vi.fn());
    expect(recorder.stop).not.toHaveBeenCalled();
    registeredListener!({ type: "stop-recording", sessionId: "active" }, {}, vi.fn());
    registeredListener!({ type: "stop-recording", sessionId: "active" }, {}, vi.fn());
    expect(recorder.stop).toHaveBeenCalledTimes(1);
  });

  it("keeps stop intent while getDisplayMedia is still starting", async () => {
    let release!: (stream: FakeMediaStream) => void;
    await loadOffscreenWithMocks(() => new Promise(resolve => { release = resolve; }));
    const started = new Promise(resolve => registeredListener!({ type: "start-recording", sessionId: "starting" }, {}, resolve));
    registeredListener!({ type: "stop-recording", sessionId: "starting" }, {}, vi.fn());
    release(new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]));
    await started;
    expect(FakeMediaRecorder.lastInstance!.stop).toHaveBeenCalledTimes(1);
  });

  it("waits for the final chunk commit before publishing finalized metadata", async () => {
    await loadOffscreenWithMocks(async () => new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]));
    vi.stubGlobal("Blob", NodeBlob);
    await createCompletion({ sessionId: "chunks", provider: "meet", meetingId: "meeting", capturedTabId: 7, status: "finalizing", updatedAt: 1 });
    await new Promise(resolve => registeredListener!({ type: "start-recording", sessionId: "chunks" }, {}, resolve));
    const recorder = FakeMediaRecorder.lastInstance!;
    recorder.ondataavailable!({ data: new NodeBlob(["first"]) });
    recorder.ondataavailable!({ data: new NodeBlob(["final"]) });
    await recorder.onstop!();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "recording-stopped", sessionId: "chunks", size: 10, mimeType: "video/webm;codecs=vp8,opus", durationSeconds: expect.any(Number) });
    expect(await getCompletion("chunks")).toMatchObject({ status: "upload_pending", meetingId: "meeting" });
  });

  it("persists a failed start and leaves its identity available", async () => {
    await loadOffscreenWithMocks(async () => { throw new Error("capture denied"); });
    await createCompletion({ sessionId: "failed", provider: "meet", meetingId: "meeting", capturedTabId: 7, status: "capturing", updatedAt: 1 });
    const reply = await new Promise(resolve => registeredListener!({ type: "start-recording", sessionId: "failed" }, {}, resolve));
    expect(reply).toEqual({ ok: false, reason: "failed" });
    expect(await getCompletion("failed")).toMatchObject({ captureError: true, meetingId: "meeting" });
  });

  it("screen_audio mode: requests video at the given resolution and uses a video mimeType", async () => {
    const tabStream = new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]);
    const getUserMedia = vi.fn(async (_constraints: unknown) => tabStream);
    await loadOffscreenWithMocks(getUserMedia);

    expect(registeredListener).toBeDefined();
    registeredListener!(
      {
        type: "start-recording",

        sessionId: "session-1",
        captureMode: "screen_audio",
        resolution: { width: 1280, height: 720 },
      },
      {},
      vi.fn()
    );

    // Allow the async startRecording body to run
    await new Promise((r) => setTimeout(r, 0));

    const constraints = getUserMedia.mock.calls[0][0] as any;
    expect(constraints.video).toBeTruthy();
    expect(constraints.video.width.max).toBe(1280);
    expect(constraints.video.height.max).toBe(720);
    expect(constraints).toMatchObject({ audio: { suppressLocalAudioPlayback: false }, video: { displaySurface: "browser" }, selfBrowserSurface: "include", preferCurrentTab: false, monitorTypeSurfaces: "exclude", surfaceSwitching: "include", systemAudio: "exclude" });

    expect(FakeMediaRecorder.lastInstance?.options.mimeType).toMatch(/^video\/webm/);
  });

  it("audio_only mode: picks a tab but excludes video from the recorded audio file", async () => {
    const tabStream = new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]);
    const getUserMedia = vi.fn(async (_constraints: unknown) => tabStream);
    await loadOffscreenWithMocks(getUserMedia);

    registeredListener!(
      {
        type: "start-recording",

        sessionId: "session-2",
        captureMode: "audio_only",
      },
      {},
      vi.fn()
    );
    await new Promise((r) => setTimeout(r, 0));

    const constraints = getUserMedia.mock.calls[0][0] as any;
    expect(constraints.video.displaySurface).toBe("browser");
    expect(FakeMediaRecorder.lastInstance?.stream.getVideoTracks()).toHaveLength(0);
    expect(FakeMediaRecorder.lastInstance?.stream.getAudioTracks()).toHaveLength(1);
    expect(tabStream.getVideoTracks()[0].stop).not.toHaveBeenCalled();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "capture-video-presence", videoPresence: "absent" });
    expect(FakeMediaRecorder.lastInstance?.options.mimeType).toMatch(/^audio\/webm/);
  });

  it.each(["screen_audio", "audio_only"])("%s with micDeviceId: mixes microphone audio with tab audio via AudioContext", async captureMode => {
    const tabStream = new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]);
    const micStream = new FakeMediaStream([new FakeTrack("audio")]);
    const getUserMedia = vi.fn(async (constraints: any) => {
      if (constraints.audio?.deviceId) return micStream;
      return tabStream;
    });
    await loadOffscreenWithMocks(getUserMedia);

    registeredListener!(
      {
        type: "start-recording",

        sessionId: "session-3",
        captureMode,
        resolution: { width: 1280, height: 720 },
        micDeviceId: "mic-device-1",
      },
      {},
      vi.fn()
    );
    await new Promise((r) => setTimeout(r, 0));

    // getUserMedia called twice: once for the tab, once for the mic
    expect(getUserMedia).toHaveBeenCalledTimes(2);
    const micCallConstraints = getUserMedia.mock.calls[1][0] as any;
    expect(micCallConstraints.audio.deviceId.exact).toBe("mic-device-1");
    const context = FakeAudioContext.lastInstance!;
    const destination = context.createMediaStreamDestination.mock.results[0].value;
    for (const source of context.createMediaStreamSource.mock.results) {
      expect(source.value.connect).toHaveBeenCalledTimes(1);
      expect(source.value.connect).toHaveBeenCalledWith(destination);
      expect(source.value.connect).not.toHaveBeenCalledWith(context.destination);
    }
    expect(FakeMediaRecorder.lastInstance?.stream.getAudioTracks()).toEqual(destination.stream.getAudioTracks());
    expect(FakeMediaRecorder.lastInstance?.stream.getVideoTracks()).toEqual(captureMode === "screen_audio" ? tabStream.getVideoTracks() : []);
  });

  it("without micDeviceId: only requests the tab stream", async () => {
    const tabStream = new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]);
    const getUserMedia = vi.fn(async () => tabStream);
    await loadOffscreenWithMocks(getUserMedia);

    registeredListener!(
      {
        type: "start-recording",

        sessionId: "session-4",
        captureMode: "screen_audio",
        resolution: { width: 1280, height: 720 },
      },
      {},
      vi.fn()
    );
    await new Promise((r) => setTimeout(r, 0));

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(FakeAudioContext.lastInstance).toBeNull();
  });
});

async function start(sessionId = "picker", extra = {}) {
  return new Promise(resolve => registeredListener!({ type: "start-recording", sessionId, ...extra }, {}, resolve));
}

describe("native sharing picker outcomes", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it.each(["NotAllowedError", "AbortError"])("%s cancels without creating or failing a session and allows retry", async name => {
    await loadOffscreenWithMocks(async () => { throw new DOMException("Picker dismissed", name); });
    expect(await start()).toEqual({ ok: false, reason: "cancelled" });
    expect(await getCompletion("picker")).toBeUndefined();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect(navigator.mediaDevices.getDisplayMedia).toHaveBeenCalledTimes(1);
    expect(await start()).toEqual({ ok: false, reason: "cancelled" });
  });

  it("stops every source track without requesting a microphone or binding a session when tab audio is missing", async () => {
    const video = new FakeTrack("video");
    await loadOffscreenWithMocks(async () => new FakeMediaStream([video]));
    expect(await start("silent", { micDeviceId: "mic" })).toEqual({ ok: false, reason: "no-tab-audio" });
    expect(video.stop).toHaveBeenCalledTimes(1);
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect(await getCompletion("silent")).toBeUndefined();
  });

  it("reports microphone permission separately from picker cancellation and releases the source", async () => {
    const video = new FakeTrack("video");
    const audio = new FakeTrack("audio");
    await loadOffscreenWithMocks(async () => new FakeMediaStream([audio, video]));
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValueOnce(new DOMException("Microphone denied", "NotAllowedError"));
    expect(await start("mic-denied", { micDeviceId: "mic" })).toEqual({ ok: false, reason: "microphone-permission" });
    expect(audio.stop).toHaveBeenCalledOnce();
    expect(video.stop).toHaveBeenCalledOnce();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect(await getCompletion("mic-denied")).toBeUndefined();
  });

  it("rejects a window even when Chrome ignores the picker hints and returns audio", async () => {
    const video = new FakeTrack("video");
    video.getSettings = () => ({ displaySurface: "window" });
    const audio = new FakeTrack("audio");
    await loadOffscreenWithMocks(async () => new FakeMediaStream([audio, video]));
    expect(await start()).toEqual({ ok: false, reason: "unsupported-surface" });
    expect(audio.stop).toHaveBeenCalled();
    expect(video.stop).toHaveBeenCalled();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });

  it("retries unsupported optional hints once, without suppressing playback", async () => {
    const pick = vi.fn().mockRejectedValueOnce(new TypeError("Unsupported option"))
      .mockResolvedValue(new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]));
    await loadOffscreenWithMocks(pick);
    expect(await start()).toEqual({ ok: true, sessionId: "picker", segmentStartedAt: expect.any(Number), micLabel: undefined });
    expect(pick).toHaveBeenCalledTimes(2);
    expect(pick.mock.calls[1][0]).toEqual({ video: { displaySurface: "browser", width: { max: 1280 }, height: { max: 720 } }, audio: true });
  });

  it.each(["screen_audio", "audio_only"])("%s source ended claims the durable close path, including while paused", async captureMode => {
    const video = new FakeTrack("video");
    await loadOffscreenWithMocks(async () => new FakeMediaStream([new FakeTrack("audio"), video]));
    await createCompletion({ sessionId: "ended", provider: "meet", meetingId: "meeting", capturedTabId: 7, status: "capturing", updatedAt: 1 });
    expect(await start("ended", { captureMode })).toEqual({ ok: true, sessionId: "ended", segmentStartedAt: expect.any(Number), micLabel: undefined });
    FakeMediaRecorder.lastInstance!.state = "paused";
    video.dispatchEvent(new Event("ended"));
    await vi.waitFor(() => expect(FakeMediaRecorder.lastInstance!.stop).toHaveBeenCalledTimes(1));
    expect(await getCompletion("ended")).toMatchObject({ status: "finalizing", trigger: "captured_tab_closed" });
    registeredListener!({ type: "stop-recording", sessionId: "ended" }, {}, vi.fn());
    expect(FakeMediaRecorder.lastInstance!.stop).toHaveBeenCalledTimes(1);
  });
});

describe("current-tab acquisition and playback", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it.each(["screen_audio", "audio_only"])("%s requests tab audio/video by stream ID and restores local playback", async captureMode => {
    const tab = new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]);
    await loadOffscreenWithMocks(async () => tab);
    expect(await start("direct", { source: "current-tab", streamId: "direct-stream", captureMode })).toEqual({ ok: true, sessionId: "direct", segmentStartedAt: expect.any(Number), micLabel: undefined });
    expect(navigator.mediaDevices.getDisplayMedia).not.toHaveBeenCalled();
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: "direct-stream" } },
      video: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: "direct-stream", maxWidth: 1280, maxHeight: 720 } },
    });
    const context = FakeAudioContext.lastInstance!;
    const source = context.createMediaStreamSource.mock.results[0].value;
    expect(source.connect).toHaveBeenCalledTimes(1);
    expect(source.connect).toHaveBeenCalledWith(context.destination);
    expect(FakeMediaRecorder.lastInstance?.stream.getVideoTracks()).toHaveLength(captureMode === "audio_only" ? 0 : 1);
    expect(FakeMediaRecorder.lastInstance?.stream.getAudioTracks()).toHaveLength(1);
  });

  it("mixes the mic into the file but loops back only tab audio", async () => {
    const tab = new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]);
    const mic = new FakeMediaStream([new FakeTrack("audio")]);
    await loadOffscreenWithMocks(async (constraints: any) => constraints.audio?.deviceId ? mic : tab);
    expect(await start("mixed-direct", { source: "current-tab", streamId: "stream", micDeviceId: "mic" })).toMatchObject({ ok: true });
    const context = FakeAudioContext.lastInstance!;
    const [tabSource, micSource] = context.createMediaStreamSource.mock.results.map(result => result.value);
    const destination = context.createMediaStreamDestination.mock.results[0].value;
    expect(tabSource.connect).toHaveBeenCalledTimes(2);
    expect(tabSource.connect).toHaveBeenCalledWith(context.destination);
    expect(tabSource.connect).toHaveBeenCalledWith(destination);
    expect(micSource.connect).toHaveBeenCalledTimes(1);
    expect(micSource.connect).toHaveBeenCalledWith(destination);
    expect(micSource.connect).not.toHaveBeenCalledWith(context.destination);
    expect(FakeMediaRecorder.lastInstance?.stream.getAudioTracks()).toEqual(destination.stream.getAudioTracks());
  });

  it("a denied direct stream is not treated as a silent picker cancellation", async () => {
    await loadOffscreenWithMocks(async () => { throw new DOMException("Permission denied", "NotAllowedError"); });
    expect(await start("denied-direct", { source: "current-tab", streamId: "stream" })).toEqual({ ok: false, reason: "current-tab-unavailable" });
    expect(await getCompletion("denied-direct")).toBeUndefined();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });
});

describe("recorded duration reported on stop", () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  async function recordWith(sessionId: string, script: (control: { advance: (ms: number) => void; send: (type: string) => unknown }) => void) {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(1_000_000);
    await loadOffscreenWithMocks(async () => new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]));
    vi.stubGlobal("Blob", NodeBlob);
    await createCompletion({ sessionId, provider: "meet", meetingId: "meeting", capturedTabId: 7, status: "finalizing", updatedAt: 1 });
    await start(sessionId);
    const recorder = FakeMediaRecorder.lastInstance!;
    recorder.ondataavailable!({ data: new NodeBlob(["media"]) });
    script({
      advance: ms => vi.setSystemTime(Date.now() + ms),
      send: type => { let reply: unknown; registeredListener!({ type, sessionId }, {}, r => { reply = r; }); return reply; },
    });
    await recorder.onstop!();
    const stopped = vi.mocked(chrome.runtime.sendMessage).mock.calls.map(([m]) => m as unknown as Record<string, unknown>).find(m => m.type === "recording-stopped");
    return stopped?.durationSeconds;
  }

  it("rounds an uninterrupted recording up to whole seconds", async () => {
    expect(await recordWith("plain", c => { c.advance(36_100); c.send("stop-recording"); })).toBe(37);
  });

  it("excludes paused time, including a pause that is still open at stop", async () => {
    expect(await recordWith("paused", c => {
      c.advance(10_000); c.send("pause-recording");
      c.advance(60_000); c.send("resume-recording");
      c.advance(5_500); c.send("pause-recording");
      c.advance(120_000); c.send("stop-recording");
    })).toBe(16);
  });

  it("does not count time between the stop request and the final chunk commit", async () => {
    expect(await recordWith("late-commit", c => { c.advance(8_000); c.send("stop-recording"); c.advance(30_000); })).toBe(8);
  });

  it.each([0, 1, 400])("reports at least one second for a %d ms recording", async ms => {
    expect(await recordWith(`short-${ms}`, c => { c.advance(ms); c.send("stop-recording"); })).toBe(1);
  });
});
