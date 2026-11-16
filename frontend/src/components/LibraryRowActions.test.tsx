// @vitest-environment jsdom
/**
 * Library rows: the summary shows as a tooltip, and the "..." menu renames, downloads and deletes.
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
  it("is a button with an accessible name per recording that opens rename, download and delete", async () => {
    const { onSelectMeeting } = await renderList([item("a", "Weekly sync")]);
    const trigger = menuButton("Weekly sync");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: text.row.actions("Weekly sync") });
    expect(within(menu).getAllByRole("menuitem").map((entry) => entry.textContent))
      .toEqual([text.row.rename, text.row.downloadTranscript, text.row.delete]);
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
    fireEvent.keyDown(download, { key: "Escape" });
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

  it("forgets the last explored recording when it is deleted, and keeps it when another one is", async () => {
    const values = new Map([["sauri_last_meeting_id", "a"]]);
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    });
    await renderList([item("a", "Weekly sync"), item("b", "Other")], { selectedId: "a" });
    vi.spyOn(api, "deleteMeeting").mockResolvedValue(undefined);
    chooseFromMenu("Other", text.row.delete);
    fireEvent.click(screen.getByRole("button", { name: text.row.delete, hidden: true }));
    await waitFor(() => expect(screen.queryByText("Other")).toBeNull());
    expect(values.get("sauri_last_meeting_id")).toBe("a");
    chooseFromMenu("Weekly sync", text.row.delete);
    fireEvent.click(screen.getByRole("button", { name: text.row.delete, hidden: true }));
    await waitFor(() => expect(values.has("sauri_last_meeting_id")).toBe(false));
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
