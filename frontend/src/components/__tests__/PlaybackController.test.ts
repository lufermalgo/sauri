import { describe, expect, it, vi } from "vitest";

import { findPassageAt, PlaybackController } from "../PlaybackController";
import type { TimedPassage } from "../PlaybackController";

function passage(id: string, startMs: number, endMs: number): TimedPassage {
  return { id, startMs, endMs, text: `Synthetic passage ${id}` };
}

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

const passages = [passage("first", 0, 1000), passage("second", 1000, 2000)];

describe("findPassageAt", () => {
  it("matches valid half-open intervals, including adjacent boundaries", () => {
    expect(findPassageAt(passages, 0)?.id).toBe("first");
    expect(findPassageAt(passages, 999)?.id).toBe("first");
    expect(findPassageAt(passages, 1000)?.id).toBe("second");
    expect(findPassageAt(passages, 2000)).toBeNull();
  });

  it("returns the first matching passage in supplied order when intervals overlap", () => {
    const overlapping = [passage("later-start", 500, 1500), passage("earlier-start", 0, 1000)];

    expect(findPassageAt(overlapping, 750)?.id).toBe("later-start");
    expect(overlapping.map(({ id }) => id)).toEqual(["later-start", "earlier-start"]);
  });

  it("returns no passage for gaps, empty input, or invalid intervals", () => {
    expect(findPassageAt([passage("before", 0, 100), passage("after", 200, 300)], 150)).toBeNull();
    expect(findPassageAt([], 0)).toBeNull();
    expect(
      findPassageAt(
        [passage("zero", 100, 100), passage("reversed", 200, 100), passage("nan", Number.NaN, 300)],
        150,
      ),
    ).toBeNull();
  });
});

describe("PlaybackController state and controls", () => {
  it("seeks, pauses, resumes, and reflects rate, volume, and mute state", async () => {
    const audio = mediaElement();
    const controller = new PlaybackController({
      videoPresence: "absent",
      audioElement: audio,
      passages,
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

  it("updates active passage from the authoritative audio clock and clears it on a gap", () => {
    const audio = mediaElement();
    const controller = new PlaybackController({ videoPresence: "absent", audioElement: audio, passages });

    audio.currentTime = 0.5;
    audio.emit("timeupdate");
    expect(controller.getState().activePassageId).toBe("first");
    audio.currentTime = 1.5;
    audio.emit("timeupdate");
    expect(controller.getState().activePassageId).toBe("second");
    audio.currentTime = 3;
    audio.emit("timeupdate");
    expect(controller.getState().activePassageId).toBeNull();
  });
});

describe("PlaybackController media modes and synchronization", () => {
  it("uses one element for muxed playback and audio only for absent or unknown video", () => {
    const muxedAudio = mediaElement();
    const muxed = new PlaybackController({ videoPresence: "muxed", audioElement: muxedAudio, passages });
    expect(muxed.getState().isPlaying).toBe(false);

    for (const videoPresence of ["absent", "unknown"] as const) {
      const audio = mediaElement();
      const controller = new PlaybackController({ videoPresence, audioElement: audio, passages });
      expect(controller.getState().selectedSourceId).toBeNull();
      controller.seekTo(500);
      expect(audio.currentTime).toBe(0.5);
    }
  });

  it("aligns paired video with signed offsets and waits for positive offsets", async () => {
    const audio = mediaElement();
    const video = mediaElement();
    const controller = new PlaybackController({
      videoPresence: "separate",
      audioElement: audio,
      videoElement: video,
      passages,
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
      passages,
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
