// Notes_List, Note_Card, Notes_Search, Notes_Filter — Req. 4, 5, 6.1
import React, { useEffect, useMemo, useState } from "react";
import { projectCards } from "../../core/notes";
import { sortNotes } from "../../core/order";
import { filterNotes } from "../../core/search";
import type { NoteDTO, ViewState, NotesFilter } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface NotesListProps {
  state: ViewState;
  notes: NoteDTO[];
  onRetry: () => void;
  onOpenNote: (meetingId: string) => void;
  onDeleteNote: (meetingId: string) => void;
  onRenameNote: (meetingId: string, newTitle: string) => void;
}

const DEBOUNCE_MS = 300;

export function NotesList({
  state,
  notes,
  onRetry,
  onOpenNote,
  onDeleteNote,
  onRenameNote,
}: NotesListProps) {
  const [inputText, setInputText] = useState("");
  const [debouncedText, setDebouncedText] = useState("");
  const [filter, setFilter] = useState<NotesFilter>({});
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [editedTitle, setEditedTitle] = useState("");

  const startRename = (meetingId: string, currentTitle: string) => {
    setRenamingId(meetingId);
    setEditedTitle(currentTitle);
  };

  const confirmRename = (meetingId: string) => {
    const newTitle = editedTitle.trim();
    if (newTitle.length > 0) {
      onRenameNote(meetingId, newTitle);
    }
    setRenamingId(null);
  };

  const confirmDelete = (meetingId: string) => {
    if (window.confirm("Delete this note? This action cannot be undone.")) {
      onDeleteNote(meetingId);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedText(inputText), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [inputText]);

  const filteredNotes = useMemo(
    () => sortNotes(filterNotes(notes, debouncedText, filter)),
    [notes, debouncedText, filter]
  );
  const cards = useMemo(() => projectCards(filteredNotes), [filteredNotes]);

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space2, padding: SPACING_TOKENS.space4 }}>
      <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textLg, margin: 0 }}>Mis Notas</h2>

      <input
        type="text"
        placeholder="Search notes..."
        maxLength={100}
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        style={{
          padding: SPACING_TOKENS.space2,
          borderRadius: RADIUS_TOKENS.radiusSm,
          border: `1px solid ${COLOR_TOKENS.textMuted}`,
        }}
      />

      <select
        aria-label="Filter notes by state"
        value={filter.processState ?? ""}
        onChange={(e) =>
          setFilter((f) => ({ ...f, processState: e.target.value || undefined }))
        }
      >
        <option value="">All states</option>
        <option value="queued">Queued</option>
        <option value="recording">Recording</option>
        <option value="transcribing">Transcribing</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
      </select>

      {state === "loading" && <p>Loading...</p>}

      {state === "error" && (
        <div>
          <p style={{ color: COLOR_TOKENS.error }}>Could not load note history.</p>
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}

      {state === "empty" && <p>You don't have any notes yet. Create your first note to get started.</p>}

      {state === "withData" && cards.length === 0 && (
        <p>No notes matched your search.</p>
      )}

      {state === "withData" && cards.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space2 }}>
          {cards.map((card) => (
            <li
              key={card.meetingId}
              style={{
                display: "flex",
                alignItems: "center",
                gap: SPACING_TOKENS.space1,
                background: COLOR_TOKENS.surface,
                borderRadius: RADIUS_TOKENS.radiusMd,
              }}
            >
              {renamingId === card.meetingId ? (
                <div
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    gap: SPACING_TOKENS.space1,
                    padding: SPACING_TOKENS.space3,
                  }}
                >
                  <input
                    type="text"
                    aria-label={`Rename ${card.displayedTitle}`}
                    autoFocus
                    value={editedTitle}
                    maxLength={512}
                    onChange={(e) => setEditedTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") confirmRename(card.meetingId);
                      if (e.key === "Escape") setRenamingId(null);
                    }}
                    style={{ flex: 1, padding: SPACING_TOKENS.space1, borderRadius: RADIUS_TOKENS.radiusSm }}
                  />
                  <button type="button" onClick={() => confirmRename(card.meetingId)}>
                    Save
                  </button>
                  <button type="button" onClick={() => setRenamingId(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => onOpenNote(card.meetingId)}
                    style={{
                      flex: 1,
                      textAlign: "left",
                      background: "none",
                      border: "none",
                      padding: SPACING_TOKENS.space3,
                      color: COLOR_TOKENS.text,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontWeight: TYPOGRAPHY_TOKENS.weightMedium }}>{card.displayedTitle}</div>
                    <div style={{ fontSize: TYPOGRAPHY_TOKENS.textSm, color: COLOR_TOKENS.textMuted }}>
                      {card.displayedDate}
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label={`Rename ${card.displayedTitle}`}
                    onClick={() => startRename(card.meetingId, card.displayedTitle)}
                    style={{ background: "none", border: "none", cursor: "pointer", padding: SPACING_TOKENS.space2 }}
                  >
                    ✏️
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${card.displayedTitle}`}
                    onClick={() => confirmDelete(card.meetingId)}
                    style={{ background: "none", border: "none", cursor: "pointer", padding: SPACING_TOKENS.space2 }}
                  >
                    🗑️
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
