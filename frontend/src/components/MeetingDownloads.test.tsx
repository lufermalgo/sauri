// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as api from "../api";
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

function readBlob(blob: Blob): Promise<string> {
  return new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("MeetingDownloads", () => {
  it("is an icon-only button named and described by the download label", () => {
    render(<MeetingDownloads meetingId="m1" manifest={manifest} turns={turns} />);
    const trigger = screen.getByRole("button", { name: text.download });
    expect(trigger).toHaveTextContent("");
    expect(trigger.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(trigger).toHaveAccessibleDescription(text.download);
  });

  it("disables every download without a manifest, turns or summary", () => {
    render(<MeetingDownloads meetingId="m1" manifest={null} turns={[]} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadVideo })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("menuitem", { name: text.downloadTranscript })).toHaveAttribute("aria-disabled", "true");
    const summaryItem = screen.getByRole("menuitem", { name: text.downloadSummary });
    expect(summaryItem).toHaveAttribute("aria-disabled", "true");
    expect(summaryItem).toHaveAttribute("title", text.summaryUnavailable);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("offers the summary after the media and the transcript, enabled once a summary exists", () => {
    render(<MeetingDownloads meetingId="m1" manifest={manifest} turns={turns} hasSummary />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    const items = screen.getAllByRole("menuitem");
    expect(items.map(item => item.textContent)).toEqual([text.downloadVideo, text.downloadTranscript, text.downloadSummary]);
    expect(items[2]).not.toHaveAttribute("aria-disabled");
    expect(items[2]).not.toHaveAttribute("title");
  });

  it("downloads the summary as <title> - resumen.txt", async () => {
    vi.spyOn(api, "getMeetingSummary").mockResolvedValue({
      summaryId: "s", meetingId: "m1", templateId: "t", templateName: "General", templateVersion: 1,
      topic: "Synthetic topic", schemaVersion: 1, keyPoints: ["Synthetic point"], conclusion: null,
      reviewState: "draft", generation: 1, createdAt: "2026-11-14T12:00:00Z", updatedAt: "2026-11-14T12:00:00Z",
    });
    const blobs: Blob[] = [];
    vi.stubGlobal("URL", { createObjectURL: (blob: Blob) => { blobs.push(blob); return "blob:synthetic"; }, revokeObjectURL: vi.fn() });
    let clicked: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked = this; });
    render(<MeetingDownloads meetingId="m1" title="Weekly sync" manifest={manifest} turns={turns} hasSummary />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadSummary }));
    await waitFor(() => expect(clicked).toBeDefined());
    expect(clicked).toHaveAttribute("download", "Weekly sync - resumen.txt");
    expect(await readBlob(blobs[0])).toBe("Synthetic topic\n- Synthetic point");
  });

  it("reports a summary that vanished instead of saving an empty file", async () => {
    vi.spyOn(api, "getMeetingSummary").mockResolvedValue(null);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<MeetingDownloads meetingId="m1" manifest={manifest} turns={turns} hasSummary />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadSummary }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.downloadFailed);
    expect(click).not.toHaveBeenCalled();
  });

  it.each(["muxed", "separate", "absent", "unknown"] as const)("opens the primary source of a fresh manifest for %s media", async mode => {
    const fresh = { ...manifest, video_presence: mode, video_sources: [video] };
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(fresh);
    render(<MeetingDownloads meetingId="m1" title="Weekly sync" manifest={fresh} turns={turns} />);
    const audioOnly = mode === "absent" || mode === "unknown";
    let link: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { link = this; });
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadTranscript })).not.toHaveAttribute("aria-disabled");
    fireEvent.click(screen.getByRole("menuitem", { name: audioOnly ? text.downloadAudio : text.downloadVideo }));
    await waitFor(() => expect(link).toBeDefined());
    // Without a file picker the signed link opens in a tab; the file name still follows the title.
    expect(link).toHaveAttribute("href", audioOnly ? audio.url : video.url);
    expect(link).toHaveAttribute("download", audioOnly ? "Weekly sync.wav" : "Weekly sync.webm");
    expect(link).toHaveAttribute("target", "_blank");
    expect(await screen.findByRole("status")).toHaveTextContent(text.mediaOpened);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    expect(screen.getByRole("menuitem", { name: text.downloadTranscript })).not.toHaveAttribute("aria-disabled");
  });

  it("shows an error when the manifest cannot be fetched", async () => {
    vi.spyOn(api, "getPlaybackManifest").mockRejectedValue(new Error("Error 500"));
    render(<MeetingDownloads meetingId="m1" manifest={manifest} turns={turns} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadVideo }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.downloadFailed);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
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

  async function transcriptDownloadName(title: string | null | undefined) {
    const revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: () => "blob:synthetic", revokeObjectURL: revoke });
    let clicked: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked = this; });
    const view = render(<MeetingDownloads meetingId="m1" title={title} manifest={manifest} turns={turns} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadTranscript }));
    await waitFor(() => expect(revoke).toHaveBeenCalled());
    return { name: clicked?.getAttribute("download"), view };
  }

  it("names the transcript after the meeting title", async () => {
    expect((await transcriptDownloadName("Caf\u00e9 planning a\u00f1o")).name).toBe("Caf\u00e9 planning a\u00f1o.txt");
  });

  it("drops the media extension of an uploaded recording title", async () => {
    expect((await transcriptDownloadName("recording.webm")).name).toBe("recording.txt");
  });

  it("uses the renamed title for the next download", async () => {
    const { name, view } = await transcriptDownloadName("Old title");
    expect(name).toBe("Old title.txt");
    let clicked: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked = this; });
    view.rerender(<MeetingDownloads meetingId="m1" title="Renamed title" manifest={manifest} turns={turns} />);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadTranscript }));
    expect(clicked).toHaveAttribute("download", "Renamed title.txt");
  });

  it.each([null, undefined, "", "  ", "???"])("falls back to the id-based name for the title %j", async title => {
    expect((await transcriptDownloadName(title)).name).toBe(text.transcriptFilename("m1"));
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
