// SpeakingTime calculation — Req. 10.1, 10.2
import type { SpeechTurnDTO, SpeakerAssignmentDTO, SpeakerDTO, SpeakingTimeEntry } from "./types";

/** Sums (end_ms - start_ms) per Speaker; includes speakers with time 0 (Req. 10.1, 10.2) */
export function calculateSpeakingTime(
  turns: SpeechTurnDTO[],
  assignments: SpeakerAssignmentDTO[],
  speakers: SpeakerDTO[]
): SpeakingTimeEntry[] {
  const turnsById = new Map(turns.map((t) => [t.id, t]));

  return speakers.map((speaker) => {
    const turnIds = assignments
      .filter((a) => a.speakerId === speaker.id)
      .map((a) => a.turnId);

    const timeMs = turnIds.reduce((acc, turnId) => {
      const turn = turnsById.get(turnId);
      if (!turn) return acc;
      return acc + (turn.endMs - turn.startMs);
    }, 0);

    return { speaker, timeMs };
  });
}
