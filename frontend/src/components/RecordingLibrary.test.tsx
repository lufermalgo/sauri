// @vitest-environment jsdom
/**
 * Recording library: truthful list, states, and client-side search.
 *
 * Spec: portal-visual-design — PV4.2 (Property 2) and PV9.2.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, waitFor, fireEvent, within } from "@testing-library/react";
import { FailureCause, ProcessState, MeetingOrigin } from "@sauri/shared-types";
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

/** The search card only exists once the list has loaded. */
async function listLoaded() {
  await screen.findByRole("search");
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

    fireEvent.change(screen.getByLabelText(text.search.text), { target: { value: "o" } });
    expect(screen.queryAllByRole("heading", { level: 2 })).toHaveLength(0);
    expect(screen.getByRole("list", { name: text.listLabel })).toBeDefined();
    expect(renderedTitles()).toHaveLength(5);

    fireEvent.click(screen.getByRole("button", { name: text.search.clear }));
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(3);
  });

  it("shows a flat list when the order is not the default", async () => {
    vi.spyOn(api, "listMeetings").mockResolvedValue(dated);
    renderLibrary();
    await listLoaded();

    fireEvent.change(screen.getByLabelText(text.search.sort), { target: { value: "oldest" } });
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
