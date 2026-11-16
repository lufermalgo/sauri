// @vitest-environment jsdom
/**
 * The library list pane can be hidden from the side panel while a recording is open; the choice is
 * remembered per device and never applies on `/` or in single-pane (narrow) mode.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, fireEvent, act } from "@testing-library/react";
import { MeetingOrigin, ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { PortalShell } from "./PortalShell";
import { LibraryWorkspace } from "./LibraryWorkspace";
import { LIBRARY_PANE_STORAGE_KEY } from "./useLibraryPane";
import * as api from "../api";
import { copy } from "../copy/es";
import type { Route } from "../router";

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

type Listener = () => void;
let viewportWidth = 1440;
const listeners = new Set<Listener>();

function stubViewport(width: number) {
  viewportWidth = width;
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      const min = /min-width:\s*(\d+)/.exec(query);
      const max = /max-width:\s*(\d+)/.exec(query);
      return (min ? viewportWidth >= Number(min[1]) : true) && (max ? viewportWidth <= Number(max[1]) : true);
    },
    media: query,
    addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
  }));
}

function createLocalStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

function renderApp(route: Route = { name: "meeting", meetingId: "b" }) {
  const meetingId = route.name === "meeting" ? route.meetingId : undefined;
  return render(
    <PortalShell route={route} user={{ name: "Ana", email: "ana@example.test" }} onLogout={vi.fn()}>
      <LibraryWorkspace meetingId={meetingId} />
    </PortalShell>,
  );
}

const slot = () => document.querySelector<HTMLElement>(".workspace-list")!;
const toggle = () => screen.getByRole("button", { name: copy.shell.library });

beforeEach(() => {
  listeners.clear();
  stubViewport(1440);
  vi.stubGlobal("localStorage", createLocalStorage());
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
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("library pane toggle in the side panel", () => {
  it("is a button with the pane's state while a recording is open on a wide screen", async () => {
    renderApp();
    await screen.findByRole("region", { name: copy.library.title });
    expect(screen.queryByRole("link", { name: copy.shell.library })).toBeNull();
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(toggle().getAttribute("aria-controls")).toBe("library-pane");
    expect(document.getElementById("library-pane")).not.toBeNull();
    expect(slot()).not.toHaveAttribute("data-hidden");
  });

  it("hides the list pane and shows it again, keeping focus on the button and remembering the choice", async () => {
    renderApp();
    await screen.findByRole("region", { name: copy.library.title });
    const button = toggle();
    act(() => button.focus());

    fireEvent.click(button);
    expect(slot()).toHaveAttribute("data-hidden");
    expect(slot()).toHaveAttribute("aria-hidden", "true");
    expect(slot()).toHaveAttribute("inert");
    expect(screen.queryByRole("region", { name: copy.library.title })).toBeNull();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("1");
    // The detail stays open and takes the room.
    expect(await screen.findByRole("heading", { level: 1, name: "Client interview" })).toBeVisible();

    fireEvent.click(button);
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(slot()).not.toHaveAttribute("inert");
    expect(screen.getByRole("region", { name: copy.library.title })).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveFocus();
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("0");
  });

  it("describes the action with a tooltip: hide when shown, show when hidden", async () => {
    renderApp();
    await screen.findByRole("region", { name: copy.library.title });
    vi.useFakeTimers();
    const tipOf = () => document.getElementById(toggle().getAttribute("aria-describedby") ?? "") as HTMLElement;
    expect(tipOf()).toHaveTextContent(copy.shell.libraryPane.hide);
    expect(tipOf()).toHaveAttribute("role", "tooltip");
    fireEvent.mouseEnter(toggle());
    act(() => { vi.advanceTimersByTime(400); });
    expect(tipOf().hidden).toBe(false);

    fireEvent.click(toggle());
    expect(tipOf()).toHaveTextContent(copy.shell.libraryPane.show);
  });

  it("remembers a hidden list on the next visit", async () => {
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderApp();
    await screen.findByRole("heading", { level: 1, name: "Client interview" });
    expect(slot()).toHaveAttribute("data-hidden");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the list mounted while hidden, so its search and selection are still there", async () => {
    renderApp();
    const list = await screen.findByRole("region", { name: copy.library.title });
    fireEvent.click(screen.getByRole("checkbox", { name: copy.library.row.select("Weekly sync") }));
    fireEvent.click(toggle());
    expect(list.isConnected).toBe(true);
    fireEvent.click(toggle());
    expect(screen.getByRole("checkbox", { name: copy.library.row.select("Weekly sync") })).toBeChecked();
  });

  it("works for the visit when storage is blocked", async () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("localStorage", { ...createLocalStorage(), getItem: blocked, setItem: blocked });
    renderApp();
    await screen.findByRole("region", { name: copy.library.title });
    fireEvent.click(toggle());
    expect(slot()).toHaveAttribute("data-hidden");
    fireEvent.click(toggle());
    expect(slot()).not.toHaveAttribute("data-hidden");
  });

  it("is never hidden on the library route: the item is a link and the list is the content", async () => {
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderApp({ name: "library" });
    await screen.findByRole("region", { name: copy.library.title });
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(screen.getByRole("link", { name: copy.shell.library })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: copy.shell.library })).toBeNull();
    // Coming back to the list shows it again for the next recording too.
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("0");
  });

  it("is a plain link below 1100px, where the workspace has one pane at a time", async () => {
    stubViewport(900);
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderApp();
    await screen.findByRole("heading", { level: 1, name: "Client interview" });
    expect(screen.getByRole("link", { name: copy.shell.library })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("button", { name: copy.shell.library })).toBeNull();
    expect(screen.queryByRole("region", { name: copy.library.title })).toBeNull();
    expect(document.querySelector(".workspace-list")).toBeNull();
  });

  it("keeps its name Biblioteca in the rail, where only the icon shows", async () => {
    localStorage.setItem("sauri_sidebar_collapsed", "1");
    renderApp();
    await screen.findByRole("region", { name: copy.library.title });
    expect(document.querySelector(".shell-root")).toHaveAttribute("data-mode", "rail");
    expect(toggle()).toHaveAccessibleName(copy.shell.library);
  });
});
