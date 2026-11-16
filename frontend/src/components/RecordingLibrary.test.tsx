// @vitest-environment jsdom
/**
 * Recording library: truthful list, states, and client-side search.
 *
 * Spec: portal-visual-design — PV4.2 (Property 2) and PV9.2.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, waitFor, fireEvent, within } from "@testing-library/react";
import { FailureCause, ProcessState, MeetingOrigin } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";

import { RecordingLibrary } from "./RecordingLibrary";
import { LIBRARY_CHANGED_EVENT } from "../library-events";
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
    thumbnailUrl: null,
    mediaKind: null,
    ...overrides,
  };
}

function renderLibrary(onSelectMeeting = vi.fn()) {
  render(<RecordingLibrary refreshKey={0} onSelectMeeting={onSelectMeeting} />);
  return onSelectMeeting;
}

/** The search card only exists once the list has loaded. */
async function listLoaded() {
  await screen.findByRole("search");
}

const search = text.search;

/** The search field, expanding it first when it is still the collapsed icon. */
function searchBox(): HTMLInputElement {
  if (!screen.queryByRole("searchbox")) fireEvent.click(screen.getByRole("button", { name: search.text }));
  return screen.getByRole("searchbox", { name: search.text }) as HTMLInputElement;
}

function typeSearch(value: string) {
  fireEvent.change(searchBox(), { target: { value } });
}

function datesButton(): HTMLElement {
  return screen.getByRole("button", { name: /^Fechas/ });
}

function setDates(from: string, to: string) {
  if (!screen.queryByRole("dialog", { name: search.dates })) fireEvent.click(datesButton());
  fireEvent.change(screen.getByLabelText(search.from), { target: { value: from } });
  fireEvent.change(screen.getByLabelText(search.to), { target: { value: to } });
}

function sortButton(): HTMLElement {
  return screen.getByRole("button", { name: /^Ordenar/ });
}

function chooseSort(label: string) {
  fireEvent.click(sortButton());
  fireEvent.click(screen.getByRole("menuitemradio", { name: label }));
}

function renderedTitles(): string[] {
  return screen.getAllByRole("button")
    .map((button) => button.querySelector(".library-item-title")?.textContent)
    .filter((title): title is string => typeof title === "string");
}

/** ISO string of a local date/time, so grouping does not depend on the machine time zone. */
function localIso(year: number, month: number, day: number, hour = 10, minute = 0): string {
  return new Date(year, month - 1, day, hour, minute).toISOString();
}

describe("RecordingLibrary list", () => {
  it("keeps the order received from the API within a group", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "b", title: "Second by name", createdAt: "2026-01-02T10:00:00Z" }),
      meeting({ id: "a", title: "First by name", createdAt: "2026-01-01T10:00:00Z" }),
      meeting({ id: "c", title: "Third by name", createdAt: "2026-01-03T10:00:00Z" }),
    ]);
    renderLibrary();
    await screen.findByRole("heading", { name: text.title });
    await listLoaded();

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
    await listLoaded();

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

  it("the header upload button has a plus icon and is the primary action", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([meeting()]);
    renderLibrary();
    await listLoaded();
    const button = screen.getByRole("button", { name: text.upload });
    expect(button.className).toContain("ui-button--primary");
    expect(button.querySelector("svg")).not.toBeNull();
  });

  it("treats a null title from the API as untitled", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ title: null as unknown as string }),
    ]);
    renderLibrary();
    expect(await screen.findByText(text.untitled)).toBeDefined();
    typeSearch("x");
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
    await listLoaded();

    fireEvent.click(screen.getByRole("button", { name: text.upload }));
    expect(window.location.pathname).toBe("/upload");
  });

  it("shows a loading status and an aria-hidden skeleton while the list is requested", async () => {
    vi.spyOn(api, "listMeetings").mockReturnValue(new Promise(() => {}));
    const { container } = render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);
    expect((await screen.findByRole("status")).textContent).toBe(text.loading);

    const skeleton = container.querySelector(".library-skeleton");
    expect(skeleton?.getAttribute("aria-hidden")).toBe("true");
    expect(skeleton?.querySelectorAll("li")).toHaveLength(3);
    expect(screen.queryByRole("search")).toBeNull();
  });

  it("removes the skeleton once the list has loaded", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([meeting()]);
    const { container } = render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);
    expect(container.querySelector(".library-skeleton")).not.toBeNull();

    await listLoaded();
    expect(container.querySelector(".library-skeleton")).toBeNull();
    expect(screen.queryByText(text.loading)).toBeNull();
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

