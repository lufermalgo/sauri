// Note title, date, and card projection — Req. 4.2, 4.3, 4.4, 4.5, 7.5
import type { NoteDTO, NoteCard } from "./types";

export const TITLE_PLACEHOLDER = "Untitled note";

/** Returns the original title if non-blank, or a placeholder (Req. 4.4, 7.5) */
export function displayTitle(title: string | null | undefined): string {
  if (title === null || title === undefined) return TITLE_PLACEHOLDER;
  if (title.trim().length === 0) return TITLE_PLACEHOLDER;
  return title;
}

/** Formats an ISO-8601 date as "D/M, HH:MM" (Req. 4.5) */
export function formatNoteDate(createdAt: string): string {
  const date = new Date(createdAt);
  const day = date.getDate();
  const month = date.getMonth() + 1;
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${day}/${month}, ${hours}:${minutes}`;
}

/** Projects Notes to Cards (1:1 by meetingId) — Req. 4.2, 4.3 */
export function projectCards(notes: NoteDTO[]): NoteCard[] {
  return notes.map((note) => ({
    meetingId: note.meetingId,
    displayedTitle: displayTitle(note.title),
    displayedDate: note.createdAt ? formatNoteDate(note.createdAt) : "--/--, --:--",
    processState: note.processState,
    createdAt: note.createdAt,
  }));
}
