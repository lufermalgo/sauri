import { describe, expect, it, vi } from "vitest";

import { findPassageAt, PlaybackController } from "../PlaybackController";
import type { TimedPassage } from "../PlaybackController";
import { createPlaybackIntervals, groupTranscriptTurns } from "../../transcript-turns";

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

describe("T17 derived source intervals", () => {
  it("retains two intervals for one presentation turn and no association in the gap", async () => {
    const sources = [
      { ...passage("a", 0, 100), sequence: 1 },
      { ...passage("b", 200, 300), sequence: 2 },
    ];
    const snapshot = structuredClone(sources);
    const turns = groupTranscriptTurns(sources, new Map([["a", "speaker-a"], ["b", "speaker-a"]]));
    const intervals = createPlaybackIntervals(sources, turns);
    expect(turns).toHaveLength(1);
    expect(intervals.map(({ id, startMs, endMs, presentationTurnId }) => ({ id, startMs, endMs, presentationTurnId }))).toEqual([
      { id: "a", startMs: 0, endMs: 100, presentationTurnId: "a" },
      { id: "b", startMs: 200, endMs: 300, presentationTurnId: "a" },
    ]);
    expect(findPassageAt(intervals, 50)?.id).toBe("a");
    expect(findPassageAt(intervals, 150)).toBeNull();
    expect(findPassageAt(intervals, 250)?.id).toBe("b");
    const audio = mediaElement();
    const controller = new PlaybackController({ videoPresence: "absent", audioElement: audio, passages: intervals });
    for (const [seconds, expected] of [[0.05, "a"], [0.15, null], [0.25, "b"], [0.3, null]] as const) {
      audio.currentTime = seconds;
      audio.emit("timeupdate");
      expect(controller.getState().activePassageId).toBe(expected);
    }
    await controller.playPassage(intervals[0]!);
    expect(audio.currentTime).toBe(0);
    expect(sources).toEqual(snapshot);
    controller.destroy();
  });

  it("keeps overlapping source order and excludes invalid timing without inventing text", () => {
    const sources = [
      { ...passage("a", 0, 100), sequence: 1 },
      { ...passage("b", 50, 300), sequence: 2, text: "" },
      { ...passage("invalid", 400, 200), sequence: 3 },
      { id: "untimed", startMs: null, endMs: null, sequence: 4, text: "Synthetic untimed" },
    ];
    const intervals = createPlaybackIntervals(sources, groupTranscriptTurns(sources, new Map(sources.map(({ id }) => [id, "speaker-a"]))));
    expect(intervals.map(({ id, startMs, endMs, text }) => ({ id, startMs, endMs, text }))).toEqual([
      { id: "a", startMs: 0, endMs: 100, text: "Synthetic passage a" },
      { id: "b", startMs: 50, endMs: 300, text: "" },
    ]);
    expect(findPassageAt(intervals, 75)?.id).toBe("a");
    expect(findPassageAt(intervals, 150)?.id).toBe("b");
    expect(findPassageAt(intervals, 400)).toBeNull();
  });
});

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

  it("keeps playback paused and reports a rejected play request", async () => {
    const audio = mediaElement();
    const onError = vi.fn();
    audio.play = vi.fn().mockRejectedValue(new Error("synthetic playback failure"));
    const controller = new PlaybackController({
      videoPresence: "absent",
      audioElement: audio,
      passages,
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
    const muxed = new PlaybackController({ videoPresence: "muxed", audioElement: muxedAudio, passages });
    expect(muxed.getState().isPlaying).toBe(false);

    muxedAudio.currentTime = 7.25;
    muxedAudio.emit("timeupdate");
    expect(muxed.getState().currentTimeMs).toBe(7250);
    muxed.seekTo(8500);
    expect(muxedAudio.currentTime).toBe(8.5);

    for (const videoPresence of ["absent", "unknown"] as const) {
      const audio = mediaElement();
      const controller = new PlaybackController({ videoPresence, audioElement: audio, passages });
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
      passages,
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
      passages,
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
      passages,
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
      passages,
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
