// Example-based test: Notes_List, Note_Card, Search and Filter (Req. 4, 5)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { NotesList } from "./NotesList";
import type { NoteDTO } from "../../core/types";

const notes: NoteDTO[] = [
  { meetingId: "r1", title: "Meeting with client A", processState: "completed", createdAt: "2024-05-01T10:00:00Z" },
  { meetingId: "r2", title: null, processState: "completed", createdAt: "2024-05-02T10:00:00Z" },
];

describe("NotesList", () => {
  it("shows the 'loading' ViewState while waiting (Req. 4.7)", () => {
    render(<NotesList state="loading" notes={[]} onRetry={() => {}} onOpenNote={() => {}} onDeleteNote={() => {}} onRenameNote={() => {}} />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders one Note_Card per Note with title/placeholder and date (Req. 4.2-4.5)", () => {
    render(<NotesList state="withData" notes={notes} onRetry={() => {}} onOpenNote={() => {}} onDeleteNote={() => {}} onRenameNote={() => {}} />);
    expect(screen.getByText("Meeting with client A")).toBeInTheDocument();
    expect(screen.getByText(/untitled note/i)).toBeInTheDocument();
    expect(screen.getAllByText(/, \d{2}:\d{2}/).length).toBe(2);
  });

  it("the 'empty' ViewState invites the user to create the first note (Req. 4.8)", () => {
    render(<NotesList state="empty" notes={[]} onRetry={() => {}} onOpenNote={() => {}} onDeleteNote={() => {}} onRenameNote={() => {}} />);
    expect(screen.getByText(/first note/i)).toBeInTheDocument();
  });

  it("the 'error' ViewState offers a retry (Req. 4.9)", () => {
    const onRetry = vi.fn();
    render(<NotesList state="error" notes={[]} onRetry={onRetry} onOpenNote={() => {}} onDeleteNote={() => {}} onRenameNote={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("filters by text after a 300ms debounce (Req. 5.1)", async () => {
    render(<NotesList state="withData" notes={notes} onRetry={() => {}} onOpenNote={() => {}} onDeleteNote={() => {}} onRenameNote={() => {}} />);
    const input = screen.getByPlaceholderText(/search/i);
    fireEvent.change(input, { target: { value: "client A" } });

    await waitFor(
      () => {
        expect(screen.queryByText(/untitled note/i)).not.toBeInTheDocument();
      },
      { timeout: 1000 }
    );
    expect(screen.getByText("Meeting with client A")).toBeInTheDocument();
  });

  it("opens the selected note (Req. 6.1)", () => {
    const onOpenNote = vi.fn();
    render(
      <NotesList
        state="withData"
        notes={notes}
        onRetry={() => {}}
        onOpenNote={onOpenNote}
        onDeleteNote={() => {}}
        onRenameNote={() => {}}
      />
    );
    fireEvent.click(screen.getByText("Meeting with client A"));
    expect(onOpenNote).toHaveBeenCalledWith("r1");
  });

  it("asks for confirmation and deletes the note when accepted (manage notes)", () => {
    const onDeleteNote = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <NotesList
        state="withData"
        notes={notes}
        onRetry={() => {}}
        onOpenNote={() => {}}
        onDeleteNote={onDeleteNote}
        onRenameNote={() => {}}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /delete meeting with client a/i }));
    expect(onDeleteNote).toHaveBeenCalledWith("r1");
    vi.restoreAllMocks();
  });

  it("does not delete the note if the user cancels the confirmation (manage notes)", () => {
    const onDeleteNote = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <NotesList
        state="withData"
        notes={notes}
        onRetry={() => {}}
        onOpenNote={() => {}}
        onDeleteNote={onDeleteNote}
        onRenameNote={() => {}}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /delete meeting with client a/i }));
    expect(onDeleteNote).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it("renames the note: edits the title and confirms with Save (manage notes)", () => {
    const onRenameNote = vi.fn();
    render(
      <NotesList
        state="withData"
        notes={notes}
        onRetry={() => {}}
        onOpenNote={() => {}}
        onDeleteNote={() => {}}
        onRenameNote={onRenameNote}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /rename meeting with client a/i }));
    const input = screen.getByLabelText(/rename meeting with client a/i);
    fireEvent.change(input, { target: { value: "New name" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(onRenameNote).toHaveBeenCalledWith("r1", "New name");
  });

  it("canceling the rename does not call onRenameNote (manage notes)", () => {
    const onRenameNote = vi.fn();
    render(
      <NotesList
        state="withData"
        notes={notes}
        onRetry={() => {}}
        onOpenNote={() => {}}
        onDeleteNote={() => {}}
        onRenameNote={onRenameNote}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /rename meeting with client a/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onRenameNote).not.toHaveBeenCalled();
    expect(screen.getByText("Meeting with client A")).toBeInTheDocument();
  });
});
