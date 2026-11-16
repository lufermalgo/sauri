// @vitest-environment jsdom
/**
 * The library list pane can be hidden from the side panel, on `/` as well as with a recording open;
 * the choice is remembered per device and never applies in single-pane (narrow) mode.
 */

import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, fireEvent, act, within } from "@testing-library/react";
import { MeetingOrigin, ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { PortalShell } from "./PortalShell";
import { LibraryWorkspace } from "./LibraryWorkspace";
import { LIBRARY_PANE_STORAGE_KEY } from "./useLibraryPane";
import * as api from "../api";
import type { Route } from "../router";
import { t } from "../i18n";

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
const toggle = () => screen.getByRole("button", { name: t("shell:library") });

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
    await screen.findByRole("region", { name: t("library:title") });
    expect(screen.queryByRole("link", { name: t("shell:library") })).toBeNull();
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(toggle().getAttribute("aria-controls")).toBe("library-pane");
    expect(document.getElementById("library-pane")).not.toBeNull();
    expect(slot()).not.toHaveAttribute("data-hidden");
  });

  it("hides the list pane and shows it again, keeping focus on the button and remembering the choice", async () => {
    renderApp();
    await screen.findByRole("region", { name: t("library:title") });
    const button = toggle();
    act(() => button.focus());

    fireEvent.click(button);
    expect(slot()).toHaveAttribute("data-hidden");
    expect(slot()).toHaveAttribute("aria-hidden", "true");
    expect(slot()).toHaveAttribute("inert");
    expect(screen.queryByRole("region", { name: t("library:title") })).toBeNull();
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("1");
    // The detail stays open and takes the room.
    expect(await screen.findByRole("heading", { level: 1, name: "Client interview" })).toBeVisible();

    fireEvent.click(button);
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(slot()).not.toHaveAttribute("inert");
    expect(screen.getByRole("region", { name: t("library:title") })).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveFocus();
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("0");
  });

  it("describes the action with a tooltip: hide when shown, show when hidden", async () => {
    renderApp();
    await screen.findByRole("region", { name: t("library:title") });
    vi.useFakeTimers();
    const tipOf = () => document.getElementById(toggle().getAttribute("aria-describedby") ?? "") as HTMLElement;
    expect(tipOf()).toHaveTextContent(t("shell:libraryPane.hide"));
    expect(tipOf()).toHaveAttribute("role", "tooltip");
    fireEvent.mouseEnter(toggle());
    act(() => { vi.advanceTimersByTime(400); });
    expect(tipOf().hidden).toBe(false);

    fireEvent.click(toggle());
    expect(tipOf()).toHaveTextContent(t("shell:libraryPane.show"));
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
    const list = await screen.findByRole("region", { name: t("library:title") });
    fireEvent.click(screen.getByRole("checkbox", { name: t("library:row.select", { title: "Weekly sync" }) }));
    fireEvent.click(toggle());
    expect(list.isConnected).toBe(true);
    fireEvent.click(toggle());
    expect(screen.getByRole("checkbox", { name: t("library:row.select", { title: "Weekly sync" }) })).toBeChecked();
  });

  it("works for the visit when storage is blocked", async () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("localStorage", { ...createLocalStorage(), getItem: blocked, setItem: blocked });
    renderApp();
    await screen.findByRole("region", { name: t("library:title") });
    fireEvent.click(toggle());
    expect(slot()).toHaveAttribute("data-hidden");
    fireEvent.click(toggle());
    expect(slot()).not.toHaveAttribute("data-hidden");
  });

  it("is the same toggle on the library home, with the list as its target", async () => {
    renderApp({ name: "library" });
    await screen.findByRole("region", { name: t("library:title") });
    expect(screen.queryByRole("link", { name: t("shell:library") })).toBeNull();
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(toggle()).toHaveAttribute("aria-controls", "library-pane");
    expect(toggle()).toHaveAttribute("aria-current", "page");
    expect(slot()).not.toHaveAttribute("data-hidden");
    // The pane is visible by default, so the detail only carries the quiet hint.
    expect(screen.getByText(t("library:selectHint"))).toBeVisible();
    expect(screen.queryByRole("button", { name: t("shell:libraryPane.show") })).toBeNull();
  });

  it("hides the list on the library home and offers the way back in the empty state", async () => {
    renderApp({ name: "library" });
    await screen.findByRole("region", { name: t("library:title") });
    act(() => toggle().focus());
    fireEvent.click(toggle());
    expect(slot()).toHaveAttribute("data-hidden");
    expect(slot()).toHaveAttribute("inert");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(toggle()).toHaveFocus();
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("1");
    // The hidden list takes its h1 out of the tree; the empty state owns the only h1 and the button.
    expect(screen.getByRole("heading", { level: 1, name: t("library:chooseRecording") })).toBeVisible();
    expect(screen.queryByText(t("library:selectHint"))).toBeNull();
    expect(screen.getByRole("button", { name: t("shell:libraryPane.show") })).toBeVisible();
  });

  it("brings the list back from the empty state's button and moves the keyboard into it", async () => {
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderApp({ name: "library" });
    expect(await screen.findByRole("heading", { level: 1, name: t("library:chooseRecording") })).toBeVisible();
    // The stored choice is kept on the home: it is neither cleared nor forced visible.
    expect(slot()).toHaveAttribute("data-hidden");
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("1");

    fireEvent.click(screen.getByRole("button", { name: t("shell:libraryPane.show") }));
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("0");
    expect(screen.getByText(t("library:selectHint"))).toBeVisible();
    expect(screen.queryByRole("heading", { name: t("library:chooseRecording") })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: t("library:title") })).toBeVisible();
    const list = screen.getByRole("region", { name: t("library:title") });
    await within(list).findByText("Weekly sync");
    expect(list.contains(document.activeElement)).toBe(true);
  });

  it("keeps a hidden list hidden across the home and a recording", async () => {
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    const view = renderApp({ name: "library" });
    await screen.findByRole("heading", { level: 1, name: t("library:chooseRecording") });
    view.unmount();
    renderApp({ name: "meeting", meetingId: "b" });
    await screen.findByRole("heading", { level: 1, name: "Client interview" });
    expect(slot()).toHaveAttribute("data-hidden");
    expect(localStorage.getItem(LIBRARY_PANE_STORAGE_KEY)).toBe("1");
  });

  it("hides on the home when storage is blocked, for the visit", async () => {
    const blocked = () => { throw new Error("blocked"); };
    vi.stubGlobal("localStorage", { ...createLocalStorage(), getItem: blocked, setItem: blocked });
    renderApp({ name: "library" });
    await screen.findByRole("region", { name: t("library:title") });
    fireEvent.click(toggle());
    expect(await screen.findByRole("button", { name: t("shell:libraryPane.show") })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: t("shell:libraryPane.show") }));
    expect(slot()).not.toHaveAttribute("data-hidden");
  });

  it("ignores the stored choice below 1100px: the home shows the list alone, with no empty state", async () => {
    stubViewport(900);
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderApp({ name: "library" });
    await screen.findByRole("region", { name: t("library:title") });
    expect(slot()).not.toHaveAttribute("data-hidden");
    expect(screen.queryByRole("heading", { name: t("library:chooseRecording") })).toBeNull();
    expect(screen.getByRole("link", { name: t("shell:library") })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: t("shell:library") })).toBeNull();
  });

  it("is a plain link below 1100px, where the workspace has one pane at a time", async () => {
    stubViewport(900);
    localStorage.setItem(LIBRARY_PANE_STORAGE_KEY, "1");
    renderApp();
    await screen.findByRole("heading", { level: 1, name: "Client interview" });
    expect(screen.getByRole("link", { name: t("shell:library") })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("button", { name: t("shell:library") })).toBeNull();
    expect(screen.queryByRole("region", { name: t("library:title") })).toBeNull();
    expect(document.querySelector(".workspace-list")).toBeNull();
  });

  it("keeps its name Biblioteca in the rail, where only the icon shows", async () => {
    localStorage.setItem("sauri_sidebar_collapsed", "1");
    renderApp();
    await screen.findByRole("region", { name: t("library:title") });
    expect(document.querySelector(".shell-root")).toHaveAttribute("data-mode", "rail");
    expect(toggle()).toHaveAccessibleName(t("shell:library"));
  });
});
