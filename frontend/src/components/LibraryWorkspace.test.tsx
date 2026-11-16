// @vitest-environment jsdom
/**
 * Master-detail workspace: list pane + detail pane on wide screens, one at a time on narrow ones.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import { MeetingOrigin, ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { LibraryWorkspace, WORKSPACE_WIDE_QUERY } from "./LibraryWorkspace";
import * as api from "../api";
import { copy } from "../copy/es";

vi.mock("../api", () => ({
  getMeeting: vi.fn(),
  listMeetings: vi.fn(),
  getMeetingSummary: vi.fn(),
  getLatestSummaryRequest: vi.fn(),
  getTranscript: vi.fn(),
  getPlaybackManifest: vi.fn(),
  getDiarization: vi.fn(),
  getSpeakerReview: vi.fn(),
  submitSpeakerDisposition: vi.fn(),
  newIdempotencyKey: vi.fn(),
}));

function item(id: string, title: string): MeetingListItem {
  return {
    id, meetLink: null, origin: MeetingOrigin.Manual, processState: ProcessState.Completed, failureCause: null,
    createdAt: "2026-10-28T17:45:00Z", title, durationSeconds: 600, speakerCount: 2, summaryTopic: null,
    thumbnailUrl: null, mediaKind: "video",
  };
}

/** `matchMedia` for jsdom: only the wide-workspace query can match. */
function mockViewport(wide: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: wide && query === WORKSPACE_WIDE_QUERY,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

beforeEach(() => {
  vi.mocked(api.listMeetings).mockResolvedValue([item("a", "Weekly sync"), item("b", "Client interview")]);
  vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "b", processState: "completed" });
  vi.mocked(api.getMeetingSummary).mockResolvedValue(null);
  vi.mocked(api.getLatestSummaryRequest).mockResolvedValue(null);
  vi.mocked(api.getTranscript).mockRejectedValue(new Error("Error 404"));
  vi.mocked(api.getPlaybackManifest).mockResolvedValue(null as unknown as api.PlaybackManifest);
  vi.mocked(api.getSpeakerReview).mockResolvedValue(null as unknown as api.SpeakerReview);
  vi.mocked(api.getDiarization).mockResolvedValue({ speakers: [], assignments: [] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("LibraryWorkspace on a wide screen", () => {
  it("renders the list pane and the detail pane together when a meeting is open", async () => {
    mockViewport(true);
    render(<LibraryWorkspace meetingId="b" />);
    const list = await screen.findByRole("region", { name: copy.library.title });
    expect(await screen.findByRole("heading", { level: 1, name: "Client interview" })).toBeVisible();
    expect(list.closest(".workspace")).toHaveAttribute("data-layout", "split");
    expect(document.querySelector(".workspace-detail .meeting-view")).not.toBeNull();
    // The list pane stays beside the detail, so the detail has no back button.
    expect(screen.queryByRole("button", { name: copy.meeting.backToList })).not.toBeInTheDocument();
  });

  it("marks the open recording in the list and keeps one h1 for the screen", async () => {
    mockViewport(true);
    render(<LibraryWorkspace meetingId="b" />);
    const list = await screen.findByRole("region", { name: copy.library.title });
    const rows = (await within(list).findAllByRole("button", { name: /Weekly sync|Client interview/ }))
      .filter((row) => row.classList.contains("library-item"));
    const selected = rows.filter((row) => row.getAttribute("aria-current") === "true");
    expect(selected).toHaveLength(1);
    expect(selected[0]).toHaveTextContent("Client interview");
    await screen.findByRole("heading", { level: 1, name: "Client interview" });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(within(list).queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("opens a recording from the list without leaving the workspace", async () => {
    mockViewport(true);
    render(<LibraryWorkspace />);
    const list = await screen.findByRole("region", { name: copy.library.title });
    const row = (await within(list).findAllByRole("button", { name: /Weekly sync/ }))
      .find((button) => button.classList.contains("library-item"));
    fireEvent.click(row as HTMLElement);
    expect(window.location.pathname).toBe("/meetings/a");
  });

  it("shows a quiet hint in the detail pane when nothing is selected", async () => {
    mockViewport(true);
    render(<LibraryWorkspace />);
    await screen.findByRole("region", { name: copy.library.title });
    expect(screen.getByText(copy.library.selectHint)).toBeVisible();
    expect(document.querySelector(".meeting-view")).toBeNull();
    // With nothing open the list owns the only h1.
    expect(screen.getByRole("heading", { level: 1, name: copy.library.title })).toBeVisible();
  });

  it("gives each pane its own header strip", async () => {
    mockViewport(true);
    render(<LibraryWorkspace meetingId="b" />);
    const list = await screen.findByRole("region", { name: copy.library.title });
    await screen.findByRole("heading", { level: 1, name: "Client interview" });
    expect(list.querySelector(":scope > .ui-pane-header .ui-pane-title")).toHaveTextContent(copy.library.title);
    expect(within(list.querySelector(":scope > .ui-pane-header") as HTMLElement)
      .getByRole("button", { name: copy.library.upload })).toBeVisible();
    expect(document.querySelector(".workspace-detail > .meeting-view > .meeting-header")).not.toBeNull();
  });
});

describe("LibraryWorkspace on a narrow screen", () => {
  it("shows only the detail with a back button when a meeting is open", async () => {
    mockViewport(false);
    render(<LibraryWorkspace meetingId="b" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Client interview" })).toBeVisible();
    expect(screen.queryByRole("region", { name: copy.library.title })).not.toBeInTheDocument();
    expect(document.querySelector(".workspace")).toHaveAttribute("data-layout", "single");
    expect(screen.getByRole("button", { name: copy.meeting.backToList })).toBeVisible();
  });

  it("goes back to the list route from the back button", async () => {
    mockViewport(false);
    window.history.replaceState(null, "", "/meetings/b");
    render(<LibraryWorkspace meetingId="b" />);
    fireEvent.click(await screen.findByRole("button", { name: copy.meeting.backToList }));
    expect(window.location.pathname).toBe("/");
  });

  it("shows only the list, full width and without the hint, when nothing is open", async () => {
    mockViewport(false);
    render(<LibraryWorkspace />);
    await screen.findByRole("region", { name: copy.library.title });
    expect(screen.queryByText(copy.library.selectHint)).not.toBeInTheDocument();
    expect(document.querySelector(".workspace-detail")).toBeNull();
  });
});
