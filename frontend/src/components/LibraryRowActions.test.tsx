// @vitest-environment jsdom
/**
 * Library rows: the summary shows as a tooltip, and the "..." menu renames, downloads (transcript, summary,
video) and deletes.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, waitFor, fireEvent, act, within } from "@testing-library/react";
import { MeetingOrigin, ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";

import { RecordingLibrary } from "./RecordingLibrary";
import { LIBRARY_CHANGED_EVENT } from "../library-events";
import * as api from "../api";
import { copy } from "../copy/es";
import { meeting as meetingText } from "../copy/meeting";
import { summaryPlainText } from "../summary-export";

const text = copy.library;

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function item(id: string, title: string, overrides: Partial<MeetingListItem> = {}): MeetingListItem {
  return {
    id, meetLink: null, origin: MeetingOrigin.Manual, processState: ProcessState.Completed, failureCause: null,
    createdAt: "2026-10-28T17:45:00Z", title, durationSeconds: 600, speakerCount: 2, summaryTopic: null,
    thumbnailUrl: null, mediaKind: "video", ...overrides,
  };
}

async function renderList(items: MeetingListItem[], props: { selectedId?: string; onSelectMeeting?: () => void } = {}) {
  const list = vi.spyOn(api, "listMeetings").mockResolvedValue(items);
  const onSelectMeeting = props.onSelectMeeting ?? vi.fn();
  const view = render(<RecordingLibrary refreshKey={0} selectedId={props.selectedId} onSelectMeeting={onSelectMeeting} />);
  await screen.findByRole("search");
  return { list, onSelectMeeting, view };
}

function open(title: string): HTMLElement {
  const match = screen.getAllByRole("button").find((button) =>
    button.classList.contains("library-item") && button.querySelector(".library-item-title")?.textContent === title);
  if (!match) throw new Error(`no row ${title}`);
  return match;
}

function menuButton(title: string): HTMLElement {
  return screen.getByRole("button", { name: text.row.actions(title) });
}

function chooseFromMenu(title: string, itemName: string) {
  fireEvent.click(menuButton(title));
  fireEvent.click(screen.getByRole("menuitem", { name: itemName }));
}

function tooltipOf(element: HTMLElement): HTMLElement | null {
  const id = element.getAttribute("aria-describedby");
  return id ? document.getElementById(id) : null;
}

describe("summary tooltip", () => {
  it("shows the summary after 500 ms of hover, wrapped, and not as a line of the row", async () => {
    await renderList([item("a", "Weekly sync", { summaryTopic: "Quarterly results and delivery plan" })]);
    const row = open("Weekly sync");
    const tip = tooltipOf(row) as HTMLElement;
    expect(tip).toHaveAttribute("role", "tooltip");
    expect(tip).toHaveTextContent("Quarterly results and delivery plan");
    expect(tip).toHaveClass("ui-tooltip--wrap");
    expect(tip).toBeInTheDocument();
    expect(tip.hidden).toBe(true);
    expect(row).not.toHaveTextContent("Quarterly results");

    vi.useFakeTimers();
    fireEvent.mouseEnter(row);
    act(() => { vi.advanceTimersByTime(499); });
    expect(tip.hidden).toBe(true);
    act(() => { vi.advanceTimersByTime(1); });
    expect(tip.hidden).toBe(false);
    fireEvent.mouseLeave(row);
    expect(tip.hidden).toBe(true);
  });

  it("shows it on keyboard focus too and Escape dismisses it", async () => {
    await renderList([item("a", "Weekly sync", { summaryTopic: "Topic text" })]);
    const row = open("Weekly sync");
    const tip = tooltipOf(row) as HTMLElement;
    vi.useFakeTimers();
    act(() => { row.focus(); });
    act(() => { vi.advanceTimersByTime(500); });
    expect(tip.hidden).toBe(false);
    fireEvent.keyDown(row, { key: "Escape" });
    expect(tip.hidden).toBe(true);
  });

  it("has no tooltip without a summary", async () => {
    await renderList([item("a", "Weekly sync"), item("b", "Blank", { summaryTopic: "   " })]);
    for (const title of ["Weekly sync", "Blank"]) {
      expect(open(title)).not.toHaveAttribute("aria-describedby");
    }
    expect(document.querySelector(".library-row-tip")).toBeNull();
  });
});

describe("row actions menu", () => {
  it("is a button with an accessible name per recording that opens rename, the three downloads and delete", async () => {
    const { onSelectMeeting } = await renderList([item("a", "Weekly sync", { summaryTopic: "Topic" })]);
    const trigger = menuButton("Weekly sync");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: text.row.actions("Weekly sync") });
    expect(within(menu).getAllByRole("menuitem").map((entry) => entry.textContent))
      .toEqual([text.row.rename, text.row.downloadTranscript, text.row.downloadSummary, text.row.downloadVideo,
        text.row.delete]);
    // A separator sets the destructive action apart, right before it.
    const separator = within(menu).getByRole("separator");
    expect(separator.nextElementSibling).toBe(within(menu).getByRole("menuitem", { name: text.row.delete }));
    expect(separator.previousElementSibling).toBe(within(menu).getByRole("menuitem", { name: text.row.downloadVideo }));
    expect(within(menu).getByRole("menuitem", { name: text.row.delete })).toHaveClass("ui-menu-item--danger");
    // Using the menu never opens the recording.
    expect(onSelectMeeting).not.toHaveBeenCalled();
  });

  it("is keyboard operable: arrows move, Escape closes and the focus returns to the button", async () => {
    await renderList([item("a", "Weekly sync")]);
    const trigger = menuButton("Weekly sync");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const [rename, download] = screen.getAllByRole("menuitem");
    expect(rename).toHaveFocus();
    fireEvent.keyDown(rename, { key: "ArrowDown" });
    expect(download).toHaveFocus();
    // The summary is not there yet (disabled) and the separator is not an item: the arrows skip both.
    fireEvent.keyDown(download, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: text.row.downloadVideo })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menuitem", { name: text.row.downloadVideo }), { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: text.row.delete })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menuitem", { name: text.row.delete }), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("works on rows in any state, with the download only for a ready recording", async () => {
    await renderList([
      item("r", "Ready one"),
      item("p", "Processing one", { processState: ProcessState.Transcribing }),
      item("f", "Failed one", { processState: ProcessState.Failed }),
      item("q", "Audio only", { mediaKind: "audio" }),
    ]);
    for (const [title, enabled] of [["Ready one", true], ["Processing one", false], ["Failed one", false], ["Audio only", true]] as const) {
      fireEvent.click(menuButton(title));
      const download = screen.getByRole("menuitem", { name: text.row.downloadTranscript });
      expect(screen.getByRole("menuitem", { name: text.row.rename })).not.toHaveAttribute("aria-disabled");
      expect(screen.getByRole("menuitem", { name: text.row.delete })).not.toHaveAttribute("aria-disabled");
      if (enabled) {
        expect(download).not.toHaveAttribute("aria-disabled");
        expect(download).not.toHaveAttribute("title");
      } else {
        expect(download).toHaveAttribute("aria-disabled", "true");
        expect(download).toHaveAttribute("title", text.row.downloadUnavailable);
      }
      fireEvent.keyDown(download, { key: "Escape" });
    }
  });

  it("disables the summary with its hint until the list reports one, and every download for a recording that is not ready", async () => {
    await renderList([
      item("n", "No summary"),
      item("s", "With summary", { summaryTopic: "Topic" }),
      item("p", "Processing one", { processState: ProcessState.Transcribing, summaryTopic: "Topic" }),
    ]);
    const entries = (title: string) => {
      fireEvent.click(menuButton(title));
      return {
        summary: screen.getByRole("menuitem", { name: text.row.downloadSummary }),
        media: screen.getByRole("menuitem", { name: text.row.downloadVideo }),
      };
    };
    let { summary, media } = entries("No summary");
    expect(summary).toHaveAttribute("aria-disabled", "true");
    expect(summary).toHaveAttribute("title", text.row.downloadSummaryUnavailable);
    expect(text.row.downloadSummaryUnavailable).toBe(meetingText.summaryUnavailable);
    expect(media).not.toHaveAttribute("aria-disabled");
    fireEvent.keyDown(media, { key: "Escape" });

    ({ summary, media } = entries("With summary"));
    expect(summary).not.toHaveAttribute("aria-disabled");
    expect(summary).not.toHaveAttribute("title");
    fireEvent.keyDown(media, { key: "Escape" });

    ({ summary, media } = entries("Processing one"));
    expect(summary).toHaveAttribute("aria-disabled", "true");
    expect(summary).toHaveAttribute("title", text.row.downloadSummaryUnavailable);
    expect(media).toHaveAttribute("aria-disabled", "true");
    expect(media).toHaveAttribute("title", text.row.downloadMediaUnavailable);
  });

  it("names the media download after its kind: video, or audio for an audio-only recording", async () => {
    await renderList([item("v", "Has video"), item("q", "Audio only", { mediaKind: "audio" })]);
    fireEvent.click(menuButton("Has video"));
    expect(screen.getByRole("menuitem", { name: text.row.downloadVideo })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: text.row.downloadAudio })).toBeNull();
    fireEvent.keyDown(screen.getByRole("menuitem", { name: text.row.rename }), { key: "Escape" });
    fireEvent.click(menuButton("Audio only"));
    expect(screen.getByRole("menuitem", { name: text.row.downloadAudio })).not.toHaveAttribute("aria-disabled");
    expect(screen.queryByRole("menuitem", { name: text.row.downloadVideo })).toBeNull();
  });

  it("is in the tab order only for the row that holds the list's Tab stop", async () => {
    await renderList([item("a", "First"), item("b", "Second")]);
    expect(open("First")).toHaveAttribute("tabindex", "0");
    expect(menuButton("First")).toHaveAttribute("tabindex", "0");
    expect(open("Second")).toHaveAttribute("tabindex", "-1");
    expect(menuButton("Second")).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(open("First"), { key: "ArrowDown" });
    expect(open("Second")).toHaveFocus();
    expect(open("Second")).toHaveAttribute("tabindex", "0");
    expect(open("First")).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(open("Second"), { key: "End" });
    expect(open("Second")).toHaveFocus();
    fireEvent.keyDown(open("Second"), { key: "Home" });
    expect(open("First")).toHaveFocus();
  });
});

describe("inline rename", () => {
  it("replaces the title with a field; Enter saves through the rename API and the row shows the new title", async () => {
    const { list } = await renderList([item("a", "Weekly sync")]);
    const rename = vi.spyOn(api, "renameMeeting").mockResolvedValue({ meetingId: "a", title: "Sprint review" });
    list.mockResolvedValue([item("a", "Sprint review")]);
    const changed = vi.fn();
    window.addEventListener(LIBRARY_CHANGED_EVENT, changed);

    chooseFromMenu("Weekly sync", text.row.rename);
    const field = screen.getByRole("textbox", { name: text.row.renameLabel });
    expect(field).toHaveFocus();
    expect(field).toHaveValue("Weekly sync");
    expect(screen.queryByText("Weekly sync", { selector: ".library-item-title" })).toBeNull();

    fireEvent.change(field, { target: { value: "  Sprint review " } });
    fireEvent.submit(field.closest("form") as HTMLFormElement);

    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(rename).toHaveBeenCalledWith("a", "Sprint review");
    expect(open("Sprint review")).toHaveFocus();
    expect(changed).toHaveBeenCalled();
    window.removeEventListener(LIBRARY_CHANGED_EVENT, changed);
  });

  it("shows a failure inline, keeps what was typed and lets the user retry", async () => {
    await renderList([item("a", "Weekly sync")]);
    const rename = vi.spyOn(api, "renameMeeting").mockRejectedValueOnce(new Error("Error 500"));
    chooseFromMenu("Weekly sync", text.row.rename);
    const field = screen.getByRole("textbox", { name: text.row.renameLabel });
    fireEvent.change(field, { target: { value: "Retry me" } });
    fireEvent.submit(field.closest("form") as HTMLFormElement);

    expect(await screen.findByRole("alert")).toHaveTextContent(text.row.renameFailed);
    expect(screen.getByRole("textbox", { name: text.row.renameLabel })).toHaveValue("Retry me");
    expect(screen.getByRole("textbox", { name: text.row.renameLabel })).toHaveAttribute("aria-invalid", "true");

    rename.mockResolvedValueOnce({ meetingId: "a", title: "Retry me" });
    fireEvent.submit(screen.getByRole("textbox").closest("form") as HTMLFormElement);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(rename).toHaveBeenCalledTimes(2);
  });

  it("Escape cancels without calling the API, returns the focus to the row and keeps the selection", async () => {
    await renderList([item("a", "Weekly sync"), item("b", "Other")]);
    const rename = vi.spyOn(api, "renameMeeting");
    fireEvent.click(screen.getByRole("checkbox", { name: text.row.select("Other") }));
    chooseFromMenu("Weekly sync", text.row.rename);
    const field = screen.getByRole("textbox", { name: text.row.renameLabel });
    fireEvent.change(field, { target: { value: "Never saved" } });
    fireEvent.keyDown(field, { key: "Escape" });

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(open("Weekly sync")).toHaveFocus();
    expect(rename).not.toHaveBeenCalled();
    expect(screen.getByText(text.selection.count(1))).toBeInTheDocument();
  });

  it("does not save an empty title", async () => {
    await renderList([item("a", "Weekly sync")]);
    const rename = vi.spyOn(api, "renameMeeting");
    chooseFromMenu("Weekly sync", text.row.rename);
    const field = screen.getByRole("textbox", { name: text.row.renameLabel });
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.submit(field.closest("form") as HTMLFormElement);
    expect(rename).not.toHaveBeenCalled();
    expect(field).toHaveAttribute("aria-invalid", "true");
  });
});

describe("row download", () => {
  const transcript = {
    id: "t", meetingId: "a", language: "es", provider: "x", supportsTurns: true, createdAt: "2026-10-28T17:45:00Z",
    segments: [], presentation: "words" as const,
    turns: [{
      id: "t:turn:1", transcriptId: "t", sequence: 1, speakerId: "s1", speakerLabel: "Speaker 1", startMs: 0,
      endMs: 1000, text: "Hola a todos", wordCount: 3, hasAmbiguous: false,
    }],
  } as unknown as api.MeetingTranscript;

  function captureDownloads() {
    const files: Array<{ name: string; content: Promise<string> }> = [];
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn((blob: Blob) => {
        const reader = new FileReader();
        const content = new Promise<string>((resolve) => { reader.onload = () => resolve(String(reader.result)); });
        reader.readAsText(blob);
        files.push({ name: "", content });
        return "blob:test";
      }),
      revokeObjectURL: vi.fn(),
    }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      files[files.length - 1].name = this.download;
    });
    return files;
  }

  it("fetches the transcript and downloads <title>.txt, like the detail header", async () => {
    await renderList([item("a", "Weekly sync")]);
    const files = captureDownloads();
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 404"));
    vi.spyOn(api, "getSpeakerReview").mockRejectedValue(new Error("Error 404"));

    chooseFromMenu("Weekly sync", text.row.downloadTranscript);

    await waitFor(() => expect(files).toHaveLength(1));
    expect(files[0].name).toBe("Weekly sync.txt");
    expect(await files[0].content).toBe(`[00:00] ${copy.transcript.numberedSpeaker("1")}: Hola a todos`);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("uses the reviewed speaker names", async () => {
    await renderList([item("a", "Weekly sync")]);
    const files = captureDownloads();
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(api, "getDiarization").mockResolvedValue({ speakers: [], assignments: [] } as unknown as api.MeetingDiarization);
    vi.spyOn(api, "getSpeakerReview").mockResolvedValue({
      revisionId: "r", items: [{ speakerId: "s1", disposition: "named" }], labelsBySpeakerId: { s1: "Ana" },
    } as unknown as api.SpeakerReview);

    chooseFromMenu("Weekly sync", text.row.downloadTranscript);
    await waitFor(() => expect(files).toHaveLength(1));
    expect(await files[0].content).toBe("[00:00] Ana: Hola a todos");
  });

  it("does nothing for a recording that is not ready", async () => {
    await renderList([item("p", "Processing one", { processState: ProcessState.Transcribing })]);
    const get = vi.spyOn(api, "getTranscript");
    chooseFromMenu("Processing one", text.row.downloadTranscript);
    expect(get).not.toHaveBeenCalled();
  });

  it("shows an inline error in the row when the transcript cannot be fetched", async () => {
    await renderList([item("a", "Weekly sync")]);
    vi.spyOn(api, "getTranscript").mockRejectedValue(new Error("Error 500"));
    vi.spyOn(api, "getDiarization").mockResolvedValue({ speakers: [], assignments: [] } as unknown as api.MeetingDiarization);
    vi.spyOn(api, "getSpeakerReview").mockRejectedValue(new Error("Error 404"));
    chooseFromMenu("Weekly sync", text.row.downloadTranscript);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.row.downloadFailed);
  });
});

describe("row summary download", () => {
  const v1 = {
    summaryId: "s", meetingId: "a", templateId: "t", templateName: "General", templateVersion: 1,
    topic: "Quarterly results", schemaVersion: 1 as const, keyPoints: ["Revenue grew", "Costs fell"],
    conclusion: null, reviewState: "draft" as const, generation: 1,
    createdAt: "2026-11-14T12:00:00Z", updatedAt: "2026-11-14T12:00:00Z",
  };
  const v2 = {
    ...v1, schemaVersion: 2 as const, templateVersion: 2, conclusion: "All good.",
    keyPoints: [{
      title: "Finance", sources: [],
      items: [{ text: "Revenue grew", subItems: ["Q3", "Q4"] }, { text: "Costs fell", subItems: [] }],
    }],
  };

  function captureDownloads() {
    const files: Array<{ name: string; content: Promise<string> }> = [];
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn((blob: Blob) => {
        const reader = new FileReader();
        const content = new Promise<string>((resolve) => { reader.onload = () => resolve(String(reader.result)); });
        reader.readAsText(blob);
        files.push({ name: "", content });
        return "blob:test";
      }),
      revokeObjectURL: vi.fn(),
    }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      files[files.length - 1].name = this.download;
    });
    return files;
  }

  it.each([["v1", v1], ["v2", v2]] as const)("saves the %s summary as <title> - resumen.txt with the panel's own export", async (_name, summary) => {
    await renderList([item("a", "Weekly sync", { summaryTopic: "Quarterly results" })]);
    const files = captureDownloads();
    const get = vi.spyOn(api, "getMeetingSummary").mockResolvedValue(summary);

    chooseFromMenu("Weekly sync", text.row.downloadSummary);

    await waitFor(() => expect(files).toHaveLength(1));
    expect(get).toHaveBeenCalledWith("a");
    expect(files[0].name).toBe("Weekly sync - resumen.txt");
    expect(await files[0].content).toBe(summaryPlainText(summary));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the transcript name apart from the summary name", async () => {
    await renderList([item("a", "Weekly sync", { summaryTopic: "Topic" })]);
    const files = captureDownloads();
    vi.spyOn(api, "getMeetingSummary").mockResolvedValue(v1);
    vi.spyOn(api, "getTranscript").mockResolvedValue({
      id: "t", meetingId: "a", language: "es", provider: "x", supportsTurns: true, createdAt: "2026-10-28T17:45:00Z",
      segments: [], presentation: "words",
      turns: [{ id: "t:turn:1", transcriptId: "t", sequence: 1, speakerId: "s1", speakerLabel: "S1", startMs: 0,
        endMs: 1000, text: "Hola", wordCount: 1, hasAmbiguous: false }],
    } as unknown as api.MeetingTranscript);
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 404"));
    vi.spyOn(api, "getSpeakerReview").mockRejectedValue(new Error("Error 404"));
    chooseFromMenu("Weekly sync", text.row.downloadTranscript);
    await waitFor(() => expect(files).toHaveLength(1));
    chooseFromMenu("Weekly sync", text.row.downloadSummary);
    await waitFor(() => expect(files).toHaveLength(2));
    expect(files.map((file) => file.name)).toEqual(["Weekly sync.txt", "Weekly sync - resumen.txt"]);
  });

  it("does nothing for a recording without a summary", async () => {
    await renderList([item("a", "Weekly sync")]);
    const get = vi.spyOn(api, "getMeetingSummary");
    chooseFromMenu("Weekly sync", text.row.downloadSummary);
    expect(get).not.toHaveBeenCalled();
  });

  it("shows an inline error and saves nothing when the summary disappeared or the request fails", async () => {
    await renderList([item("a", "Weekly sync", { summaryTopic: "Topic" })]);
    const files = captureDownloads();
    const get = vi.spyOn(api, "getMeetingSummary").mockResolvedValue(null);
    chooseFromMenu("Weekly sync", text.row.downloadSummary);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.row.downloadSummaryFailed);
    get.mockRejectedValue(new Error("Error 500"));
    chooseFromMenu("Weekly sync", text.row.downloadSummary);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.row.downloadSummaryFailed);
    expect(files).toHaveLength(0);
  });
});

describe("row media download", () => {
  const source = (url: string, mime: string) => ({ source_id: url, url, mime_type: mime });
  const manifest = (overrides: Partial<api.PlaybackManifest>): api.PlaybackManifest => ({
    meeting_id: "a", duration_seconds: 600, video_presence: "muxed", audio_source: source("http://store.test/a.m4a", "audio/mp4"),
    muxed_video_source: source("http://store.test/v.webm", "video/webm"), video_sources: [], ...overrides,
  });

  function captureAnchor() {
    const anchors: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      anchors.push(this);
    });
    return anchors;
  }

  it("downloads the muxed video as <title>.webm from a fresh manifest", async () => {
    await renderList([item("a", "Weekly sync")]);
    const anchors = captureAnchor();
    const get = vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(manifest({}));
    chooseFromMenu("Weekly sync", text.row.downloadVideo);
    await waitFor(() => expect(anchors).toHaveLength(1));
    expect(get).toHaveBeenCalledWith("a");
    expect(anchors[0]).toHaveAttribute("href", "http://store.test/v.webm");
    expect(anchors[0]).toHaveAttribute("download", "Weekly sync.webm");
  });

  it("takes the video source when audio and video are separate", async () => {
    await renderList([item("a", "Weekly sync")]);
    const anchors = captureAnchor();
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(manifest({
      video_presence: "separate", muxed_video_source: null, video_sources: [source("http://store.test/v.mp4", "video/mp4")],
    }));
    chooseFromMenu("Weekly sync", text.row.downloadVideo);
    await waitFor(() => expect(anchors).toHaveLength(1));
    expect(anchors[0]).toHaveAttribute("href", "http://store.test/v.mp4");
    expect(anchors[0]).toHaveAttribute("download", "Weekly sync.mp4");
  });

  it("downloads the audio of an audio-only recording with its own extension", async () => {
    await renderList([item("a", "Podcast", { mediaKind: "audio" })]);
    const anchors = captureAnchor();
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(manifest({ video_presence: "absent", muxed_video_source: null }));
    chooseFromMenu("Podcast", text.row.downloadAudio);
    await waitFor(() => expect(anchors).toHaveLength(1));
    expect(anchors[0]).toHaveAttribute("href", "http://store.test/a.m4a");
    expect(anchors[0]).toHaveAttribute("download", "Podcast.m4a");
  });

  it("tells the user when the browser opened the file in a tab instead of saving it", async () => {
    await renderList([item("a", "Weekly sync")]);
    captureAnchor();
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(manifest({}));
    chooseFromMenu("Weekly sync", text.row.downloadVideo);
    expect(await screen.findByText(meetingText.mediaOpened)).toHaveAttribute("role", "status");
  });

  it("shows an inline error when there is no manifest or no source", async () => {
    await renderList([item("a", "Weekly sync")]);
    const anchors = captureAnchor();
    const get = vi.spyOn(api, "getPlaybackManifest").mockRejectedValue(new Error("Error 404"));
    chooseFromMenu("Weekly sync", text.row.downloadVideo);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.row.downloadMediaFailed);
    get.mockResolvedValue(manifest({ muxed_video_source: null }));
    chooseFromMenu("Weekly sync", text.row.downloadVideo);
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.row.downloadMediaFailed);
    expect(anchors).toHaveLength(0);
  });

  it("does nothing for a recording that is not ready", async () => {
    await renderList([item("p", "Processing one", { processState: ProcessState.Transcribing })]);
    const get = vi.spyOn(api, "getPlaybackManifest");
    chooseFromMenu("Processing one", text.row.downloadVideo);
    expect(get).not.toHaveBeenCalled();
  });
});

describe("row delete", () => {
  it("asks for confirmation, deletes through the API and removes the row", async () => {
    await renderList([item("a", "Weekly sync"), item("b", "Other")]);
    const del = vi.spyOn(api, "deleteMeeting").mockResolvedValue(undefined);

    chooseFromMenu("Weekly sync", text.row.delete);
    const dialog = screen.getByRole("dialog", { name: text.row.deleteTitle, hidden: true });
    expect(dialog).toHaveTextContent(text.row.deleteBody);
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: text.row.delete, hidden: true }));

    await waitFor(() => expect(screen.queryByText("Weekly sync", { selector: ".library-item-title" })).toBeNull());
    expect(del).toHaveBeenCalledWith("a");
    expect(window.location.pathname).toBe("/");
    // The keyboard lands on the neighbouring row.
    expect(open("Other")).toHaveFocus();
    expect(document.querySelector(".library-sr-only")).toHaveTextContent(text.row.deleted("Weekly sync"));
  });

  it("keeps the row when the user cancels", async () => {
    await renderList([item("a", "Weekly sync")]);
    const del = vi.spyOn(api, "deleteMeeting");
    chooseFromMenu("Weekly sync", text.row.delete);
    fireEvent.click(screen.getByRole("button", { name: text.row.cancel, hidden: true }));
    expect(del).not.toHaveBeenCalled();
    expect(open("Weekly sync")).toBeInTheDocument();
  });

  it("goes back to the library route when the open recording is deleted", async () => {
    window.history.replaceState(null, "", "/meetings/a");
    await renderList([item("a", "Weekly sync"), item("b", "Other")], { selectedId: "a" });
    vi.spyOn(api, "deleteMeeting").mockResolvedValue(undefined);
    chooseFromMenu("Weekly sync", text.row.delete);
    fireEvent.click(screen.getByRole("button", { name: text.row.delete, hidden: true }));
    await waitFor(() => expect(window.location.pathname).toBe("/"));
  });

  it("shows an inline error and keeps the row when the API fails", async () => {
    await renderList([item("a", "Weekly sync")]);
    vi.spyOn(api, "deleteMeeting").mockRejectedValue(new Error("Error 500"));
    chooseFromMenu("Weekly sync", text.row.delete);
    fireEvent.click(screen.getByRole("button", { name: text.row.delete, hidden: true }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.row.deleteFailed);
    expect(open("Weekly sync")).toBeInTheDocument();
  });
});
