// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import type { PlaybackManifest, PlaybackSource } from "./api";
import { downloadMeetingMedia, pickMediaSource } from "./media-download";

const src = (url: string, mime: string | null): PlaybackSource => ({ source_id: url, url, mime_type: mime });
const audio = src("http://store.test/a.m4a?sig=1", "audio/mp4");
const video = src("http://store.test/v.webm?sig=1", "video/webm");
const manifest = (overrides: Partial<PlaybackManifest> = {}): PlaybackManifest => ({
  meeting_id: "m1", duration_seconds: 10, video_presence: "muxed", audio_source: audio,
  muxed_video_source: video, video_sources: [], ...overrides,
});

afterEach(() => { vi.restoreAllMocks(); });

describe("pickMediaSource", () => {
  it("takes the muxed video for muxed media", () => {
    expect(pickMediaSource(manifest())).toEqual({ source: video, audioOnly: false });
  });

  it("takes the first video source when audio and video are separate", () => {
    const other = src("http://store.test/v2.mp4", "video/mp4");
    expect(pickMediaSource(manifest({ video_presence: "separate", muxed_video_source: null, video_sources: [other, video] })))
      .toEqual({ source: other, audioOnly: false });
  });

  it.each(["absent", "unknown"] as const)("takes the audio for %s video", (presence) => {
    expect(pickMediaSource(manifest({ video_presence: presence }))).toEqual({ source: audio, audioOnly: true });
  });

  it("has nothing to offer without a manifest or a usable source", () => {
    expect(pickMediaSource(null)).toBeNull();
    expect(pickMediaSource(manifest({ muxed_video_source: null }))).toBeNull();
    expect(pickMediaSource(manifest({ video_presence: "separate", video_sources: [] }))).toBeNull();
    expect(pickMediaSource(manifest({ video_presence: "absent", audio_source: src("", "audio/mp4") }))).toBeNull();
  });
});

describe("downloadMeetingMedia", () => {
  function clickedAnchors() {
    const clicked: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked.push(this); });
    return clicked;
  }

  it("asks the API for a fresh download link and follows it in the same tab", async () => {
    const get = vi.spyOn(api, "getMediaDownloadLink").mockResolvedValue({
      url: "http://store.test/v.webm?sig=1&response-content-disposition=attachment", filename: "Weekly sync.webm", expires_in_seconds: 300,
    });
    const clicked = clickedAnchors();
    await downloadMeetingMedia("m1");
    expect(get).toHaveBeenCalledWith("m1");
    expect(clicked).toHaveLength(1);
    expect(clicked[0]).toHaveAttribute("href", "http://store.test/v.webm?sig=1&response-content-disposition=attachment");
    // The server's Content-Disposition names the file; the page neither opens a tab nor reads the body.
    expect(clicked[0]).not.toHaveAttribute("target");
    expect(document.body.querySelector("a")).toBeNull();
  });

  it("rejects, and follows nothing, when the API refuses the link", async () => {
    vi.spyOn(api, "getMediaDownloadLink").mockRejectedValue(new Error("Error 404"));
    const clicked = clickedAnchors();
    await expect(downloadMeetingMedia("m1")).rejects.toThrow("Error 404");
    expect(clicked).toHaveLength(0);
  });
});