describe("RecordingLibrary date groups", () => {
  beforeEach(() => {
    // Only Date is faked so Testing Library timers keep working.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 14, 12, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const dated = [
    meeting({ id: "old", title: "Old one", createdAt: localIso(2026, 10, 28) }),
    meeting({ id: "week", title: "Week one", createdAt: localIso(2026, 11, 12) }),
    meeting({ id: "now", title: "Today one", createdAt: localIso(2026, 11, 14, 9, 0) }),
    meeting({ id: "edge", title: "Six days ago", createdAt: localIso(2026, 11, 8) }),
    meeting({ id: "limit", title: "Seven days ago", createdAt: localIso(2026, 11, 7) }),
  ];

  function groupTitles(heading: string): string[] {
    const section = screen.getByRole("heading", { name: heading }).closest("section") as HTMLElement;
    return within(section).getAllByRole("button")
      .map((button) => button.querySelector(".library-item-title")?.textContent ?? "");
  }

  it("groups by local date under HOY, ESTA SEMANA and ANTERIORES in that order", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue(dated);
    renderLibrary();
    await listLoaded();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual([text.groups.today, text.groups.thisWeek, text.groups.earlier]);
    expect(groupTitles(text.groups.today)).toEqual(["Today one"]);
    expect(groupTitles(text.groups.thisWeek)).toEqual(["Week one", "Six days ago"]);
    expect(groupTitles(text.groups.earlier)).toEqual(["Old one", "Seven days ago"]);
  });

  it("does not show empty groups", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([dated[2]]);
    renderLibrary();
    await listLoaded();
    expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent))
      .toEqual([text.groups.today]);
  });

  it("puts recordings without a valid date under ANTERIORES", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "n", title: "No date", createdAt: null }),
      meeting({ id: "bad", title: "Bad date", createdAt: "not-a-date" }),
    ]);
    renderLibrary();
    await listLoaded();
    expect(groupTitles(text.groups.earlier)).toEqual(["No date", "Bad date"]);
  });

  it("shows a flat list without group headings while a search is active", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue(dated);
    renderLibrary();
    await listLoaded();

    typeSearch("o");
    expect(screen.queryAllByRole("heading", { level: 2 })).toHaveLength(0);
    expect(screen.getByRole("list", { name: text.listLabel })).toBeDefined();
    expect(renderedTitles()).toHaveLength(5);

    fireEvent.click(screen.getByRole("button", { name: search.clearFilters }));
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(3);
  });

  it("shows a flat list when the order is not the default", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue(dated);
    renderLibrary();
    await listLoaded();

    chooseSort(search.sortOldest);
    expect(screen.queryAllByRole("heading", { level: 2 })).toHaveLength(0);
  });
});

