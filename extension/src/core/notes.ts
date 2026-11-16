// Note title, date, and card projection — Req. 4.2, 4.3, 4.4, 4.5, 7.5
import type { NoteDTO, NoteCard } from "./types";

export const TITLE_PLACEHOLDER = "Untitled note";

/** Returns the original title if non-blank, or a placeholder (Req. 4.4, 7.5) */
export function displayTitle(title: string | null | undefined): string {
  if (title === null || title === undefined) return TITLE_PLACEHOLDER;
  if (title.trim().length === 0) return TITLE_PLACEHOLDER;
  return title;
}

/** Formats an ISO-8601 date as day/month and time in the given language ("5/3, 14:07" / "3/5, 2:07 PM") (Req. 4.5) */
export function formatNoteDate(createdAt: string, locale = "es"): string {
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(createdAt));
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
