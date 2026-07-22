// Mapping of SpeechTurns to Interventions and speaker attribution — Req. 8.1, 8.3, 8.5, 8.7, 14.2
import type {
  TranscriptDTO,
  SpeechTurnDTO,
  SpeakerAssignmentDTO,
  SpeakerDTO,
  InterventionDTO,
} from "./types";

export const UNIDENTIFIED_SPEAKER_LABEL = "Unidentified speaker";

/** Joins a SpeechTurn with its assigned Speaker (or null if unassigned) — Req. 8.3, 8.7 */
export function attributeSpeaker(
  turn: SpeechTurnDTO,
  assignments: SpeakerAssignmentDTO[],
  speakers: SpeakerDTO[]
): InterventionDTO {
  const assignment = assignments.find((a) => a.turnId === turn.id);
  const speaker = assignment
    ? speakers.find((h) => h.id === assignment.speakerId) ?? null
    : null;

  return {
    turnId: turn.id,
    text: turn.text,
    startMs: turn.startMs,
    endMs: turn.endMs,
    sequence: turn.sequence,
    speaker,
  };
}

/** Maps all SpeechTurns of a Transcript to Interventions (without attribution) — Req. 8.1, 8.5, 14.2 */
export function mapInterventions(transcript: TranscriptDTO): InterventionDTO[] {
  return transcript.segments.map((turn) => ({
    turnId: turn.id,
    text: turn.text,
    startMs: turn.startMs,
    endMs: turn.endMs,
    sequence: turn.sequence,
    speaker: null,
  }));
}
