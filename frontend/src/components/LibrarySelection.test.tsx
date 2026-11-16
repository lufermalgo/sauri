// @vitest-environment jsdom
/**
 * Library multi-selection and bulk actions: checkboxes, ranges, the action bar, sequential bulk
 * delete (progress, partial failure, retry) and bulk transcript download.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, waitFor, fireEvent, within, act } from "@testing-library/react";
import { MeetingOrigin, ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";

import { RecordingLibrary } from "./RecordingLibrary";
import { rangeBetween } from "./useLibrarySelection";
import { LIBRARY_CHANGED_EVENT } from "../library-events";
import * as api from "../api";
import { copy } from "../copy/es";

const text = copy.library;
const selection = text.selection;
const bulk = text.bulk;

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});

afterEach(() => {
  cleanup();
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

/** Meetings m1..mN, titled "Meeting 1".. in that order, all in one group. */
function many(count: number, overrides: (index: number) => Partial<MeetingListItem> = () => ({})): MeetingListItem[] {
  return Array.from({ length: count }, (_, index) => item(`m${index + 1}`, `Meeting ${index + 1}`, overrides(index + 1)));
}

async function renderList(items: MeetingListItem[], selectedId?: string) {
  const list = vi.spyOn(api, "listMeetings").mockResolvedValue(items);
  const onSelectMeeting = vi.fn();
  render(<RecordingLibrary refreshKey={0} selectedId={selectedId} onSelectMeeting={onSelectMeeting} />);
  await screen.findByRole("search");
  return { list, onSelectMeeting };
}

function box(title: string): HTMLInputElement {
  return screen.getByRole("checkbox", { name: text.row.select(title) }) as HTMLInputElement;
}

function rowOpen(title: string): HTMLElement {
  const match = screen.getAllByRole("button").find((button) =>
    button.classList.contains("library-item") && button.querySelector(".library-item-title")?.textContent === title);
  if (!match) throw new Error(`no row ${title}`);
  return match;
}

function selectAllBox(): HTMLInputElement {
  return screen.getByRole("checkbox", { name: selection.selectAll }) as HTMLInputElement;
}

function checkedTitles(): string[] {
  return screen.getAllByRole("checkbox")
    .filter((input) => (input as HTMLInputElement).checked && input.getAttribute("aria-label") !== selection.selectAll)
    .map((input) => (input.getAttribute("aria-label") ?? "").replace(/^Seleccionar «|»$/g, ""));
}

describe("rangeBetween", () => {
  const order = ["a", "b", "c", "d", "e"];
  it("is inclusive and works in both directions", () => {
    expect(rangeBetween(order, "b", "d")).toEqual(["b", "c", "d"]);
    expect(rangeBetween(order, "d", "b")).toEqual(["b", "c", "d"]);
    expect(rangeBetween(order, "c", "c")).toEqual(["c"]);
  });
  it("falls back to the target without a usable anchor", () => {
    expect(rangeBetween(order, "zzz", "c")).toEqual(["c"]);
    expect(rangeBetween(order, "a", "zzz")).toEqual([]);
  });
});

