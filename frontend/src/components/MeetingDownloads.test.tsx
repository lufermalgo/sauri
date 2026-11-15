// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PlaybackManifest } from "../api";
import { MeetingDownloads } from "./MeetingDownloads";
import { meeting as text } from "../copy/meeting";

const audio = { source_id: "a", url: "http://localhost/synthetic.wav", mime_type: "audio/wav" };
const video = { source_id: "v", url: "http://localhost/synthetic.webm", mime_type: "video/webm" };
const manifest: PlaybackManifest = {
  meeting_id: "m1", duration_seconds: 10, video_presence: "muxed", audio_source: audio,
  muxed_video_source: video, video_sources: [],
};
const turns = [{ timestampMs: 65000, speakerLabel: "Synthetic speaker", text: "Synthetic text" }];

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("MeetingDownloads", () => {
  it("disables both downloads without a manifest or turns", () => {
    render(<MeetingDownloads meetingId="m1" manifest={null} turns={[]} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadVideo })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("menuitem", { name: text.downloadTranscript })).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it.each(["muxed", "separate", "absent", "unknown"] as const)("links the primary source for %s media", mode => {
    render(<MeetingDownloads meetingId="m1" manifest={{ ...manifest, video_presence: mode, video_sources: [video] }} turns={turns} />);
    const audioOnly = mode === "absent" || mode === "unknown";
    let link: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { link = this; });
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadTranscript })).not.toHaveAttribute("aria-disabled");
    fireEvent.click(screen.getByRole("menuitem", { name: audioOnly ? text.downloadAudio : text.downloadVideo }));
    expect(link).toHaveAttribute("href", audioOnly ? audio.url : video.url);
    expect(link).toHaveAttribute("download");
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadTranscript })).not.toHaveAttribute("aria-disabled");
  });

  it("keeps media disabled when the primary source is unavailable", () => {
    render(<MeetingDownloads meetingId="m1" manifest={{ ...manifest, muxed_video_source: null }} turns={turns} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadVideo })).toHaveAttribute("aria-disabled", "true");
  });

  it("downloads the actual text export with a filename and releases the object URL", async () => {
    const create = vi.fn((_blob: Blob) => "blob:synthetic");
    const revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: revoke });
    let clicked: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked = this; });
    render(<MeetingDownloads meetingId="m1" manifest={manifest} turns={turns} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadTranscript }));
    const blob = create.mock.calls[0][0];
    expect(blob.type).toBe("text/plain;charset=utf-8");
    const content = await new Promise<string>(resolve => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(content).toBe("[01:05] Synthetic speaker: Synthetic text");
    expect(clicked).toHaveAttribute("download", text.transcriptFilename("m1"));
    expect(clicked).toHaveAttribute("href", "blob:synthetic");
    expect(document.querySelector('a[href="blob:synthetic"]')).not.toBeInTheDocument();
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:synthetic"));
  });

  it("reports an export failure without disabling retry", () => {
    vi.stubGlobal("URL", { createObjectURL: () => { throw new Error("Synthetic failure"); } });
    render(<MeetingDownloads meetingId="m1" manifest={manifest} turns={turns} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadTranscript }));
    expect(screen.getByRole("alert")).toHaveTextContent(text.downloadFailed);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadTranscript })).not.toHaveAttribute("aria-disabled");
  });
});
