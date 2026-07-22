// Search filters — Req. 5, 9
import type { NoteDTO, InterventionDTO, NotesFilter } from "./types";

export const NOTES_SEARCH_LIMIT = 100;
export const TRANSCRIPT_SEARCH_LIMIT = 200;

function normalize(text: string): string {
  return text.trim().toLowerCase();
}

/** Filters Notes by conjunction of title text and criteria (Req. 5.1, 5.2, 5.3, 5.4, 5.6, 5.7) */
export function filterNotes(
  notes: NoteDTO[],
  text: string,
  filter: NotesFilter
): NoteDTO[] {
  const boundedText = (text ?? "").slice(0, NOTES_SEARCH_LIMIT);
  const normText = normalize(boundedText);
  const searchActive = normText.length > 0;

  return notes.filter((note) => {
    if (searchActive) {
      const normTitle = normalize(note.title ?? "");
      if (!normTitle.includes(normText)) return false;
    }
    if (filter.processState && note.processState !== filter.processState) return false;
    if (filter.from && note.createdAt && new Date(note.createdAt) < new Date(filter.from)) return false;
    if (filter.to && note.createdAt && new Date(note.createdAt) > new Date(filter.to)) return false;
    return true;
  });
}

export interface TranscriptSearchResult {
  interventions: InterventionDTO[];
  matchingTurnIds: string[];
  firstMatchId: string | null;
}

/** Searches for matches within Interventions without altering order/set (Req. 9.1, 9.2, 9.3, 9.4, 9.5) */
export function transcriptMatches(
  interventions: InterventionDTO[],
  text: string
): TranscriptSearchResult {
  const boundedText = (text ?? "").slice(0, TRANSCRIPT_SEARCH_LIMIT);
  const normText = boundedText.trim().toLowerCase();

  if (normText.length === 0) {
    return { interventions, matchingTurnIds: [], firstMatchId: null };
  }

  const matches = interventions.filter((i) => i.text.toLowerCase().includes(normText));
  let firstMatchId: string | null = null;
  if (matches.length > 0) {
    const first = matches.reduce((min, i) => (i.startMs < min.startMs ? i : min));
    firstMatchId = first.turnId;
  }

  return {
    interventions,
    matchingTurnIds: matches.map((i) => i.turnId),
    firstMatchId,
  };
}
