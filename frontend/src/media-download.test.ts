// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { meeting as text } from "./copy/meeting";
import type { PlaybackManifest, PlaybackSource } from "./api";
import {
  NoMediaError, downloadMeetingMedia, mediaExtension, mediaFilename, pickMediaSource, saveSignedMedia,
} from "./media-download";

const src = (url: string, mime: string | null): PlaybackSource => ({ source_id: url, url, mime_type: mime });
const audio = src("http://store.test/a.m4a?sig=1", "audio/mp4");
const video = src("http://store.test/v.webm?sig=1", "video/webm");
const manifest = (overrides: Partial<PlaybackManifest> = {}): PlaybackManifest => ({
  meeting_id: "m1", duration_seconds: 10, video_presence: "muxed", audio_source: audio,
  muxed_video_source: video, video_sources: [], ...overrides,
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, "showSaveFilePicker");
});

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

describe("mediaExtension and mediaFilename", () => {
  it.each([
    ["video/webm", "webm"], ["video/mp4", "mp4"], ["audio/mp4", "m4a"], ["audio/mpeg", "mp3"],
    ["audio/wav", "wav"], ["audio/ogg", "ogg"], ["VIDEO/WEBM; codecs=vp9", "webm"],
  ])("maps %s to .%s", (mime, extension) => {
    expect(mediaExtension(src("http://store.test/x", mime))).toBe(extension);
  });

  it("falls back to the extension in the link, then to a generic one", () => {
    expect(mediaExtension(src("http://store.test/path/file.MKV?sig=1", null))).toBe("mkv");
    expect(mediaExtension(src("http://store.test/path/file", "application/octet-stream"))).toBe("bin");
    expect(mediaExtension(src("not a url", null))).toBe("bin");
  });

  it("names the file after the title and falls back to the id", () => {
    expect(mediaFilename("m1", "Weekly sync", video)).toBe("Weekly sync.webm");
    expect(mediaFilename("m1", "recording.webm", video)).toBe("recording.webm");
    expect(mediaFilename("m1", "???", audio)).toBe(text.mediaFilename("m1", "m4a"));
    expect(mediaFilename("m1", null, video)).toBe(text.mediaFilename("m1", "webm"));
  });
});

function bodyOf(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  return new Response(stream, { status: 200, headers: { "content-length": String(length) } });
}

function stubPicker(picker: ((options: { suggestedName: string }) => Promise<unknown>) | undefined) {
  Object.defineProperty(window, "showSaveFilePicker", { value: picker, configurable: true, writable: true });
}

function anchors() {
  const clicked: HTMLAnchorElement[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked.push(this); });
  return clicked;
}

function collector() {
  const received: string[] = [];
  const decoder = new TextDecoder();
  const writable = new WritableStream<Uint8Array>({ write(chunk) { received.push(decoder.decode(chunk)); } });
  return { received, handle: { createWritable: async () => writable } };
}

describe("saveSignedMedia", () => {
  it("streams the response into the file the user picked, reporting progress", async () => {
    const { received, handle } = collector();
    const picker = vi.fn().mockResolvedValue(handle);
    stubPicker(picker);
    const fetchMock = vi.fn().mockResolvedValue(bodyOf(["aaaa", "bbbb", "cccc", "dddd"]));
    vi.stubGlobal("fetch", fetchMock);
    const progress: Array<number | null> = [];

    const outcome = await saveSignedMedia(video.url, "Weekly sync.webm", (percent) => progress.push(percent));

    expect(outcome).toBe("saved");
    expect(fetchMock).toHaveBeenCalledWith(video.url);
    expect(picker).toHaveBeenCalledWith({ suggestedName: "Weekly sync.webm" });
    expect(received.join("")).toBe("aaaabbbbccccdddd");
    expect(progress).toEqual([0, 25, 50, 75, 100]);
  });

  it("reports an unknown size as null instead of a made-up percentage", async () => {
    const { handle } = collector();
    stubPicker(vi.fn().mockResolvedValue(handle));
    const response = bodyOf(["abc"]);
    response.headers.delete("content-length");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const progress: Array<number | null> = [];
    await saveSignedMedia(video.url, "x.webm", (percent) => progress.push(percent));
    expect(progress).toEqual([null]);
  });

  it("writes nothing and stays quiet when the user closes the file picker", async () => {
    stubPicker(vi.fn().mockRejectedValue(new DOMException("closed", "AbortError")));
    const response = bodyOf(["abc"]);
    const cancel = vi.spyOn(response.body as ReadableStream, "cancel");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const clicked = anchors();
    expect(await saveSignedMedia(video.url, "x.webm")).toBe("cancelled");
    expect(cancel).toHaveBeenCalled();
    expect(clicked).toHaveLength(0);
  });

  it("opens the link in a tab when the picker cannot open (no user gesture left)", async () => {
    stubPicker(vi.fn().mockRejectedValue(new DOMException("needs a gesture", "SecurityError")));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(bodyOf(["abc"])));
    const clicked = anchors();
    expect(await saveSignedMedia(video.url, "x.webm")).toBe("opened");
    expect(clicked[0]).toHaveAttribute("href", video.url);
    expect(clicked[0]).toHaveAttribute("target", "_blank");
  });

  it.each([
    ["the object store refuses the portal origin", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["the signed link was rejected", () => Promise.resolve(new Response("denied", { status: 403 }))],
  ])("falls back to the link without creating a file when %s", async (_name, respond) => {
    const picker = vi.fn();
    stubPicker(picker);
    vi.stubGlobal("fetch", vi.fn(respond));
    const clicked = anchors();
    expect(await saveSignedMedia(video.url, "Weekly sync.webm")).toBe("opened");
    expect(picker).not.toHaveBeenCalled();
    expect(clicked[0]).toHaveAttribute("href", video.url);
    expect(clicked[0]).toHaveAttribute("download", "Weekly sync.webm");
    expect(clicked[0]).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("opens the link in a tab, without fetching it, in a browser with no file picker", async () => {
    stubPicker(undefined);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const clicked = anchors();
    expect(await saveSignedMedia(video.url, "x.webm")).toBe("opened");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(clicked).toHaveLength(1);
  });

  it("rejects when the transfer breaks halfway, so the caller can report it", async () => {
    const failing = new Response(new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new Uint8Array([1])); controller.error(new Error("connection lost")); },
    }));
    stubPicker(vi.fn().mockResolvedValue({ createWritable: async () => new WritableStream<Uint8Array>() }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(failing));
    await expect(saveSignedMedia(video.url, "x.webm")).rejects.toThrow("connection lost");
  });
});

describe("downloadMeetingMedia", () => {
  it("asks for a fresh manifest and saves the chosen source under the title", async () => {
    const get = vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(manifest());
    stubPicker(undefined);
    const clicked = anchors();
    expect(await downloadMeetingMedia("m1", "Weekly sync")).toBe("opened");
    expect(get).toHaveBeenCalledWith("m1");
    expect(clicked[0]).toHaveAttribute("href", video.url);
    expect(clicked[0]).toHaveAttribute("download", "Weekly sync.webm");
  });

  it("rejects with NoMediaError when the manifest has no usable source", async () => {
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(manifest({ muxed_video_source: null }));
    await expect(downloadMeetingMedia("m1", "Weekly sync")).rejects.toBeInstanceOf(NoMediaError);
  });
});
