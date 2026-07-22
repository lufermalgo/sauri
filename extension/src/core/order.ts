// Deterministic orderings — Req. 4.6, 8.2, 10.4
import type { NoteDTO, InterventionDTO, SpeakingTimeEntry } from "./types";

/** Notes: desc. by createdAt, tie-break asc. by meetingId (Req. 4.6) */
export function sortNotes(notes: NoteDTO[]): NoteDTO[] {
  return [...notes].sort((a, b) => {
    const fa = a.createdAt ? new Date(a.createdAt).getTime() : 0;
    const fb = b.createdAt ? new Date(b.createdAt).getTime() : 0;
    if (fa !== fb) return fb - fa;
    return a.meetingId < b.meetingId ? -1 : a.meetingId > b.meetingId ? 1 : 0;
  });
}

/** Interventions: asc. by (start_ms, sequence) (Req. 8.2) */
export function sortInterventions(interventions: InterventionDTO[]): InterventionDTO[] {
  return [...interventions].sort((a, b) => {
    if (a.startMs !== b.startMs) return a.startMs - b.startMs;
    return a.sequence - b.sequence;
  });
}

/** SpeakingTimeView: desc. by timeMs, tie-break asc. by sequence (Req. 10.4) */
export function sortSpeakingTime(entries: SpeakingTimeEntry[]): SpeakingTimeEntry[] {
  return [...entries].sort((a, b) => {
    if (a.timeMs !== b.timeMs) return b.timeMs - a.timeMs;
    return a.speaker.sequence - b.speaker.sequence;
  });
}