describe("RecordingLibrary row content", () => {
  async function openWith(items: MeetingListItem[]) {
    vi.spyOn(api, "listMeetings").mockResolvedValue(items);
    const view = render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);
    await listLoaded();
    return view;
  }

  it("shows the summary topic, the duration in mm:ss and the speaker count", async () => {
    await openWith([meeting({
      processState: ProcessState.Completed,
      summaryTopic: "Quarterly results and delivery plan",
      durationSeconds: 3260,
      speakerCount: 3,
    })]);
    expect(screen.getByText("Quarterly results and delivery plan")).toBeDefined();
    expect(screen.getByText("54:20").className).toContain("library-item-duration");
    expect(screen.getByText(text.speakers(3))).toBeDefined();
  });

  it("formats durations of an hour or more as h:mm:ss", async () => {
    await openWith([meeting({ durationSeconds: 3725 }), meeting({ id: "2", durationSeconds: 59 })]);
    expect(screen.getByText("1:02:05")).toBeDefined();
    expect(screen.getByText("00:59")).toBeDefined();
  });

  it("uses the singular for one speaker", async () => {
    await openWith([meeting({ speakerCount: 1 })]);
    expect(screen.getByText(text.speakers(1))).toBeDefined();
    expect(text.speakers(1)).not.toBe(text.speakers(2));
    expect(text.speakers(2)).toContain("2");
  });

  it("omits duration, speakers and topic when they are null", async () => {
    const { container } = await openWith([meeting({ processState: ProcessState.Completed })]);
    expect(container.querySelector(".library-item-duration")).toBeNull();
    expect(container.querySelector(".library-item-topic")).toBeNull();
    expect(container.textContent).not.toContain(text.speakers(2).slice(2));
  });

  it("falls back to a generating message for an in-progress recording without topic", async () => {
    await openWith([meeting({ processState: ProcessState.Transcribing })]);
    expect(screen.getByText(text.topicGenerating)).toBeDefined();
  });

  it("falls back to a failure message for a failed recording without topic", async () => {
    await openWith([meeting({ processState: ProcessState.Failed })]);
    expect(screen.getByText(text.topicFailed)).toBeDefined();
  });

  it("explains a recording without detected speech in its row, with no retry", async () => {
    await openWith([meeting({ processState: ProcessState.Failed, failureCause: FailureCause.NoSpeechDetected })]);
    expect(screen.getByText(text.topicNoSpeech)).toBeDefined();
    expect(screen.queryByText(text.topicFailed)).toBeNull();
    expect(screen.queryByRole("button", { name: text.retry })).toBeNull();
  });

  it("does not use a fallback line for a queued recording", async () => {
    const { container } = await openWith([meeting({ processState: ProcessState.Queued })]);
    expect(container.querySelector(".library-item-topic")).toBeNull();
  });

  it("prefers the real topic over the fallback", async () => {
    await openWith([meeting({ processState: ProcessState.Failed, summaryTopic: "Real topic" })]);
    expect(screen.getByText("Real topic")).toBeDefined();
    expect(screen.queryByText(text.topicFailed)).toBeNull();
  });

  it("colours the left edge by state", async () => {
    const { container } = await openWith([
      meeting({ id: "1", processState: ProcessState.Completed }),
      meeting({ id: "2", processState: ProcessState.Recording }),
      meeting({ id: "3", processState: ProcessState.Failed }),
      meeting({ id: "4", processState: ProcessState.Queued }),
    ]);
    const edges = Array.from(container.querySelectorAll(".library-item"))
      .map((item) => Array.from(item.classList).find((name) => name.startsWith("library-item--")));
    expect(edges).toEqual([
      "library-item--ready", "library-item--progress", "library-item--failed", "library-item--queued",
    ]);
  });
});

