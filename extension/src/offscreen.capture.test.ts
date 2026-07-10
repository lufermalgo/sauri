/**
 * Tests de la capa de captura del documento offscreen (offscreen.ts).
 *
 * Feature: meeting-capture-transcription
 * Task: 14.8 — Validates: Requirements 2.1, 2.2
 *
 * Cubre: composición A/V según modo de captura, mimeType seleccionado,
 * y mezcla de audio de micrófono con el audio de la pestaña.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

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
  start = vi.fn();
  stop = vi.fn();
}

async function loadOffscreenWithMocks(getUserMediaImpl: (constraints: unknown) => Promise<FakeMediaStream>) {
  vi.resetModules();
  registeredListener = undefined;

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

describe("Documento offscreen — composición A/V y captura", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("modo screen_audio: solicita video con la resolución dada y usa mimeType de video", async () => {
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

  it("modo audio_only: no solicita video y usa mimeType de audio", async () => {
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

  it("con micDeviceId: mezcla el audio del micrófono con el de la pestaña vía AudioContext", async () => {
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

  it("sin micDeviceId: solo solicita el stream de la pestaña", async () => {
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
