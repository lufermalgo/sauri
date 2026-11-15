// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { meeting as text } from "../../copy/meeting";
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

    const seek = screen.getByRole("slider", { name: text.seek });
    fireEvent.change(seek, { target: { value: "12000" } });
    expect(audio.currentTime).toBe(12);

    fireEvent.click(screen.getByRole("button", { name: text.pause }));
    expect(pause).toHaveBeenCalledWith();
    fireEvent.click(screen.getByRole("button", { name: text.resume }));
    await waitFor(() => expect(play).toHaveBeenCalled());

    fireEvent.change(screen.getByRole("combobox", { name: text.speed }), { target: { value: "1.5" } });
    expect(audio.playbackRate).toBe(1.5);
    fireEvent.change(screen.getByRole("slider", { name: text.volume }), { target: { value: "0.4" } });
    expect(audio.volume).toBe(0.4);
    fireEvent.click(screen.getByRole("button", { name: text.mute }));
    expect(audio.muted).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: text.playText("Synthetic middle passage") }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    expect(audio.currentTime).toBe(5);
  });

  it("keeps grouped transcript turns discoverable with 320 playback passages while preserving the raw passage list", () => {
    const longPassages: TimedPassage[] = Array.from({ length: 320 }, (_, index) => ({
      id: `synthetic-passage-${index + 1}`,
      text: `Synthetic passage ${index + 1}`,
      startMs: index * 1000,
      endMs: (index + 1) * 1000,
      sequence: index + 1,
      speakerLabel: `Speaker ${index % 2 === 0 ? "A" : "B"}`,
    }));
    render(
      <>
        <MeetingPlaybackView manifest={manifest()} passages={longPassages} loading={false} error={null} />
        <section aria-label="Grouped transcript">
          <ol>
            <li>Synthetic grouped turn A1</li>
            <li>Synthetic grouped turn B</li>
            <li>Synthetic grouped turn A2</li>
          </ol>
        </section>
      </>,
    );

    expect(screen.getByText("Synthetic grouped turn A1")).toBeVisible();
    expect(screen.getByText("Synthetic grouped turn B")).toBeVisible();
    expect(screen.getByText("Synthetic grouped turn A2")).toBeVisible();
    const disclosure = screen.getByText(text.passages(320)).closest("details");
    expect(disclosure).not.toHaveAttribute("open");

    fireEvent.click(screen.getByText(text.passages(320)));
    expect(disclosure).toHaveAttribute("open");
    const passageList = screen.getByRole("list", { name: text.transcriptPassages });
    expect(passageList.querySelectorAll("[data-passage-id]")).toHaveLength(320);
    expect(screen.getByText("Synthetic grouped turn A1")).toBeVisible();
  });

  it("keeps the active passage visible and highlighted while the long passage list is collapsed", async () => {
    const play = vi.fn().mockResolvedValue(undefined);
    HTMLMediaElement.prototype.play = play;
    const longPassages: TimedPassage[] = Array.from({ length: 320 }, (_, index) => ({
      id: `synthetic-passage-${index + 1}`,
      text: `Synthetic passage ${index + 1}`,
      startMs: index * 1000,
      endMs: (index + 1) * 1000,
      sequence: index + 1,
      speakerLabel: `Speaker ${index % 2 === 0 ? "A" : "B"}`,
    }));
    renderView({ passages: longPassages });

    const audio = mediaElement();
    Object.defineProperty(audio, "duration", { configurable: true, value: 320 });
    fireEvent.loadedMetadata(audio);
    const summary = screen.getByText(text.passages(320));
    fireEvent.click(summary);
    fireEvent.click(screen.getByRole("button", { name: text.playText("Synthetic passage 18") }));
    await waitFor(() => expect(play).toHaveBeenCalled());
    setMediaTime(audio, 17.5);
    fireEvent.click(summary);

    expect(summary.closest("details")).not.toHaveAttribute("open");
    const activePassage = screen.queryByTestId("active-playback-passage");
    expect(activePassage).not.toBeNull();
    expect(activePassage).toBeVisible();
    expect(activePassage).toHaveTextContent("Speaker B · 0:17 · Synthetic passage 18");
    expect(activePassage).toHaveClass("meeting-turn--active");

    setMediaTime(audio, 18.5);
    expect(activePassage).toHaveTextContent("Speaker A · 0:18 · Synthetic passage 19");
  });

  it("renders a colored speaker label on every playback transcript passage", () => {
    renderView({
      passages: passages.map((passage, index) => ({
        ...passage,
        speakerLabel: `Synthetic Speaker ${index + 1}`,
        speakerColor: index === 0 ? "#1d4ed8" : "#b45309",
      })),
    });

    const rows = screen.getByRole("list", { name: text.transcriptPassages }).querySelectorAll("li");
    expect(rows).toHaveLength(3);
    rows.forEach((row, index) => {
      const label = row.querySelector('[data-testid="transcript-speaker-label"]');
      expect(label?.textContent).toBe(`Synthetic Speaker ${index + 1}`);
      expect(label?.getAttribute("style")).toContain("color:");
    });
  });

  it("seeks the active highlight as playback advances and scrolls when the passage changes", () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    renderView();

    const audio = mediaElement();
    setMediaTime(audio, 2);
    expect(screen.getByText("Synthetic opening passage").closest("[data-passage-id]")).toHaveAttribute("data-active", "true");
    setMediaTime(audio, 6);
    const activePassage = screen.getByText("Synthetic middle passage").closest("[data-passage-id]");
    const inactivePassage = screen.getByText("Synthetic opening passage").closest("[data-passage-id]");
    expect(activePassage).toHaveAttribute("data-active", "true");
    expect(activePassage).toHaveClass("meeting-turn--active");
    expect(inactivePassage).not.toHaveClass("meeting-turn--active");
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
    expect(screen.queryByRole("combobox", { name: text.quality })).toBeNull();
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
      expect(screen.queryByRole("combobox", { name: text.quality })).toBeNull();
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
    const quality = screen.getByRole("combobox", { name: text.quality });
    fireEvent.change(quality, { target: { value: "high" } });
    expect(mediaElement("video").src).toBe(VIDEO_HIGH_URL);
    expect(audio.src).toBe(AUDIO_URL);
    expect(audio.currentTime).toBe(7.25);
    unmount();

    for (const video_sources of [[], [source("single", VIDEO_LOW_URL, 0)], [source("unknown-offset", VIDEO_LOW_URL, null)]]) {
      const view = renderView({ manifest: manifest({ video_presence: "separate", video_sources }) });
      expect(screen.queryByRole("combobox", { name: text.quality })).toBeNull();
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

    fireEvent.click(screen.getByRole("button", { name: text.resume }));
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
    expect(screen.getByText(text.emptyPlaybackTranscript)).toBeVisible();
    rerender(<MeetingPlaybackView manifest={manifest()} passages={passages} loading={false} error="synthetic load failure" />);
    expect(screen.getByRole("alert")).toBeVisible();

    for (const excluded of [/edit/i, /library/i, /notes/i, /summary/i, /metadata/i]) {
      expect(screen.queryByRole("button", { name: excluded })).toBeNull();
      expect(screen.queryByRole("link", { name: excluded })).toBeNull();
    }
  });
});


it("shows a localized load failure even when no manifest is available", () => {
  render(<MeetingPlaybackView manifest={null} passages={[]} loading={false} error="Synthetic network failure" />);
  expect(screen.getByRole("alert")).toHaveTextContent(text.playbackLoadFailed);
});
