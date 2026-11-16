import type { MeetingDiarization, MeetingTranscript, SpeakerReview } from "./api";
import { groupTranscriptTurns, type PresentationTurn } from "./transcript-turns";
import { t } from "./i18n";

export const UNRESOLVED_SPEAKER_COLOR = "var(--ds-speaker-unresolved)";

export function speakerColor(diarization: MeetingDiarization | null, speakerId: string | undefined): string {
  const sequence = diarization?.speakers.find((speaker) => speaker.id === speakerId)?.sequence;
  if (sequence === undefined) return UNRESOLVED_SPEAKER_COLOR;
  return `var(--ds-speaker-${(Math.max(1, sequence) - 1) % 6 + 1})`;
}

export function displaySpeakerLabel(label: string, speakerId: string | undefined, review: SpeakerReview | null): string {
  const disposition = review?.items.find(item => item.speakerId === speakerId)?.disposition;
  const number = /^Speaker (\d+)$/.exec(label)?.[1];
  return number && disposition !== "named" && disposition !== "corrected"
    ? t("transcript:numberedSpeaker", { number }) : label;
}

export type PresentedTurn = PresentationTurn & { color: string; hasAmbiguous: boolean };

/**
 * The turns the transcript shows (and the text export contains): merged by speaker, with the names
 * the reviewer chose. Shared by the meeting view and the library's download actions.
 */
export function presentTranscriptTurns(
  data: MeetingTranscript,
  diarization: MeetingDiarization | null,
  review: SpeakerReview | null,
): PresentedTurn[] {
  if (data.presentation === "words") return data.turns.map((turn) => ({
    id: turn.id,
    sourceIds: [turn.id],
    text: turn.text,
    timestampMs: turn.startMs,
    sequence: turn.sequence,
    speakerId: turn.speakerId ?? undefined,
    speakerLabel: displaySpeakerLabel(
      (turn.speakerId ? review?.labelsBySpeakerId[turn.speakerId]?.trim() : undefined) ||
        turn.speakerLabel || t("transcript:unknownSpeaker"), turn.speakerId ?? undefined, review),
    hasAmbiguous: turn.hasAmbiguous ?? false,
    color: speakerColor(diarization, turn.speakerId ?? undefined),
  }));
  return groupTranscriptTurns(
    data.turns,
    new Map(diarization?.assignments.map(({ turn_id, speaker_id }) => [turn_id, speaker_id]) ?? []),
  ).map((turn) => {
    const speaker = diarization?.speakers.find((candidate) => candidate.id === turn.speakerId);
    const reviewedLabel = turn.speakerId ? review?.labelsBySpeakerId[turn.speakerId]?.trim() : undefined;
    return {
      ...turn,
      speakerLabel: displaySpeakerLabel(reviewedLabel || speaker?.label || t("transcript:legacyUnknownSpeaker"), turn.speakerId, review),
      color: speakerColor(diarization, turn.speakerId),
      hasAmbiguous: false,
    };
  });
}