describe("RecordingLibrary as the list pane", () => {
  async function openPane(selectedId?: string) {
    vi.spyOn(api, "listMeetings").mockResolvedValue([
      meeting({ id: "a", title: "First", processState: ProcessState.Completed }),
      meeting({ id: "b", title: "Second", processState: ProcessState.Completed }),
    ]);
    const view = render(<RecordingLibrary refreshKey={0} selectedId={selectedId} onSelectMeeting={vi.fn()} />);
    await listLoaded();
    return view;
  }

  it("is a labelled pane whose header strip holds the title and the compact upload button", async () => {
    const { container } = await openPane();
    const pane = screen.getByRole("region", { name: text.title });
    expect(pane).toHaveClass("ui-pane");
    const header = container.querySelector(".ui-pane-header") as HTMLElement;
    expect(within(header).getByRole("heading", { level: 1, name: text.title })).toHaveClass("ui-pane-title");
    expect(within(header).getByRole("button", { name: text.upload })).toHaveClass("ui-button--primary", "ui-button--sm");
    // The icon toolbar sits right under the header strip and the rows scroll in the pane body.
    expect(header.nextElementSibling).toBe(screen.getByRole("search"));
    expect(container.querySelector(".ui-pane-body .library-item")).not.toBeNull();
  });

  it("marks only the open recording with aria-current", async () => {
    await openPane("b");
    expect(screen.getByRole("button", { name: /Second/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /First/ })).not.toHaveAttribute("aria-current");
  });

  it("marks nothing when no recording is open", async () => {
    const { container } = await openPane();
    expect(container.querySelector('.library-item[aria-current]')).toBeNull();
  });

  it("turns the list title into a plain label while a recording is open (one h1 per screen)", async () => {
    await openPane("a");
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: text.title })).toBeInTheDocument();
  });

  it("refreshes quietly when a recording is renamed or deleted elsewhere", async () => {
    const view = await openPane();
    const list = vi.spyOn(api, "listMeetings").mockResolvedValue([meeting({ id: "b", title: "Second renamed" })]);
    window.dispatchEvent(new Event(LIBRARY_CHANGED_EVENT));
    await waitFor(() => expect(screen.getByRole("button", { name: /Second renamed/ })).toBeDefined());
    expect(screen.queryByRole("button", { name: /First/ })).toBeNull();
    expect(list).toHaveBeenCalledTimes(1);
    // No loading state in between: the toolbar never left.
    expect(view.container.querySelector('[role="search"]')).not.toBeNull();
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
    await listLoaded();
  }

  it("typing filters by title (case insensitive) and the clear-filters icon restores", async () => {
    await openSearch();
    expect(screen.queryByRole("button", { name: search.clearFilters })).toBeNull();

    typeSearch("PLANNING");
    expect(renderedTitles()).toEqual(["Planning meeting"]);

    fireEvent.click(screen.getByRole("button", { name: search.clearFilters }));
    await waitFor(() => expect(renderedTitles()).toHaveLength(3));
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByRole("button", { name: search.clearFilters })).toBeNull();
  });

  it("date range narrows the list", async () => {
    await openSearch();
    setDates("2026-10-01", "2026-10-31");
    expect(renderedTitles()).toEqual(["Planning meeting"]);
  });

  it("changing the order reorders the list", async () => {
    await openSearch();

    chooseSort(search.sortOldest);
    expect(renderedTitles()).toEqual(["Client interview", "Planning meeting", "Closing notes"]);

    chooseSort(search.sortTitle);
    expect(renderedTitles()).toEqual(["Client interview", "Closing notes", "Planning meeting"]);
  });

  it("shows the no-match message when nothing matches", async () => {
    await openSearch();
    typeSearch("zzzz");
    expect(screen.getByText(text.noMatch)).toBeDefined();
    expect(screen.queryByRole("list", { name: text.listLabel })).toBeNull();
  });

  it("keeps the no-match message and the way out when only the date range excludes everything", async () => {
    await openSearch();
    setDates("2030-01-01", "2030-01-31");
    expect(screen.getByText(text.noMatch)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: search.clearFilters }));
    expect(renderedTitles()).toHaveLength(3);
  });
});

