import { describe, expect, it, vi } from "vitest";

import { PlaybackController } from "../PlaybackController";

function mediaElement() {
  const listeners = new Map<string, Array<() => void>>();
  const media = {
    currentTime: 0,
    duration: 30,
    paused: true,
    playbackRate: 1,
    volume: 1,
    muted: false,
    src: "",
    play: vi.fn(async function (this: { paused: boolean }) {
      this.paused = false;
    }),
    pause: vi.fn(function (this: { paused: boolean }) {
      this.paused = true;
    }),
    addEventListener: vi.fn((name: string, listener: () => void) => {
      listeners.set(name, [...(listeners.get(name) ?? []), listener]);
    }),
    removeEventListener: vi.fn(),
    emit(name: string) {
      for (const listener of listeners.get(name) ?? []) listener();
    },
  };
  return media as unknown as HTMLMediaElement & { emit(name: string): void };
}

describe("PlaybackController state and controls", () => {
  it("seeks, pauses, resumes, and reflects rate, volume, and mute state", async () => {
    const audio = mediaElement();
    const controller = new PlaybackController({
      videoPresence: "absent",
      audioElement: audio,
    });

    controller.seekTo(1200);
    expect(audio.currentTime).toBe(1.2);
    await controller.resume();
    expect(audio.play).toHaveBeenCalledOnce();
    expect(controller.getState().isPlaying).toBe(true);
    controller.pause();
    expect(audio.pause).toHaveBeenCalledOnce();
    expect(controller.getState().isPlaying).toBe(false);

    controller.setPlaybackRate(1.5);
    controller.setVolume(0.4);
    controller.setMuted(true);
    expect(audio.playbackRate).toBe(1.5);
    expect(audio.volume).toBe(0.4);
    expect(audio.muted).toBe(true);
    expect(controller.getState()).toMatchObject({ playbackRate: 1.5, volume: 0.4, muted: true });
  });

  it("plays an interval from its start and pauses when the clock reaches its end", async () => {
    const audio = mediaElement();
    const controller = new PlaybackController({ videoPresence: "absent", audioElement: audio });

    await controller.playInterval(2000, 5500);
    expect(audio.currentTime).toBe(2);
    expect(audio.play).toHaveBeenCalledOnce();
    audio.currentTime = 5.499;
    audio.emit("timeupdate");
    expect(audio.pause).not.toHaveBeenCalled();
    audio.currentTime = 5.5;
    audio.emit("timeupdate");
    expect(audio.pause).toHaveBeenCalledOnce();
    expect(controller.getState().isPlaying).toBe(false);

    await controller.resume();
    audio.currentTime = 9;
    audio.emit("timeupdate");
    expect(audio.pause).toHaveBeenCalledOnce();
  });

  it("cancels the interval on a manual seek", async () => {
    const audio = mediaElement();
    const controller = new PlaybackController({ videoPresence: "absent", audioElement: audio });

    await controller.playInterval(1000, 3000);
    controller.seekTo(7000);
    audio.currentTime = 8;
    audio.emit("timeupdate");
    expect(audio.pause).not.toHaveBeenCalled();
  });

  it("replaces a previous interval with a new one", async () => {
    const audio = mediaElement();
    const controller = new PlaybackController({ videoPresence: "absent", audioElement: audio });

    await controller.playInterval(1000, 3000);
    await controller.playInterval(10000, 12000);
    expect(audio.currentTime).toBe(10);
    audio.currentTime = 11;
    audio.emit("timeupdate");
    expect(audio.pause).not.toHaveBeenCalled();
    audio.currentTime = 12;
    audio.emit("seeked");
    expect(audio.pause).toHaveBeenCalledOnce();
  });

  it("ignores an empty or invalid interval", async () => {
    const audio = mediaElement();
    const controller = new PlaybackController({ videoPresence: "absent", audioElement: audio });

    await controller.playInterval(3000, 3000);
    await controller.playInterval(-1, 2000);
    await controller.playInterval(Number.NaN, 2000);
    expect(audio.play).not.toHaveBeenCalled();
  });

  it("reports the authoritative audio clock in its state as playback advances", () => {
    const audio = mediaElement();
    const controller = new PlaybackController({ videoPresence: "absent", audioElement: audio });

    audio.currentTime = 0.5;
    audio.emit("timeupdate");
    expect(controller.getState().currentTimeMs).toBe(500);
    audio.currentTime = 1.5;
    audio.emit("timeupdate");
    expect(controller.getState().currentTimeMs).toBe(1500);
  });

  it("keeps playback paused and reports a rejected play request", async () => {
    const audio = mediaElement();
    const onError = vi.fn();
    audio.play = vi.fn().mockRejectedValue(new Error("synthetic playback failure"));
    const controller = new PlaybackController({
      videoPresence: "absent",
      audioElement: audio,
      onError,
    });

    await controller.resume();

    expect(audio.pause).toHaveBeenCalled();
    expect(controller.getState().isPlaying).toBe(false);
    expect(onError).toHaveBeenCalledOnce();
  });
});

