// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PlaybackManifest, TimedPassage } from "../../api";
import { MeetingPlaybackView } from "../MeetingPlaybackView";

const AUDIO_URL = "https://media.example.test/synthetic-audio.webm?signature=synthetic";
const MUXED_URL = "https://media.example.test/synthetic-muxed.webm?signature=synthetic";
const VIDEO_LOW_URL = "https://media.example.test/synthetic-video-low.webm?signature=synthetic";
const VIDEO_HIGH_URL = "https://media.example.test/synthetic-video-high.webm?signature=synthetic";

function manifest(overrides: Partial<PlaybackManifest> = {}): PlaybackManifest {
  return {
    meeting_id: "meeting-synthetic-1",
    duration_seconds: 30,
    video_presence: "absent",
    audio_source: { source_id: "audio-synthetic", url: AUDIO_URL, mime_type: "audio/webm" },
    muxed_video_source: null,
    video_sources: [],
    ...overrides,
  };
}

function source(source_id: string, url: string, video_offset_ms: number | null = 0) {
  return {
    source_id,
    url,
    mime_type: "video/webm",
    quality_label: source_id,
    width: 640,
    height: 360,
    video_offset_ms,
  };
}

const passages: TimedPassage[] = [
  { id: "p-1", text: "Synthetic opening passage", startMs: 0, endMs: 5000, sequence: 1 },
  { id: "p-2", text: "Synthetic middle passage", startMs: 5000, endMs: 10000, sequence: 2 },
  { id: "p-3", text: "Synthetic closing passage", startMs: null, endMs: null, sequence: 3 },
];

function renderView(overrides: Partial<{
  manifest: PlaybackManifest;
  passages: TimedPassage[];
  loading: boolean;
  error: string | null;
  onRefreshManifest: (currentTimeMs: number) => Promise<PlaybackManifest>;
}> = {}) {
  return render(
    <MeetingPlaybackView
      manifest={"manifest" in overrides ? overrides.manifest ?? null : manifest()}
      passages={overrides.passages ?? passages}
      loading={overrides.loading ?? false}
      error={overrides.error ?? null}
      onRefreshManifest={overrides.onRefreshManifest}
    />,
  );
}

function mediaElement(kind: "audio" | "video" = "audio"): HTMLMediaElement {
  return screen.getByTestId(kind === "audio" ? "playback-audio" : "playback-video") as HTMLMediaElement;
}

function setMediaTime(media: HTMLMediaElement, seconds: number) {
  Object.defineProperty(media, "currentTime", { configurable: true, writable: true, value: seconds });
  fireEvent.timeUpdate(media);
}

const originalPlay = HTMLMediaElement.prototype.play;
const originalPause = HTMLMediaElement.prototype.pause;

afterEach(() => {
  cleanup();
  HTMLMediaElement.prototype.play = originalPlay;
  HTMLMediaElement.prototype.pause = originalPause;
});

