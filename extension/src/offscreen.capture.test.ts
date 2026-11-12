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

class FakeTrack {
  constructor(public kind: "audio" | "video") {}
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
      sendMessage: vi.fn(),
    },
  });
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi.fn(getUserMediaImpl),
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
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ignores unbound/foreign stops and stops the same recorder only once", async () => {
    await loadOffscreenWithMocks(async () => new FakeMediaStream([new FakeTrack("audio")]));
    await new Promise(resolve => registeredListener!({ type: "start-recording", streamId: "stream", sessionId: "active" }, {}, resolve));
    const recorder = FakeMediaRecorder.lastInstance!;
    registeredListener!({ type: "stop-recording", sessionId: "other" }, {}, vi.fn());
    registeredListener!({ type: "stop-recording" }, {}, vi.fn());
    expect(recorder.stop).not.toHaveBeenCalled();
    registeredListener!({ type: "stop-recording", sessionId: "active" }, {}, vi.fn());
    registeredListener!({ type: "stop-recording", sessionId: "active" }, {}, vi.fn());
    expect(recorder.stop).toHaveBeenCalledTimes(1);
  });

  it("keeps stop intent while getUserMedia is still starting", async () => {
    let release!: (stream: FakeMediaStream) => void;
    await loadOffscreenWithMocks(() => new Promise(resolve => { release = resolve; }));
    const started = new Promise(resolve => registeredListener!({ type: "start-recording", streamId: "stream", sessionId: "starting" }, {}, resolve));
    registeredListener!({ type: "stop-recording", sessionId: "starting" }, {}, vi.fn());
    release(new FakeMediaStream([new FakeTrack("audio")]));
    await started;
    expect(FakeMediaRecorder.lastInstance!.stop).toHaveBeenCalledTimes(1);
  });

  it("waits for the final chunk commit before publishing finalized metadata", async () => {
    await loadOffscreenWithMocks(async () => new FakeMediaStream([new FakeTrack("audio")]));
    vi.stubGlobal("Blob", NodeBlob);
    await createCompletion({ sessionId: "chunks", provider: "meet", meetingId: "meeting", capturedTabId: 7, status: "finalizing", updatedAt: 1 });
    await new Promise(resolve => registeredListener!({ type: "start-recording", streamId: "stream", sessionId: "chunks" }, {}, resolve));
    const recorder = FakeMediaRecorder.lastInstance!;
    recorder.ondataavailable!({ data: new NodeBlob(["first"]) });
    recorder.ondataavailable!({ data: new NodeBlob(["final"]) });
    await recorder.onstop!();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "recording-stopped", sessionId: "chunks", size: 10, mimeType: "video/webm;codecs=vp8,opus" });
    expect(await getCompletion("chunks")).toMatchObject({ status: "upload_pending", meetingId: "meeting" });
  });

  it("persists a failed start and leaves its identity available", async () => {
    await loadOffscreenWithMocks(async () => { throw new Error("capture denied"); });
    await createCompletion({ sessionId: "failed", provider: "meet", meetingId: "meeting", capturedTabId: 7, status: "capturing", updatedAt: 1 });
    const reply = await new Promise(resolve => registeredListener!({ type: "start-recording", streamId: "stream", sessionId: "failed" }, {}, resolve));
    expect(reply).toEqual({ ok: false, sessionId: "failed" });
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
        streamId: "stream-1",
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
    expect(constraints.video.mandatory.maxWidth).toBe(1280);
    expect(constraints.video.mandatory.maxHeight).toBe(720);

    expect(FakeMediaRecorder.lastInstance?.options.mimeType).toMatch(/^video\/webm/);
  });

  it("audio_only mode: does not request video and uses an audio mimeType", async () => {
    const tabStream = new FakeMediaStream([new FakeTrack("audio")]);
    const getUserMedia = vi.fn(async (_constraints: unknown) => tabStream);
    await loadOffscreenWithMocks(getUserMedia);

    registeredListener!(
      {
        type: "start-recording",
        streamId: "stream-2",
        sessionId: "session-2",
        captureMode: "audio_only",
      },
      {},
      vi.fn()
    );
    await new Promise((r) => setTimeout(r, 0));

    const constraints = getUserMedia.mock.calls[0][0] as any;
    expect(constraints.video).toBe(false);
    expect(FakeMediaRecorder.lastInstance?.options.mimeType).toMatch(/^audio\/webm/);
  });

  it("with micDeviceId: mixes microphone audio with tab audio via AudioContext", async () => {
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
        streamId: "stream-3",
        sessionId: "session-3",
        captureMode: "screen_audio",
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
  });

  it("without micDeviceId: only requests the tab stream", async () => {
    const tabStream = new FakeMediaStream([new FakeTrack("audio"), new FakeTrack("video")]);
    const getUserMedia = vi.fn(async () => tabStream);
    await loadOffscreenWithMocks(getUserMedia);

    registeredListener!(
      {
        type: "start-recording",
        streamId: "stream-4",
        sessionId: "session-4",
        captureMode: "screen_audio",
        resolution: { width: 1280, height: 720 },
      },
      {},
      vi.fn()
    );
    await new Promise((r) => setTimeout(r, 0));

    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });
});
