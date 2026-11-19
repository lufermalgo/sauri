import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { NotesList } from "./NotesList";
import { panelCopy as copy } from "../../i18n/spanish";
import type { NoteDTO } from "../../core/types";
const notes: NoteDTO[] = [
  { meetingId: "r1", title: "Test A", processState: "completed", createdAt: "2024-05-01T10:00:00Z" },
  { meetingId: "r2", title: null, processState: "transcribing", createdAt: "2024-05-02T10:00:00Z" },
  { meetingId: "r3", title: "Test B", processState: "failed", createdAt: null },
];

beforeEach(() => {
  // The app was found on the desktop port earlier in this browser session.
  vi.stubGlobal("chrome", { storage: { session: { get: vi.fn(async () => ({ sauriBackendUrl: "http://localhost:41750" })) } } });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("NotesList approved library", () => {
  it.each([ ["loading", copy.loading], ["empty", copy.empty], ["error", copy.listError] ] as const)("renders %s", (state, text) => {
    render(<NotesList state={state} notes={[]} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
  it("renders sorted recordings, localized fallback and truthful states without invented progress", async () => {
    render(<NotesList state="withData" notes={notes} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText(copy.untitled)).toBeInTheDocument();
    for (const label of [copy.ready, copy.transcribing, copy.failed]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: copy.portal })).toHaveAttribute("href", "http://localhost:41750/");
  });
  it("filters the loaded list from an inline search and restores it when closed", () => {
    render(<NotesList state="withData" notes={notes} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: copy.search });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const field = screen.getByRole("searchbox", { name: copy.searchField });
    expect(field).toHaveFocus();
    fireEvent.change(field, { target: { value: "test b" } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Test B")).toBeInTheDocument();
    fireEvent.change(field, { target: { value: "zzz" } });
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(copy.noResults);
    fireEvent.keyDown(field, { key: "Escape" });
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(toggle).toHaveFocus();
  });
  it("matches the fallback title and offers search only when there is a list", async () => {
    const view = render(<NotesList state="withData" notes={notes} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: copy.search }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: copy.untitled.toLowerCase() } });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    view.rerender(<NotesList state="empty" notes={[]} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    expect(screen.queryByRole("button", { name: copy.search })).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: copy.portal })).toBeInTheDocument();
  });
  it("hides the portal link while no Sauri app answers", async () => {
    vi.resetModules();
    vi.stubGlobal("chrome", { storage: { session: { get: vi.fn(async () => ({})), set: vi.fn(), remove: vi.fn() } } });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("connection refused"); }));
    const { NotesList: Fresh } = await import("./NotesList");
    render(<Fresh state="empty" notes={[]} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("link", { name: copy.portal })).not.toBeInTheDocument();
  });
  it("opens the selected recording and retries a failed list request", () => {
    const onOpenNote = vi.fn(), onRetry = vi.fn();
    const view = render(<NotesList state="withData" notes={notes} onRetry={onRetry} onOpenNote={onOpenNote} />);
    fireEvent.click(screen.getByText("Test A"));
    expect(onOpenNote).toHaveBeenCalledWith("r1");
    view.rerender(<NotesList state="error" notes={[]} onRetry={onRetry} onOpenNote={onOpenNote} />);
    fireEvent.click(screen.getByRole("button", { name: copy.retry }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("NotesList in English", () => {
  it("shows the English texts and the date in the language's order", async () => {
    const { setLanguage } = await import("../../i18n");
    await setLanguage("en", { persist: false });
    render(<NotesList state="withData" notes={notes} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    expect(screen.getByText("Untitled recording")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "My recordings" })).toBeInTheDocument();
    for (const label of ["Ready", "Transcribing", "Failed"]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(/^5\/1, \d{1,2}:\d{2}\s?(AM|PM)$/i)).toBeInTheDocument();
  });
});
