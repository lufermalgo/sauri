// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PlaybackManifest } from "../../api";
import { MeetingPlaybackView } from "../MeetingPlaybackView";
import { t } from "../../i18n";

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

function renderView(overrides: Partial<{
  manifest: PlaybackManifest;
  loading: boolean;
  error: string | null;
  onRefreshManifest: (currentTimeMs: number) => Promise<PlaybackManifest>;
}> = {}) {
  return render(
    <MeetingPlaybackView
      manifest={"manifest" in overrides ? overrides.manifest ?? null : manifest()}
      loading={overrides.loading ?? false}
      error={overrides.error ?? null}
      onRefreshManifest={overrides.onRefreshManifest}
    />,
  );
}

function mediaElement(kind: "audio" | "video" = "audio"): HTMLMediaElement {
  return screen.getByTestId(kind === "audio" ? "playback-audio" : "playback-video") as HTMLMediaElement;
}

/** jsdom never plays: mark the element as playing or paused and fire the matching event. */
function setPlaying(media: HTMLMediaElement, playing: boolean) {
  Object.defineProperty(media, "paused", { configurable: true, value: !playing });
  fireEvent(media, new Event(playing ? "play" : "pause"));
}

function muxedManifest() {
  return manifest({
    video_presence: "muxed",
    audio_source: { source_id: "muxed-audio", url: MUXED_URL, mime_type: null },
    muxed_video_source: { source_id: "muxed-video", url: MUXED_URL, mime_type: null },
  });
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
  it("provides seek, pause/resume, speed, volume and mute controls", async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();
    HTMLMediaElement.prototype.play = play;
    HTMLMediaElement.prototype.pause = pause;
    renderView();

    const audio = mediaElement();
    Object.defineProperty(audio, "duration", { configurable: true, value: 30 });
    fireEvent.loadedMetadata(audio);

    const seek = screen.getByRole("slider", { name: t("meeting:seek") });
    fireEvent.change(seek, { target: { value: "12000" } });
    expect(audio.currentTime).toBe(12);

    fireEvent.click(screen.getByRole("button", { name: t("meeting:play") }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    setPlaying(audio, true);
    fireEvent.click(screen.getByRole("button", { name: t("meeting:pause") }));
    expect(pause).toHaveBeenCalledWith();

    fireEvent.change(screen.getByRole("combobox", { name: t("meeting:speed") }), { target: { value: "1.5" } });
    expect(audio.playbackRate).toBe(1.5);
    fireEvent.change(screen.getByRole("slider", { name: t("meeting:volume") }), { target: { value: "0.4" } });
    expect(audio.volume).toBe(0.4);
    fireEvent.click(screen.getByRole("button", { name: t("meeting:mute") }));
    expect(audio.muted).toBe(true);
  });

  it("does not render a playback fragments disclosure or any transcript list under the player", () => {
    const { container } = renderView();

    expect(container.querySelector("details, summary, ol, li")).toBeNull();
    expect(screen.queryByTestId("transcript-speaker-label")).toBeNull();
    expect(screen.queryByTestId("active-playback-passage")).toBeNull();
    const audio = mediaElement();
    setMediaTime(audio, 6);
    expect(container.querySelector("[data-passage-id], .meeting-active-preview")).toBeNull();
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
    expect(screen.queryByRole("combobox", { name: t("meeting:quality") })).toBeNull();
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
      expect(screen.queryByRole("combobox", { name: t("meeting:quality") })).toBeNull();
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
    const quality = screen.getByRole("combobox", { name: t("meeting:quality") });
    fireEvent.change(quality, { target: { value: "high" } });
    expect(mediaElement("video").src).toBe(VIDEO_HIGH_URL);
    expect(audio.src).toBe(AUDIO_URL);
    expect(audio.currentTime).toBe(7.25);
    unmount();

    for (const video_sources of [[], [source("single", VIDEO_LOW_URL, 0)], [source("unknown-offset", VIDEO_LOW_URL, null)]]) {
      const view = renderView({ manifest: manifest({ video_presence: "separate", video_sources }) });
      expect(screen.queryByRole("combobox", { name: t("meeting:quality") })).toBeNull();
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
    for (const control of controls) {
      if (control.classList.contains("meeting-timeline-slider")) {
        expect(control).toHaveAttribute("aria-disabled", "true");
        expect(control).toHaveAttribute("tabindex", "-1");
      } else expect(control).toBeDisabled();
    }
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

    fireEvent.click(screen.getByRole("button", { name: t("meeting:play") }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeVisible());
    expect(play).toHaveBeenCalledTimes(2);
    expect(pause).toHaveBeenCalledTimes(2);
    expect(mediaElement("audio").paused).toBe(true);
    expect(mediaElement("video").paused).toBe(true);
  });

  it("renders accessible unavailable and error states without out-of-scope controls", () => {
    const { rerender } = renderView({ manifest: null as unknown as PlaybackManifest });
    expect(screen.getByRole("status")).toBeVisible();
    rerender(<MeetingPlaybackView manifest={manifest()} loading={false} error="synthetic load failure" />);
    expect(screen.getByRole("alert")).toBeVisible();

    for (const excluded of [/edit/i, /library/i, /notes/i, /summary/i, /metadata/i]) {
      expect(screen.queryByRole("button", { name: excluded })).toBeNull();
      expect(screen.queryByRole("link", { name: excluded })).toBeNull();
    }
  });
});

it("shows a localized load failure even when no manifest is available", () => {
  render(<MeetingPlaybackView manifest={null} loading={false} error="Synthetic network failure" />);
  expect(screen.getByRole("alert")).toHaveTextContent(t("meeting:playbackLoadFailed"));
});

it("keeps exactly the existing controls together in one compact toolbar", () => {
  Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
  renderView({ manifest: manifest({ video_presence: "separate", video_sources: [source("low", VIDEO_LOW_URL), source("high", VIDEO_HIGH_URL)] }) });
  const toolbar = document.querySelector(".meeting-player-controls") as HTMLElement;
  expect(within(toolbar).getAllByRole("button").map(button => button.getAttribute("aria-label")))
    .toEqual([t("meeting:play"), t("meeting:mute"), t("meeting:fullscreen")]);
  expect(within(toolbar).getAllByRole("slider").map(slider => slider.getAttribute("aria-label")))
    .toEqual([t("meeting:seek"), t("meeting:volume")]);
  expect(within(toolbar).getAllByRole("combobox").map(select => select.getAttribute("aria-label")))
    .toEqual([t("meeting:speed"), t("meeting:quality")]);
  // The manifest's duration shows before the media reports one (a browser-recorded WebM never does).
  expect(toolbar.querySelector(".meeting-control-time")).toHaveTextContent("0:00 / 0:30");
});

it("seeks timeline markers through the original playback controller and tracks its clock", async () => {
  render(<MeetingPlaybackView manifest={manifest()} loading={false} error={null}
    timelineTurns={[{ id: "t1", startMs: 0, endMs: 15000, speakerId: "s1", speakerLabel: "Synthetic speaker", color: "var(--ds-speaker-1)" }]}
    keyPointTimes={[5000, 10000]} />);
  const audio = mediaElement();
  Object.defineProperty(audio, "duration", { configurable: true, value: 30 });
  fireEvent.loadedMetadata(audio);
  fireEvent.click(screen.getByRole("button", { name: t("meeting:keyPointAt", { time: "00:05" }) }));
  expect(audio.currentTime).toBe(5);
  fireEvent.seeked(audio);
  const timeline = screen.getByRole("slider", { name: t("meeting:timeline") });
  expect(timeline).toHaveAttribute("aria-valuenow", "5000");
  fireEvent.keyDown(timeline, { key: "ArrowRight" });
  expect(audio.currentTime).toBe(10);
  fireEvent.timeUpdate(audio);
  expect(timeline).toHaveAttribute("aria-valuenow", "10000");
});

describe("playback controls", () => {
  afterEach(() => {
    Reflect.deleteProperty(document, "fullscreenEnabled");
    Reflect.deleteProperty(document, "fullscreenElement");
    Reflect.deleteProperty(HTMLElement.prototype, "requestFullscreen");
    Reflect.deleteProperty(document, "exitFullscreen");
  });

  it("enables play, pause and seek for a browser-recorded WebM whose duration is infinite", async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    HTMLMediaElement.prototype.play = play;
    renderView();
    const audio = mediaElement();
    Object.defineProperty(audio, "duration", { configurable: true, value: Infinity });
    fireEvent.loadedMetadata(audio);

    const toggle = screen.getByRole("button", { name: t("meeting:play") });
    expect(toggle).toBeEnabled();
    const seek = screen.getByRole("slider", { name: t("meeting:seek") });
    expect(seek).toBeEnabled();
    expect(seek).toHaveAttribute("max", "30000");
    expect(document.querySelector(".meeting-control-time")).toHaveTextContent("0:00 / 0:30");
    fireEvent.change(seek, { target: { value: "20000" } });
    expect(audio.currentTime).toBe(20);
    fireEvent.click(toggle);
    await waitFor(() => expect(play).toHaveBeenCalled());
  });

  it("pauses playback that a transcript turn started", async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();
    HTMLMediaElement.prototype.play = play;
    HTMLMediaElement.prototype.pause = pause;
    let seekTo: ((timeMs: number, play?: boolean) => void) | undefined;
    render(<MeetingPlaybackView manifest={manifest()} loading={false} error={null}
      onSeekToReady={registered => { seekTo = registered; }} />);
    const audio = mediaElement();
    Object.defineProperty(audio, "duration", { configurable: true, value: Infinity });
    fireEvent.loadedMetadata(audio);

    seekTo?.(12000, true);
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(audio.currentTime).toBe(12);
    setPlaying(audio, true);
    fireEvent.click(screen.getByRole("button", { name: t("meeting:pause") }));
    expect(pause).toHaveBeenCalled();
    setPlaying(audio, false);
    expect(screen.getByRole("button", { name: t("meeting:play") })).toBeEnabled();
  });

  it("plays and pauses when the picture is clicked", async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();
    HTMLMediaElement.prototype.play = play;
    HTMLMediaElement.prototype.pause = pause;
    renderView({ manifest: muxedManifest() });
    const video = screen.getByTestId("playback-media") as HTMLVideoElement;
    fireEvent.loadedMetadata(video);

    fireEvent.click(video);
    await waitFor(() => expect(play).toHaveBeenCalled());
    setPlaying(video, true);
    fireEvent.click(video);
    expect(pause).toHaveBeenCalled();
  });

  it("puts the picture, its controls and the timeline in full screen and leaves it again", async () => {
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    let stage: HTMLElement | null = null;
    const requestFullscreen = vi.fn(function (this: HTMLElement) {
      stage = this;
      Object.defineProperty(document, "fullscreenElement", { configurable: true, value: this });
      document.dispatchEvent(new Event("fullscreenchange"));
      return Promise.resolve();
    });
    const exitFullscreen = vi.fn(() => {
      Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
      document.dispatchEvent(new Event("fullscreenchange"));
      return Promise.resolve();
    });
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", { configurable: true, value: requestFullscreen });
    Object.defineProperty(document, "exitFullscreen", { configurable: true, value: exitFullscreen });
    renderView({ manifest: muxedManifest() });
    const video = screen.getByTestId("playback-media") as HTMLVideoElement;
    fireEvent.loadedMetadata(video);

    fireEvent.click(screen.getByRole("button", { name: t("meeting:fullscreen") }));
    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    expect(stage).toContainElement(video);
    expect(stage).toContainElement(document.querySelector(".meeting-player-controls") as HTMLElement);
    expect(stage).toContainElement(document.querySelector(".meeting-timeline") as HTMLElement);
    const exit = await screen.findByRole("button", { name: t("meeting:exitFullscreen") });
    fireEvent.click(exit);
    expect(exitFullscreen).toHaveBeenCalled();
    expect(await screen.findByRole("button", { name: t("meeting:fullscreen") })).toBeVisible();
  });

  it("offers no full screen for an audio-only recording", () => {
    Object.defineProperty(document, "fullscreenEnabled", { configurable: true, value: true });
    renderView();
    fireEvent.loadedMetadata(mediaElement());
    expect(screen.queryByRole("button", { name: t("meeting:fullscreen") })).toBeNull();
  });
});