describe("selecting rows", () => {
  it("gives every row a checkbox named after its title, and the list keeps list semantics", async () => {
    await renderList(many(3));
    for (const title of ["Meeting 1", "Meeting 2", "Meeting 3"]) expect(box(title)).not.toBeChecked();
    expect(screen.getAllByRole("list").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("selecting one row replaces the list header with the action bar and leaves the open recording alone", async () => {
    const { onSelectMeeting } = await renderList(many(3), "m2");
    fireEvent.click(box("Meeting 1"));

    expect(box("Meeting 1")).toBeChecked();
    expect(screen.getByText(selection.count(1))).toBeInTheDocument();
    expect(screen.queryByText(text.title)).toBeNull();
    expect(screen.queryByRole("button", { name: text.upload })).toBeNull();
    const toolbar = screen.getByRole("toolbar", { name: selection.toolbar });
    expect(within(toolbar).getByRole("button", { name: selection.deleteAll })).toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: selection.downloadAll })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: selection.clear })).toBeInTheDocument();
    // The open recording is untouched.
    expect(onSelectMeeting).not.toHaveBeenCalled();
    expect(rowOpen("Meeting 2")).toHaveAttribute("aria-current", "true");
  });

  it("selection mode is flagged on the pane so the checkboxes stay visible", async () => {
    await renderList(many(2));
    expect(document.querySelector(".library")).not.toHaveAttribute("data-selecting");
    fireEvent.click(box("Meeting 1"));
    expect(document.querySelector(".library")).toHaveAttribute("data-selecting");
  });

  it("the header checkbox selects every shown row, shows indeterminate for some and deselects all", async () => {
    await renderList(many(4));
    expect(selectAllBox().checked).toBe(false);
    expect(selectAllBox().indeterminate).toBe(false);

    fireEvent.click(box("Meeting 2"));
    expect(selectAllBox().indeterminate).toBe(true);
    expect(selectAllBox().checked).toBe(false);

    fireEvent.click(selectAllBox());
    expect(checkedTitles()).toEqual(["Meeting 1", "Meeting 2", "Meeting 3", "Meeting 4"]);
    expect(selectAllBox().checked).toBe(true);
    expect(selectAllBox().indeterminate).toBe(false);
    expect(screen.getByText(selection.count(4))).toBeInTheDocument();

    fireEvent.click(selectAllBox());
    expect(checkedTitles()).toEqual([]);
    // No selection: the normal header and toolbar are back.
    expect(screen.getByRole("button", { name: text.upload })).toBeInTheDocument();
    expect(screen.getByRole("search")).toBeInTheDocument();
  });

  it("the header checkbox applies only to the rows a search leaves visible", async () => {
    await renderList([item("a", "Planning one"), item("b", "Planning two"), item("c", "Client call")]);
    fireEvent.click(screen.getByRole("button", { name: text.search.text }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "planning" } });
    // The select-all checkbox stays reachable while searching.
    fireEvent.click(selectAllBox());
    expect(checkedTitles()).toEqual(["Planning one", "Planning two"]);
    expect(screen.getByText(selection.count(2))).toBeInTheDocument();
  });

  it("Shift+click selects a range, in the order the rows are shown", async () => {
    await renderList(many(6));
    fireEvent.click(box("Meeting 2"));
    fireEvent.click(box("Meeting 5"), { shiftKey: true });
    expect(checkedTitles()).toEqual(["Meeting 2", "Meeting 3", "Meeting 4", "Meeting 5"]);

    // Also from the row itself, and upwards from the anchor.
    fireEvent.click(rowOpen("Meeting 1"), { shiftKey: true });
    expect(checkedTitles()).toEqual(["Meeting 1", "Meeting 2", "Meeting 3", "Meeting 4", "Meeting 5"]);
  });

  it("Ctrl or Cmd+click on a row toggles it without opening the recording", async () => {
    const { onSelectMeeting } = await renderList(many(3));
    fireEvent.click(rowOpen("Meeting 1"), { ctrlKey: true });
    fireEvent.click(rowOpen("Meeting 3"), { metaKey: true });
    expect(checkedTitles()).toEqual(["Meeting 1", "Meeting 3"]);
    fireEvent.click(rowOpen("Meeting 1"), { ctrlKey: true });
    expect(checkedTitles()).toEqual(["Meeting 3"]);
    expect(onSelectMeeting).not.toHaveBeenCalled();
  });

  it("a plain click still opens the recording while recordings are selected", async () => {
    const { onSelectMeeting } = await renderList(many(2));
    fireEvent.click(box("Meeting 1"));
    fireEvent.click(rowOpen("Meeting 2"));
    expect(onSelectMeeting).toHaveBeenCalledTimes(1);
    expect(checkedTitles()).toEqual(["Meeting 1"]);
  });

  it("Escape and Cancelar clear the selection", async () => {
    await renderList(many(3));
    fireEvent.click(box("Meeting 1"));
    fireEvent.click(box("Meeting 2"));
    fireEvent.keyDown(rowOpen("Meeting 3"), { key: "Escape" });
    expect(checkedTitles()).toEqual([]);

    fireEvent.click(box("Meeting 1"));
    fireEvent.click(screen.getByRole("button", { name: selection.clear }));
    expect(checkedTitles()).toEqual([]);
    expect(screen.getByRole("button", { name: text.upload })).toBeInTheDocument();
  });

  it("keeps the selection across quiet refreshes and drops recordings that disappear", async () => {
    const { list } = await renderList(many(3));
    fireEvent.click(box("Meeting 1"));
    fireEvent.click(box("Meeting 2"));

    // A refresh with the same recordings keeps both.
    list.mockResolvedValue(many(3, (index) => (index === 3 ? { title: "Meeting 3 renamed" } : {})));
    window.dispatchEvent(new Event(LIBRARY_CHANGED_EVENT));
    await screen.findByText("Meeting 3 renamed", { selector: ".library-item-title" });
    expect(checkedTitles()).toEqual(["Meeting 1", "Meeting 2"]);

    // Meeting 2 was deleted elsewhere: the selection shrinks by itself.
    list.mockResolvedValue([item("m1", "Meeting 1"), item("m3", "Meeting 3 renamed")]);
    window.dispatchEvent(new Event(LIBRARY_CHANGED_EVENT));
    await waitFor(() => expect(screen.getByText(selection.count(1))).toBeInTheDocument());
    expect(checkedTitles()).toEqual(["Meeting 1"]);

    // Everything selected disappeared: back to the normal header.
    list.mockResolvedValue([item("m3", "Meeting 3 renamed")]);
    window.dispatchEvent(new Event(LIBRARY_CHANGED_EVENT));
    await waitFor(() => expect(screen.getByRole("button", { name: text.upload })).toBeInTheDocument());
  });
});

