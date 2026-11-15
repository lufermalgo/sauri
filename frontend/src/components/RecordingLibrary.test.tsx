// @vitest-environment jsdom
/**
 * Recording library: truthful list, states, and client-side search.
 *
 * Spec: portal-visual-design — PV4.2 (Property 2) and PV9.2.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent, within } from "@testing-library/react";
import { ProcessState, MeetingOrigin } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";

import { RecordingLibrary } from "./RecordingLibrary";
import * as api from "../api";
import { copy } from "../copy/es";

const text = copy.library;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

function meeting(overrides: Partial<MeetingListItem> = {}): MeetingListItem {
  return {
    id: "r-1",
    meetLink: "https://meet.google.com/abc-defg-hij",
    origin: MeetingOrigin.Link,
    processState: ProcessState.Queued,
    failureCause: null,
    createdAt: "2026-10-28T17:45:00Z",
    title: "Synthetic meeting",
    durationSeconds: null,
    speakerCount: null,
    summaryTopic: null,
    ...overrides,
  };
}

function renderLibrary(onSelectMeeting = vi.fn()) {
  render(<RecordingLibrary refreshKey={0} onSelectMeeting={onSelectMeeting} />);
  return onSelectMeeting;
}

function renderedTitles(): string[] {
  return within(screen.getByRole("list", { name: text.listLabel }))
    .getAllByRole("button")
    .map((button) => button.querySelector(".library-item-title")?.textContent ?? "");
}

describe("RecordingLibrary list", () => {
  it("keeps the order received from the API", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "b", title: "Second by name" }),
      meeting({ id: "a", title: "First by name", createdAt: "2026-01-01T10:00:00Z" }),
      meeting({ id: "c", title: "Third by name", createdAt: "2026-12-01T10:00:00Z" }),
    ]);
    renderLibrary();
    await screen.findByRole("heading", { name: text.title });
    await screen.findByRole("list", { name: text.listLabel });

    expect(renderedTitles()).toEqual(["Second by name", "First by name", "Third by name"]);
  });

  it("shows readable Spanish state labels and the formatted date", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "1", processState: ProcessState.Queued }),
      meeting({ id: "2", processState: ProcessState.Joining }),
      meeting({ id: "3", processState: ProcessState.Recording }),
      meeting({ id: "4", processState: ProcessState.Transcribing }),
      meeting({ id: "5", processState: ProcessState.Completed }),
      meeting({ id: "6", processState: ProcessState.Failed }),
    ]);
    renderLibrary();
    await screen.findByRole("list", { name: text.listLabel });

    for (const label of Object.values(text.states)) {
      expect(screen.getByText(label)).toBeDefined();
    }
    const expected = new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" })
      .format(new Date("2026-10-28T17:45:00Z"));
    expect(screen.getAllByText(expected).length).toBe(6);
  });

  it("shows the untitled label when the title is empty", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([meeting({ title: "" })]);
    renderLibrary();
    expect(await screen.findByText(text.untitled)).toBeDefined();
  });

  it("treats a null title from the API as untitled", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ title: null as unknown as string }),
    ]);
    renderLibrary();
    expect(await screen.findByText(text.untitled)).toBeDefined();
    fireEvent.change(screen.getByLabelText(text.search.text), { target: { value: "x" } });
    expect(screen.getByText(text.noMatch)).toBeDefined();
  });

  it("selecting a card calls onSelectMeeting with that meeting", async () => {
    const chosen = meeting({ id: "r-2", title: "Chosen one" });
    vi.spyOn(api, "listMeetings").mockResolvedValue([meeting({ id: "r-1" }), chosen]);
    const onSelectMeeting = renderLibrary();

    fireEvent.click(await screen.findByRole("button", { name: /Chosen one/ }));
    expect(onSelectMeeting).toHaveBeenCalledWith(chosen);
  });

  it("shows the empty state with an upload button that navigates to /upload", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([]);
    renderLibrary();
    await screen.findByText(text.empty);

    const buttons = screen.getAllByRole("button", { name: text.upload });
    fireEvent.click(buttons[buttons.length - 1]);
    expect(window.location.pathname).toBe("/upload");
    expect(screen.queryByRole("search")).toBeNull();
  });

  it("the header upload button navigates to /upload", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([meeting()]);
    renderLibrary();
    await screen.findByRole("list", { name: text.listLabel });

    fireEvent.click(screen.getByRole("button", { name: text.upload }));
    expect(window.location.pathname).toBe("/upload");
  });

  it("shows a loading status while the list is requested", async () => {
    vi.spyOn(api, "listMeetings").mockReturnValue(new Promise(() => {}));
    renderLibrary();
    expect((await screen.findByRole("status")).textContent).toBe(text.loading);
  });

  it("shows an alert with Reintentar and asks for the list again", async () => {
    const listMeetings = vi.spyOn(api, "listMeetings")
      .mockRejectedValueOnce(new Error("Not authenticated: token not found"))
      .mockResolvedValue([meeting({ title: "After retry" })]);
    renderLibrary();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(text.error);
    expect(listMeetings).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    expect(await screen.findByText("After retry")).toBeDefined();
    expect(listMeetings).toHaveBeenCalledTimes(2);
  });
});

describe("RecordingLibrary search", () => {
  const items = [
    meeting({ id: "1", title: "Planning meeting", createdAt: "2026-10-28T17:45:00Z" }),
    meeting({ id: "2", title: "Client interview", createdAt: "2026-09-10T15:00:00Z" }),
    meeting({ id: "3", title: "Closing notes", createdAt: "2026-11-02T15:00:00Z" }),
  ];

  async function openSearch() {
    vi.spyOn(api, "listMeetings").mockResolvedValue(items);
    renderLibrary();
    await screen.findByRole("list", { name: text.listLabel });
  }

  it("typing filters by title (case insensitive) and Limpiar restores", async () => {
    await openSearch();
    expect(screen.queryByRole("button", { name: text.search.clear })).toBeNull();

    fireEvent.change(screen.getByLabelText(text.search.text), { target: { value: "PLANNING" } });
    expect(renderedTitles()).toEqual(["Planning meeting"]);

    fireEvent.click(screen.getByRole("button", { name: text.search.clear }));
    await waitFor(() => expect(renderedTitles()).toHaveLength(3));
    expect((screen.getByLabelText(text.search.text) as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("button", { name: text.search.clear })).toBeNull();
  });

  it("date range narrows the list", async () => {
    await openSearch();
    fireEvent.change(screen.getByLabelText(text.search.from), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText(text.search.to), { target: { value: "2026-10-31" } });
    expect(renderedTitles()).toEqual(["Planning meeting"]);
  });

  it("changing the order reorders the list", async () => {
    await openSearch();
    const sort = screen.getByLabelText(text.search.sort);

    fireEvent.change(sort, { target: { value: "oldest" } });
    expect(renderedTitles()).toEqual(["Client interview", "Planning meeting", "Closing notes"]);

    fireEvent.change(sort, { target: { value: "title" } });
    expect(renderedTitles()).toEqual(["Client interview", "Closing notes", "Planning meeting"]);
  });

  it("shows the no-match message when nothing matches", async () => {
    await openSearch();
    fireEvent.change(screen.getByLabelText(text.search.text), { target: { value: "zzzz" } });
    expect(screen.getByText(text.noMatch)).toBeDefined();
    expect(screen.queryByRole("list", { name: text.listLabel })).toBeNull();
  });
});