describe("RecordingLibrary toolbar", () => {
  const items = [
    meeting({ id: "1", title: "Planning meeting", createdAt: "2026-10-28T17:45:00Z" }),
    meeting({ id: "2", title: "Client interview", createdAt: "2026-09-10T15:00:00Z" }),
  ];

  async function openToolbar() {
    vi.spyOn(api, "listMeetings").mockResolvedValue(items);
    renderLibrary();
    await listLoaded();
  }

  function describedText(element: HTMLElement): string | null {
    const id = element.getAttribute("aria-describedby");
    return id ? document.getElementById(id)?.textContent ?? null : null;
  }

  it("starts as three icon buttons with an accessible name and a matching tooltip", async () => {
    await openToolbar();
    const toolbar = screen.getByRole("search", { name: search.regionLabel });
    const buttons = within(toolbar).getAllByRole("button");
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual([
      search.text, search.dates, search.sortCurrent(search.sortNewest),
    ]);
    for (const button of buttons) expect(describedText(button)).toBe(button.getAttribute("aria-label"));
    expect(toolbar.querySelector("input")).toBeNull();
    expect(screen.queryByLabelText(search.from)).toBeNull();
  });

  it("expands the search field with focus, keeps it while it has text and closes it with Escape", async () => {
    await openToolbar();
    fireEvent.click(screen.getByRole("button", { name: search.text }));
    const input = screen.getByRole("searchbox", { name: search.text });
    expect(document.activeElement).toBe(input);

    fireEvent.change(input, { target: { value: "plan" } });
    fireEvent.blur(input);
    expect(screen.getByRole("searchbox")).toBe(input);
    expect(renderedTitles()).toEqual(["Planning meeting"]);

    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(renderedTitles()).toHaveLength(2);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: search.text }));
  });

  it("the close button clears the term and collapses the field", async () => {
    await openToolbar();
    typeSearch("plan");
    fireEvent.click(screen.getByRole("button", { name: search.closeSearch }));
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(renderedTitles()).toHaveLength(2);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: search.text }));
  });

  it("an empty search field folds back into its icon when focus leaves it", async () => {
    await openToolbar();
    const input = searchBox();
    fireEvent.blur(input, { relatedTarget: document.body });
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.getByRole("button", { name: search.text })).toBeDefined();
  });

  it("keeps focus in the field while typing", async () => {
    await openToolbar();
    const input = searchBox();
    fireEvent.change(input, { target: { value: "p" } });
    fireEvent.change(input, { target: { value: "pl" } });
    expect(document.activeElement).toBe(screen.getByRole("searchbox"));
    expect(screen.getByRole("searchbox")).toBe(input);
  });

  it("the date popover is a non-modal dialog with two labeled dates and applies on change", async () => {
    await openToolbar();
    const trigger = datesButton();
    expect(trigger.getAttribute("aria-haspopup")).toBe("dialog");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: search.dates });
    expect(dialog.getAttribute("aria-modal")).toBeNull();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(screen.getByLabelText(search.from));
    expect((screen.getByLabelText(search.to) as HTMLInputElement).type).toBe("date");

    fireEvent.change(screen.getByLabelText(search.from), { target: { value: "2026-10-01" } });
    expect(renderedTitles()).toEqual(["Planning meeting"]);
  });

  it("shows the active range in the name and tooltip of the date icon and marks it active", async () => {
    await openToolbar();
    expect(datesButton().className).not.toContain("ui-icon-button--active");
    setDates("2026-11-01", "2026-11-15");
    const label = search.datesActive("01/11/2026", "15/11/2026");
    expect(label).toBe("Fechas: 01/11/2026 – 15/11/2026");
    const trigger = screen.getByRole("button", { name: label });
    expect(trigger.className).toContain("ui-icon-button--active");
    expect(describedText(trigger)).toBe(label);
  });

  it("names a one-sided range", async () => {
    await openToolbar();
    fireEvent.click(datesButton());
    fireEvent.change(screen.getByLabelText(search.from), { target: { value: "2026-10-01" } });
    expect(screen.getByRole("button", { name: "Fechas: desde 01/10/2026" })).toBeDefined();
  });

  it("the date popover's own Limpiar clears only the dates and returns focus to the icon", async () => {
    await openToolbar();
    typeSearch("e");
    setDates("2026-10-01", "2026-10-31");
    fireEvent.click(screen.getByRole("button", { name: search.clear }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: search.dates }));
    expect(screen.getByRole("searchbox")).toBeDefined();
    expect(renderedTitles()).toHaveLength(2);
  });

  it("opens the date popover with ArrowDown and closes it with Escape returning focus to the icon", async () => {
    await openToolbar();
    const trigger = datesButton();
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("dialog", { name: search.dates })).toBeDefined();
    fireEvent.keyDown(screen.getByLabelText(search.from), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("closes the date popover on a click outside without moving focus", async () => {
    await openToolbar();
    fireEvent.click(datesButton());
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the sort menu has radio items, checks the current one and applies a choice", async () => {
    await openToolbar();
    const trigger = sortButton();
    expect(trigger.getAttribute("aria-haspopup")).toBe("menu");
    fireEvent.click(trigger);
    const radios = screen.getAllByRole("menuitemradio");
    expect(radios.map((radio) => [radio.textContent, radio.getAttribute("aria-checked")])).toEqual([
      [search.sortNewest, "true"], [search.sortOldest, "false"], [search.sortTitle, "false"],
    ]);
    expect(radios[0].querySelector("svg")).not.toBeNull();
    expect(radios[1].querySelector("svg")).toBeNull();

    fireEvent.click(radios[2]);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: search.sortCurrent(search.sortTitle) }));
    expect(screen.getByRole("button", { name: search.sortCurrent(search.sortTitle) }).className)
      .toContain("ui-icon-button--active");
    expect(renderedTitles()).toEqual(["Client interview", "Planning meeting"]);
    fireEvent.click(sortButton());
    expect(screen.getByRole("menuitemradio", { name: search.sortTitle }).getAttribute("aria-checked")).toBe("true");
  });

  it("closes the sort menu with Escape and returns focus to the icon", async () => {
    await openToolbar();
    const trigger = sortButton();
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const first = screen.getAllByRole("menuitemradio")[0];
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("clear filters resets the search and dates but keeps the sort", async () => {
    await openToolbar();
    chooseSort(search.sortTitle);
    typeSearch("e");
    setDates("2026-10-01", "2026-10-31");
    expect(renderedTitles()).toEqual(["Planning meeting"]);

    fireEvent.click(screen.getByRole("button", { name: search.clearFilters }));
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(screen.queryByRole("button", { name: search.clearFilters })).toBeNull();
    expect(screen.getByRole("button", { name: search.dates })).toBeDefined();
    expect(renderedTitles()).toEqual(["Client interview", "Planning meeting"]);
    expect(screen.getByRole("button", { name: search.sortCurrent(search.sortTitle) })).toBeDefined();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: search.text }));
  });

  it("does not render the toolbar while loading, on error or with no recordings", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue([]);
    renderLibrary();
    await screen.findByText(text.empty);
    expect(screen.queryByRole("search")).toBeNull();
  });
});