/** deleteMeeting calls that wait to be settled by the test, in call order. */
function gatedDeletes() {
  const gates: Array<{ id: string; resolve: () => void; reject: () => void }> = [];
  const spy = vi.spyOn(api, "deleteMeeting").mockImplementation((id) => new Promise<void>((resolve, reject) => {
    gates.push({ id, resolve: () => resolve(), reject: () => reject(new Error("Error 500")) });
  }));
  return { gates, spy };
}

async function settle(gate: { resolve: () => void; reject: () => void }, outcome: "ok" | "fail") {
  await act(async () => { (outcome === "ok" ? gate.resolve : gate.reject)(); });
}

function confirmDialog(): HTMLElement {
  return screen.getByRole("dialog", { hidden: true });
}

describe("bulk delete", () => {
  async function startDelete(items: MeetingListItem[], titles: string[]) {
    const view = await renderList(items);
    for (const title of titles) fireEvent.click(box(title));
    fireEvent.click(screen.getByRole("button", { name: selection.deleteAll }));
    return view;
  }

  it("asks first, stating the count and that it cannot be undone, and deletes nothing on cancel", async () => {
    const del = vi.spyOn(api, "deleteMeeting").mockResolvedValue(undefined);
    await startDelete(many(3), ["Meeting 1", "Meeting 2"]);
    const dialog = confirmDialog();
    expect(dialog).toHaveTextContent(bulk.deleteConfirmTitle(2));
    expect(dialog).toHaveTextContent(bulk.deleteConfirmBody);
    fireEvent.click(within(dialog).getByRole("button", { name: bulk.cancel, hidden: true }));
    expect(del).not.toHaveBeenCalled();
    expect(checkedTitles()).toEqual(["Meeting 1", "Meeting 2"]);
  });

  it("deletes one at a time with a progress message and removes the rows", async () => {
    const { gates } = gatedDeletes();
    await startDelete(many(4), ["Meeting 1", "Meeting 3", "Meeting 4"]);
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: bulk.deleteConfirm, hidden: true }));

    const dialog = await screen.findByRole("dialog", { name: bulk.runningDeleteTitle });
    const status = within(dialog).getByRole("status");
    expect(status).toHaveTextContent(bulk.deleting(1, 3));
    expect(within(dialog).getByRole("progressbar")).toBeInTheDocument();
    // Concurrency 1: only the first request is out.
    expect(gates.map((gate) => gate.id)).toEqual(["m1"]);

    await settle(gates[0], "ok");
    await waitFor(() => expect(status).toHaveTextContent(bulk.deleting(2, 3)));
    expect(gates.map((gate) => gate.id)).toEqual(["m1", "m3"]);
    expect(screen.queryByText("Meeting 1", { selector: ".library-item-title" })).toBeNull();

    await settle(gates[1], "ok");
    await waitFor(() => expect(gates).toHaveLength(3));
    await settle(gates[2], "ok");

    const done = await screen.findByRole("dialog", { name: bulk.doneDeleteTitle });
    expect(within(done).getByRole("status")).toHaveTextContent(bulk.deleted(3, 0));
    expect(within(done).queryByRole("button", { name: bulk.retry })).toBeNull();
    expect(renderedTitlesLeft()).toEqual(["Meeting 2"]);
  });

  it("keeps going after a failure, reports it, keeps the failed ones selected and retries them", async () => {
    const { gates, spy } = gatedDeletes();
    await startDelete(many(4), ["Meeting 1", "Meeting 2", "Meeting 3"]);
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: bulk.deleteConfirm, hidden: true }));
    await screen.findByRole("dialog", { name: bulk.runningDeleteTitle });

    await settle(gates[0], "ok");
    await waitFor(() => expect(gates).toHaveLength(2));
    await settle(gates[1], "fail");
    await waitFor(() => expect(gates).toHaveLength(3));
    await settle(gates[2], "ok");

    const done = await screen.findByRole("dialog", { name: bulk.doneDeleteTitle });
    expect(within(done).getByRole("status")).toHaveTextContent(bulk.deleted(2, 1));
    expect(within(done).getByRole("status")).toHaveTextContent(`${bulk.deleted(2, 1)}`);
    expect(done).toHaveTextContent(bulk.failedKept);
    expect(renderedTitlesLeft()).toEqual(["Meeting 2", "Meeting 4"]);
    expect(checkedTitles()).toEqual(["Meeting 2"]);

    fireEvent.click(within(done).getByRole("button", { name: bulk.retry }));
    await waitFor(() => expect(gates).toHaveLength(4));
    expect(gates[3].id).toBe("m2");
    expect(spy).toHaveBeenCalledTimes(4);
    await settle(gates[3], "ok");
    const finished = await screen.findByRole("dialog", { name: bulk.doneDeleteTitle });
    expect(within(finished).getByRole("status")).toHaveTextContent(bulk.deleted(1, 0));
    expect(renderedTitlesLeft()).toEqual(["Meeting 4"]);
    expect(checkedTitles()).toEqual([]);
  });

  it("Detener leaves the remaining recordings alone", async () => {
    const { gates } = gatedDeletes();
    await startDelete(many(3), ["Meeting 1", "Meeting 2", "Meeting 3"]);
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: bulk.deleteConfirm, hidden: true }));
    const dialog = await screen.findByRole("dialog", { name: bulk.runningDeleteTitle });
    fireEvent.click(within(dialog).getByRole("button", { name: bulk.stop }));
    expect(within(dialog).getByRole("status")).toHaveTextContent(bulk.stopping);
    await settle(gates[0], "ok");

    const done = await screen.findByRole("dialog", { name: bulk.doneDeleteTitle });
    expect(done).toHaveTextContent(bulk.deleted(1, 0));
    expect(done).toHaveTextContent(bulk.notProcessed(2));
    expect(gates).toHaveLength(1);
    expect(checkedTitles()).toEqual(["Meeting 2", "Meeting 3"]);
  });

  it("after closing, the focus goes to the list header", async () => {
    vi.spyOn(api, "deleteMeeting").mockResolvedValue(undefined);
    await startDelete(many(2), ["Meeting 1", "Meeting 2"]);
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: bulk.deleteConfirm, hidden: true }));
    const done = await screen.findByRole("dialog", { name: bulk.doneDeleteTitle });
    const close = done.querySelector(".library-bulk-actions button") as HTMLElement;
    expect(close).toHaveTextContent(bulk.close);
    expect(close).toHaveFocus();
    fireEvent.click(close);
    await waitFor(() => expect(screen.queryByRole("dialog", { hidden: true })).toBeNull());
    expect(document.querySelector(".ui-pane-header")).toHaveFocus();
  });

  it("deleting the open recording takes the user back to the library route", async () => {
    window.history.replaceState(null, "", "/meetings/m2");
    vi.spyOn(api, "deleteMeeting").mockResolvedValue(undefined);
    const view = await renderList(many(3), "m2");
    fireEvent.click(box("Meeting 1"));
    fireEvent.click(box("Meeting 2"));
    fireEvent.click(screen.getByRole("button", { name: selection.deleteAll }));
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: bulk.deleteConfirm, hidden: true }));
    await screen.findByRole("dialog", { name: bulk.doneDeleteTitle });
    expect(window.location.pathname).toBe("/");
    expect(view.onSelectMeeting).not.toHaveBeenCalled();
  });
});