describe("MeetingPlaybackView", () => {
  it("provides seek, pause/resume, speed, volume, mute and passage play controls", async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();
    HTMLMediaElement.prototype.play = play;
    HTMLMediaElement.prototype.pause = pause;
    renderView();

    const audio = mediaElement();
    Object.defineProperty(audio, "duration", { configurable: true, value: 30 });
    fireEvent.loadedMetadata(audio);

    const seek = screen.getByRole("slider", { name: /seek/i });
    fireEvent.change(seek, { target: { value: "12000" } });
    expect(audio.currentTime).toBe(12);

    fireEvent.click(screen.getByRole("button", { name: /pause/i }));
    expect(pause).toHaveBeenCalledWith();
    fireEvent.click(screen.getByRole("button", { name: /^play or resume playback$/i }));
    await waitFor(() => expect(play).toHaveBeenCalled());

    fireEvent.change(screen.getByRole("combobox", { name: /playback speed/i }), { target: { value: "1.5" } });
    expect(audio.playbackRate).toBe(1.5);
    fireEvent.change(screen.getByRole("slider", { name: /volume/i }), { target: { value: "0.4" } });
    expect(audio.volume).toBe(0.4);
    fireEvent.click(screen.getByRole("button", { name: /mute/i }));
    expect(audio.muted).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /play.*synthetic middle passage/i }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(audio.currentTime).toBe(5);
  });

  it("seeks the active highlight as playback advances and scrolls when the passage changes", () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    renderView();

    const audio = mediaElement();
    setMediaTime(audio, 2);
    expect(screen.getByText("Synthetic opening passage").closest("[data-passage-id]")).toHaveAttribute("data-active", "true");
    setMediaTime(audio, 6);
    expect(screen.getByText("Synthetic middle passage").closest("[data-passage-id]")).toHaveAttribute("data-active", "true");
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("uses one native video clock only for explicit muxed evidence", () => {
    renderView({
      manifest: manifest({
        video_presence: "muxed",
        audio_source: { source_id: "muxed-audio", url: MUXED_URL, mime_type: null },
        muxed_video_source: { source_id: "muxed-video", url: MUXED_URL, mime_type: null },
        video_sources: [source("not-a-rendition", VIDEO_HIGH_URL)],
      }),
    });

    const video = screen.getByTestId("playback-media") as HTMLVideoElement;
    expect(video.src).toBe(MUXED_URL);
    expect(screen.queryByTestId("playback-audio")).toBeNull();
    expect(screen.queryByTestId("playback-video")).toBeNull();
    expect(screen.queryByRole("combobox", { name: /quality|resolution/i })).toBeNull();
  });

  it("keeps absent and every unknown legacy manifest audio-only, independent of MIME or video rows", () => {
    for (const legacy of [
      manifest({ video_presence: "absent", audio_source: { source_id: "a", url: MUXED_URL, mime_type: "video/webm" }, muxed_video_source: { source_id: "v", url: MUXED_URL, mime_type: "video/webm" }, video_sources: [source("v1", VIDEO_LOW_URL)] }),
      manifest({ video_presence: "unknown", audio_source: { source_id: "a", url: MUXED_URL, mime_type: null }, muxed_video_source: { source_id: "v", url: MUXED_URL, mime_type: "video/webm" }, video_sources: [] }),
      manifest({ video_presence: "unknown", audio_source: { source_id: "a", url: AUDIO_URL, mime_type: "audio/webm" }, muxed_video_source: null, video_sources: [source("legacy-video-no-offset", VIDEO_LOW_URL, null)] }),
    ]) {
      const { unmount } = renderView({ manifest: legacy });
      expect(mediaElement("audio").src).toBe(legacy.audio_source.url);
      expect(screen.queryByTestId("playback-media")).toBeNull();
      expect(screen.queryByTestId("playback-video")).toBeNull();
      expect(screen.queryByRole("combobox", { name: /quality|resolution/i })).toBeNull();
      unmount();
    }
  });

  it("pairs authoritative audio with muted, offset-qualified video only in separate mode", () => {
    renderView({ manifest: manifest({
      video_presence: "separate",
      video_sources: [source("low", VIDEO_LOW_URL, 1500)],
    }) });

    const audio = mediaElement("audio");
    const video = mediaElement("video");
    expect(audio.src).toBe(AUDIO_URL);
    expect(video.src).toBe(VIDEO_LOW_URL);
    expect(video.muted).toBe(true);
    setMediaTime(audio, 3);
    expect(video.currentTime).toBeCloseTo(1.5);
  });

  it("aligns signed positive and negative offsets and pauses video until a positive offset", () => {
    const positiveView = renderView({ manifest: manifest({
      video_presence: "separate",
      video_sources: [source("offset", VIDEO_LOW_URL, 1500)],
    }) });
    const audio = mediaElement("audio");
    const video = mediaElement("video");

    setMediaTime(audio, 1);
    expect(video.currentTime).toBe(0);
    expect(video.paused).toBe(true);
    setMediaTime(audio, 2);
    expect(video.currentTime).toBeCloseTo(0.5);
    positiveView.unmount();

    const negativeView = renderView({ manifest: manifest({
      video_presence: "separate",
      video_sources: [source("negative-offset", VIDEO_HIGH_URL, -500)],
    }) });
    const negativeAudio = mediaElement("audio");
    setMediaTime(negativeAudio, 1);
    expect(mediaElement("video").currentTime).toBeCloseTo(1.5);
    negativeView.unmount();
  });

  it("offers source selection only for multiple playable separate videos and preserves audio position/source", () => {
    const { unmount } = renderView({ manifest: manifest({
      video_presence: "separate",
      video_sources: [source("low", VIDEO_LOW_URL, 0), source("high", VIDEO_HIGH_URL, -500)],
    }) });
    const audio = mediaElement("audio");
    Object.defineProperty(audio, "currentTime", { configurable: true, writable: true, value: 7.25 });
    fireEvent.loadedMetadata(audio);
    const quality = screen.getByRole("combobox", { name: /quality|resolution/i });
    fireEvent.change(quality, { target: { value: "high" } });
    expect(mediaElement("video").src).toBe(VIDEO_HIGH_URL);
    expect(audio.src).toBe(AUDIO_URL);
    expect(audio.currentTime).toBe(7.25);
    unmount();

    for (const video_sources of [[], [source("single", VIDEO_LOW_URL, 0)], [source("unknown-offset", VIDEO_LOW_URL, null)]]) {
      const view = renderView({ manifest: manifest({ video_presence: "separate", video_sources }) });
      expect(screen.queryByRole("combobox", { name: /quality|resolution/i })).toBeNull();
      view.unmount();
    }
  });

  it("keeps controls disabled while media metadata or duration is unavailable", () => {
    renderView({ loading: true });
    expect(screen.getByRole("status")).toBeVisible();
    const controls = [
      ...screen.getAllByRole("slider"),
      ...screen.queryAllByRole("combobox"),
      ...screen.getAllByRole("button"),
    ];
    expect(controls.length).toBeGreaterThan(0);
    for (const control of controls) expect(control).toBeDisabled();
  });

  it("refreshes an expired signed source once at the saved position and stops after the renewed source fails", async () => {
    const onRefreshManifest = vi.fn().mockResolvedValue(
      manifest({ audio_source: { source_id: "renewed", url: "https://media.example.test/renewed", mime_type: "audio/webm" } }),
    );
    renderView({ onRefreshManifest });
    const audio = mediaElement();
    setMediaTime(audio, 8.75);
    fireEvent.error(audio);
    await waitFor(() => expect(onRefreshManifest).toHaveBeenCalledWith(8750));
    expect(audio.currentTime).toBe(8.75);
    fireEvent.error(audio);
    await waitFor(() => expect(screen.getByRole("alert")).toBeVisible());
    expect(onRefreshManifest).toHaveBeenCalledTimes(1);
    expect(audio.paused).toBe(true);
  });

  it("pauses both tracks and exposes an accessible error if either paired track fails to start", async () => {
    const play = vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("synthetic video start failure"));
    const pause = vi.fn();
    HTMLMediaElement.prototype.play = play;
    HTMLMediaElement.prototype.pause = pause;
    renderView({ manifest: manifest({ video_presence: "separate", video_sources: [source("paired", VIDEO_LOW_URL, 0)] }) });
    const audio = mediaElement();
    Object.defineProperty(audio, "duration", { configurable: true, value: 30 });
    fireEvent.loadedMetadata(audio);

    fireEvent.click(screen.getByRole("button", { name: /^play or resume playback$/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeVisible());
    expect(play).toHaveBeenCalledTimes(2);
    expect(pause).toHaveBeenCalledTimes(2);
    expect(mediaElement("audio").paused).toBe(true);
    expect(mediaElement("video").paused).toBe(true);
  });

  it("renders accessible unavailable, empty, and error states without out-of-scope controls", () => {
    const { rerender } = renderView({ manifest: null as unknown as PlaybackManifest, passages: [] });
    expect(screen.getByRole("status")).toBeVisible();
    rerender(<MeetingPlaybackView manifest={manifest()} passages={[]} loading={false} error={null} />);
    expect(screen.getByText(/no transcript|empty transcript/i)).toBeVisible();
    rerender(<MeetingPlaybackView manifest={manifest()} passages={passages} loading={false} error="synthetic load failure" />);
    expect(screen.getByRole("alert")).toBeVisible();

    for (const excluded of [/edit/i, /library/i, /notes/i, /summary/i, /metadata/i]) {
      expect(screen.queryByRole("button", { name: excluded })).toBeNull();
      expect(screen.queryByRole("link", { name: excluded })).toBeNull();
    }
  });
});