describe("RecordingLibrary processing progress", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  async function openWith(items: MeetingListItem[]) {
    const list = vi.spyOn(api, "listMeetings").mockResolvedValue(items);
    const view = render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);
    await listLoaded();
    return { view, list };
  }

  it("shows the stage and an estimated percentage for a recording in transcription", async () => {
    const now = Date.now();
    // 20 min of audio: transcription 120 s, speakers 15 s, summary 144 s; 60 s in → ≈ 22 %.
    const { view } = await openWith([meeting({
      processState: ProcessState.Transcribing, durationSeconds: 1200,
      createdAt: new Date(now - 60_000).toISOString(),
    })]);
    const progress = view.container.querySelector(".library-item-progress") as HTMLElement;
    expect(progress.textContent).toBe(copy.processing.libraryProgress(copy.processing.steps.transcription, 22));
    const bar = within(progress).getByRole("progressbar", { name: copy.processing.libraryProgressLabel });
    expect(bar.getAttribute("aria-valuenow")).toBe("22");
  });

  it("says it is taking longer instead of a frozen percentage", async () => {
    const { view } = await openWith([meeting({
      processState: ProcessState.Queued, durationSeconds: 600, createdAt: new Date(Date.now() - 3_600_000).toISOString(),
    })]);
    expect(view.container.querySelector(".library-item-progress")?.textContent)
      .toBe(copy.processing.libraryOvertime(copy.processing.steps.transcription));
  });

  it("shows no estimate without a duration or for finished recordings", async () => {
    const { view } = await openWith([
      meeting({ id: "a", processState: ProcessState.Transcribing, durationSeconds: null }),
      meeting({ id: "b", processState: ProcessState.Completed, durationSeconds: 600 }),
    ]);
    expect(view.container.querySelector(".library-item-progress")).toBeNull();
    expect(view.container.textContent).not.toContain("%");
  });

  it("refreshes quietly every ten seconds only while a recording is in progress", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { list } = await openWith([meeting({ processState: ProcessState.Transcribing, durationSeconds: 600,
      createdAt: new Date().toISOString() })]);
    expect(list).toHaveBeenCalledTimes(1);
    list.mockResolvedValue([meeting({ processState: ProcessState.Completed, durationSeconds: 600 })]);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(list).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByText(text.states.completed)).toBeDefined());
    expect(screen.queryByText(text.loading)).toBeNull();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(list).toHaveBeenCalledTimes(2);
  });
});