function renderedTitlesLeft(): string[] {
  return screen.getAllByRole("button")
    .filter((button) => button.classList.contains("library-item"))
    .map((button) => button.querySelector(".library-item-title")?.textContent ?? "");
}

describe("bulk download", () => {
  const transcript = (id: string) => ({
    id: `t-${id}`, meetingId: id, language: "es", provider: "x", supportsTurns: true, createdAt: "2026-10-28T17:45:00Z",
    segments: [], presentation: "words" as const,
    turns: [{
      id: `${id}:1`, transcriptId: `t-${id}`, sequence: 1, speakerId: null, speakerLabel: "Speaker 1", startMs: 0,
      endMs: 500, text: `Texto ${id}`, wordCount: 2, hasAmbiguous: false,
    }],
  }) as unknown as api.MeetingTranscript;

  function setup() {
    const names: string[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    const get = vi.spyOn(api, "getTranscript").mockImplementation(async (id) => transcript(id));
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 404"));
    vi.spyOn(api, "getSpeakerReview").mockRejectedValue(new Error("Error 404"));
    return { names, get };
  }

  it("downloads each selected transcript as <title>.txt, one after another, without asking up to five", async () => {
    const { names } = setup();
    await renderList(many(3));
    fireEvent.click(selectAllBox());
    fireEvent.click(screen.getByRole("button", { name: selection.downloadAll }));

    const done = await screen.findByRole("dialog", { name: bulk.doneDownloadTitle });
    expect(names).toEqual(["Meeting 1.txt", "Meeting 2.txt", "Meeting 3.txt"]);
    expect(within(done).getByRole("status")).toHaveTextContent(bulk.downloaded(3, 0));
    // Downloading leaves the selection as it was.
    expect(checkedTitles()).toHaveLength(3);
  });

  it("asks for confirmation above five recordings", async () => {
    const { names, get } = setup();
    await renderList(many(6));
    fireEvent.click(selectAllBox());
    fireEvent.click(screen.getByRole("button", { name: selection.downloadAll }));

    const confirm = confirmDialog();
    expect(confirm).toHaveTextContent(bulk.downloadConfirmTitle(6));
    expect(get).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole("button", { name: bulk.cancel, hidden: true }));
    expect(get).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: selection.downloadAll }));
    fireEvent.click(within(confirmDialog()).getByRole("button", { name: bulk.downloadConfirm, hidden: true }));
    await screen.findByRole("dialog", { name: bulk.doneDownloadTitle });
    expect(names).toHaveLength(6);
  });

  it("skips recordings that are not ready and says so", async () => {
    const { names } = setup();
    await renderList(many(3, (index) => (index === 2 ? { processState: ProcessState.Transcribing } : {})));
    fireEvent.click(selectAllBox());
    fireEvent.click(screen.getByRole("button", { name: selection.downloadAll }));
    const done = await screen.findByRole("dialog", { name: bulk.doneDownloadTitle });
    expect(names).toEqual(["Meeting 1.txt", "Meeting 3.txt"]);
    expect(done).toHaveTextContent(bulk.downloaded(2, 0));
    expect(done).toHaveTextContent(bulk.skippedNotReady(1));
  });

  it("explains when none of the selected recordings is ready", async () => {
    const { get } = setup();
    await renderList(many(2, () => ({ processState: ProcessState.Failed })));
    fireEvent.click(selectAllBox());
    fireEvent.click(screen.getByRole("button", { name: selection.downloadAll }));
    const done = await screen.findByRole("dialog", { name: bulk.doneDownloadTitle });
    expect(done).toHaveTextContent(bulk.noneReady);
    expect(get).not.toHaveBeenCalled();
  });

  it("counts a transcript that cannot be fetched as failed and retries only that one", async () => {
    const { names, get } = setup();
    get.mockImplementation(async (id) => {
      if (id === "m2") throw new Error("Error 500");
      return transcript(id);
    });
    await renderList(many(3));
    fireEvent.click(selectAllBox());
    fireEvent.click(screen.getByRole("button", { name: selection.downloadAll }));
    const done = await screen.findByRole("dialog", { name: bulk.doneDownloadTitle });
    expect(done).toHaveTextContent(bulk.downloaded(2, 1));
    expect(names).toEqual(["Meeting 1.txt", "Meeting 3.txt"]);

    get.mockImplementation(async (id) => transcript(id));
    fireEvent.click(within(done).getByRole("button", { name: bulk.retry }));
    await waitFor(() => expect(names).toEqual(["Meeting 1.txt", "Meeting 3.txt", "Meeting 2.txt"]));
    await screen.findByText(bulk.downloaded(1, 0));
  });
});
