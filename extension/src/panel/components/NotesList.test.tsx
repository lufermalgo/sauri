import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { NotesList } from "./NotesList";
import { panelCopy as copy } from "../copy";
import type { NoteDTO } from "../../core/types";
const notes: NoteDTO[] = [
  { meetingId: "r1", title: "Test A", processState: "completed", createdAt: "2024-05-01T10:00:00Z" },
  { meetingId: "r2", title: null, processState: "transcribing", createdAt: "2024-05-02T10:00:00Z" },
  { meetingId: "r3", title: "Test B", processState: "failed", createdAt: null },
];

describe("NotesList approved library", () => {
  it.each([ ["loading", copy.loading], ["empty", copy.empty], ["error", copy.listError] ] as const)("renders %s", (state, text) => {
    render(<NotesList state={state} notes={[]} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
  it("renders sorted recordings, localized fallback and truthful states without invented progress", () => {
    render(<NotesList state="withData" notes={notes} onRetry={vi.fn()} onOpenNote={vi.fn()} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText(copy.untitled)).toBeInTheDocument();
    for (const label of [copy.ready, copy.transcribing, copy.failed]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.portal })).toHaveAttribute("href", "http://localhost:5173/");
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