describe("RecordingLibrary thumbnails", () => {
  const URL_A = "https://storage.invalid/a/thumbnail.jpg?sig=1";

  async function openWith(items: MeetingListItem[]) {
    const list = vi.spyOn(api, "listMeetings").mockResolvedValue(items);
    const view = render(<RecordingLibrary refreshKey={0} onSelectMeeting={vi.fn()} />);
    await listLoaded();
    return { view, list };
  }

  const thumb = (container: HTMLElement) => container.querySelector(".library-item-thumb") as HTMLElement;

  it("shows the preview frame as a decorative lazy image at the start of the row", async () => {
    const { view } = await openWith([meeting({ thumbnailUrl: URL_A, mediaKind: "video" })]);
    const image = thumb(view.container).querySelector("img") as HTMLImageElement;

    expect(image.getAttribute("src")).toBe(URL_A);
    expect(image.getAttribute("alt")).toBe("");
    expect(image.getAttribute("loading")).toBe("lazy");
    expect(thumb(view.container).querySelector("svg")).toBeNull();
    // The thumbnail is the first thing in the row button, before the title block.
    const button = view.container.querySelector("button.library-item") as HTMLElement;
    expect(button.firstElementChild).toBe(thumb(view.container));
  });

  it("shows the generic video tile when the frame is not available yet", async () => {
    const { view } = await openWith([meeting({ thumbnailUrl: null, mediaKind: "video" })]);

    expect(thumb(view.container).querySelector("img")).toBeNull();
    expect(thumb(view.container).querySelector("svg.lucide-video")).not.toBeNull();
  });

  it("shows the audio tile for recordings without video", async () => {
    const { view } = await openWith([meeting({ thumbnailUrl: null, mediaKind: "audio" })]);

    expect(thumb(view.container).querySelector("svg.lucide-audio-lines")).not.toBeNull();
    expect(thumb(view.container).querySelector("img")).toBeNull();
  });

  it("falls back to the generic tile when the image fails to load", async () => {
    const { view } = await openWith([meeting({ thumbnailUrl: URL_A, mediaKind: "video" })]);

    fireEvent.error(thumb(view.container).querySelector("img") as HTMLImageElement);

    await waitFor(() => expect(thumb(view.container).querySelector("img")).toBeNull());
    expect(thumb(view.container).querySelector("svg")).not.toBeNull();
  });

  it("adds no tab stop and no accessible name to the row", async () => {
    const { view } = await openWith([meeting({ thumbnailUrl: URL_A, mediaKind: "video" })]);

    expect(view.container.querySelectorAll("button.library-item")).toHaveLength(1);
    expect(thumb(view.container).querySelector("[tabindex], a, button")).toBeNull();
    expect(screen.getByRole("button", { name: /Synthetic meeting/ })).toBeDefined();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("keeps the same preview link across quiet refreshes so the image is not reloaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { view, list } = await openWith([
        meeting({ processState: ProcessState.Transcribing, thumbnailUrl: URL_A, mediaKind: "video" }),
      ]);
      list.mockResolvedValue([
        meeting({
          processState: ProcessState.Transcribing,
          thumbnailUrl: "https://storage.invalid/a/thumbnail.jpg?sig=2", mediaKind: "video",
        }),
      ]);

      await vi.advanceTimersByTimeAsync(10_000);

      expect(list).toHaveBeenCalledTimes(2);
      expect(thumb(view.container).querySelector("img")?.getAttribute("src")).toBe(URL_A);
    } finally {
      vi.useRealTimers();
    }
  });

  it("picks up a preview link that appears while the recording is still processing", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { view, list } = await openWith([
        meeting({ processState: ProcessState.Transcribing, thumbnailUrl: null, mediaKind: "video" }),
      ]);
      list.mockResolvedValue([
        meeting({ processState: ProcessState.Transcribing, thumbnailUrl: URL_A, mediaKind: "video" }),
      ]);

      await vi.advanceTimersByTimeAsync(10_000);

      await waitFor(() => expect(thumb(view.container).querySelector("img")?.getAttribute("src")).toBe(URL_A));
    } finally {
      vi.useRealTimers();
    }
  });
});
