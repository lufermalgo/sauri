import type { MeetingDiarization, MeetingTranscript } from "./api";

export interface SpeakerReviewInterval {
  startMs: number;
  endMs: number;
  short: boolean;
}

// A natural pause between ASR turns is acceptable; a different/unknown speaker is not.
const MAX_PAUSE_MS = 250;
const REPRESENTATIVE_MS = 5000;
const MAX_LISTEN_MS = 20000;

export function representativeSpeakerInterval(
  turns: MeetingTranscript["turns"],
  assignments: MeetingDiarization["assignments"],
  speakerId: string,
): SpeakerReviewInterval | null {
  const speakerByTurn = new Map(assignments.map(({ turn_id, speaker_id }) => [turn_id, speaker_id]));
  const ordered = [...turns].sort((a, b) => a.sequence - b.sequence);
  const candidates: Array<{ startMs: number; endMs: number }> = [];
  let current: { startMs: number; endMs: number } | null = null;
  let lastStart = -1;
  let competingVoiceUntilMs = -1;

  for (let index = 0; index < ordered.length; index += 1) {
    const turn = ordered[index];
    const assigned = speakerByTurn.get(turn.id);
    const valid = Number.isFinite(turn.startMs) && Number.isFinite(turn.endMs) &&
      turn.startMs >= 0 && turn.endMs > turn.startMs && turn.startMs >= lastStart;
    if (!valid) {
      if (current) candidates.push(current);
      current = null;
      lastStart = -1;
      continue;
    }
    lastStart = turn.startMs;
    // A competing/unknown turn can extend across more than one subsequent ASR turn.
    const startMs = Math.max(turn.startMs, competingVoiceUntilMs);
    let endMs = turn.endMs;
    if (assigned === speakerId) {
      for (let nextIndex = index + 1; nextIndex < ordered.length; nextIndex += 1) {
        const next = ordered[nextIndex];
        if (speakerByTurn.get(next.id) !== speakerId && Number.isFinite(next.startMs)) {
          endMs = Math.min(endMs, next.startMs);
          break;
        }
      }
    }

    if (assigned !== speakerId || endMs <= startMs ||
      (current && startMs > current.endMs + MAX_PAUSE_MS)) {
      if (current) candidates.push(current);
      current = null;
    }
    if (assigned === speakerId && endMs > startMs) {
      if (!current) current = { startMs, endMs };
      else current.endMs = Math.max(current.endMs, endMs);
    } else if (assigned !== speakerId) {
      competingVoiceUntilMs = Math.max(competingVoiceUntilMs, turn.endMs);
    }
  }
  if (current) candidates.push(current);
  candidates.sort((a, b) => (b.endMs - b.startMs) - (a.endMs - a.startMs) || a.startMs - b.startMs);
  const best = candidates[0];
  if (!best) return null;
  return {
    startMs: best.startMs,
    endMs: Math.min(best.endMs, best.startMs + MAX_LISTEN_MS),
    short: best.endMs - best.startMs < REPRESENTATIVE_MS,
  };
}