describe("PlaybackController media modes and synchronization", () => {
  it("uses one element and its clock for muxed playback, and audio only for absent or unknown video", () => {
    const muxedAudio = mediaElement();
    const muxed = new PlaybackController({ videoPresence: "muxed", audioElement: muxedAudio });
    expect(muxed.getState().isPlaying).toBe(false);

    muxedAudio.currentTime = 7.25;
    muxedAudio.emit("timeupdate");
    expect(muxed.getState().currentTimeMs).toBe(7250);
    muxed.seekTo(8500);
    expect(muxedAudio.currentTime).toBe(8.5);

    for (const videoPresence of ["absent", "unknown"] as const) {
      const audio = mediaElement();
      const controller = new PlaybackController({ videoPresence, audioElement: audio });
      expect(controller.getState().selectedSourceId).toBeNull();
      controller.seekTo(500);
      expect(audio.currentTime).toBe(0.5);
    }
  });

  it("does not pair or offer separate video when its offset is missing", async () => {
    const audio = mediaElement();
    const video = mediaElement();
    const controller = new PlaybackController({
      videoPresence: "separate",
      audioElement: audio,
      videoElement: video,
    });

    expect(controller.getState().selectedSourceId).toBeNull();
    audio.currentTime = 2;
    audio.emit("timeupdate");
    controller.seekTo(500);
    await controller.resume();
    expect(video.currentTime).toBe(0);
    expect(video.play).not.toHaveBeenCalled();
  });

  it("changes only the video source and preserves the audio position", () => {
    const audio = mediaElement();
    const video = mediaElement();
    audio.src = "signed-audio-url";
    audio.currentTime = 12.5;
    const controller = new PlaybackController({
      videoPresence: "separate",
      audioElement: audio,
      videoElement: video,
      mediaSources: [
        { id: "low", label: "Low", videoSrc: "video-low", audioSrc: "ignored-audio", mimeType: "video/webm", videoOffsetMs: -250 },
        { id: "high", label: "High", videoSrc: "video-high", audioSrc: "ignored-audio", mimeType: "video/webm", videoOffsetMs: -250 },
      ],
    });

    controller.selectSource("high");

    expect(video.src).toBe("video-high");
    expect(audio.src).toBe("signed-audio-url");
    expect(audio.currentTime).toBe(12.5);
    expect(controller.getState().selectedSourceId).toBe("high");
    expect(video.muted).toBe(true);
  });

  it("pauses both elements and reports a paired startup failure", async () => {
    const audio = mediaElement();
    const video = mediaElement();
    const onError = vi.fn();
    video.play = vi.fn().mockRejectedValue(new Error("synthetic video failure"));
    const controller = new PlaybackController({
      videoPresence: "separate",
      audioElement: audio,
      videoElement: video,
      videoOffsetMs: -100,
      onError,
    });

    await controller.resume();

    expect(audio.pause).toHaveBeenCalled();
    expect(video.pause).toHaveBeenCalled();
    expect(controller.getState().isPlaying).toBe(false);
    expect(onError).toHaveBeenCalledOnce();
  });

  it("does not pair or offer separate video when its offset is null", async () => {
    const audio = mediaElement();
    const video = mediaElement();
    const controller = new PlaybackController({
      videoPresence: "separate",
      audioElement: audio,
      videoElement: video,
      videoOffsetMs: null,
    });

    expect(controller.getState().selectedSourceId).toBeNull();
    audio.currentTime = 2;
    audio.emit("timeupdate");
    controller.seekTo(500);
    await controller.resume();
    expect(video.currentTime).toBe(0);
    expect(video.play).not.toHaveBeenCalled();
  });

  it("aligns paired video with signed offsets and waits for positive offsets", async () => {
    const audio = mediaElement();
    const video = mediaElement();
    const controller = new PlaybackController({
      videoPresence: "separate",
      audioElement: audio,
      videoElement: video,
      videoOffsetMs: 2000,
    });

    audio.currentTime = 1;
    audio.emit("timeupdate");
    expect(video.currentTime).toBe(0);
    expect(video.paused).toBe(true);
    audio.currentTime = 3;
    audio.emit("timeupdate");
    expect(video.currentTime).toBe(1);

    audio.currentTime = 4;
    video.currentTime = 0;
    audio.emit("timeupdate");
    expect(video.currentTime).toBe(2);
    expect(video.playbackRate).toBe(audio.playbackRate);
    await controller.resume();
    expect(audio.play).toHaveBeenCalledOnce();
    expect(video.play).toHaveBeenCalledOnce();
  });

  it("aligns negative offsets and corrects only drift above 250 ms", () => {
    const audio = mediaElement();
    const video = mediaElement();
    const controller = new PlaybackController({
      videoPresence: "separate",
      audioElement: audio,
      videoElement: video,
      videoOffsetMs: -500,
    });

    audio.currentTime = 2;
    video.currentTime = 2.25;
    audio.emit("timeupdate");
    expect(video.currentTime).toBe(2.25);
    audio.currentTime = 3;
    video.currentTime = 3.249;
    audio.emit("timeupdate");
    expect(video.currentTime).toBe(3.5);
    expect(controller.getState().currentTimeMs).toBe(3000);
  });
});
