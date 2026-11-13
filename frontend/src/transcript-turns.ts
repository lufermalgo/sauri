export interface SourceTranscriptSegment {
  id: string;
  text: string;
  startMs: number | null;
  endMs: number | null;
  sequence: number;
}

export interface PresentationTurn {
  id: string;
  sourceIds: string[];
  text: string;
  timestampMs: number | null;
  sequence: number;
  speakerId?: string;
  speakerLabel: string;
}

export interface PlaybackInterval {
  id: string;
  presentationTurnId: string;
  startMs: number;
  endMs: number;
  text: string;
  sequence: number;
}

const UNKNOWN_SPEAKER_LABEL = "Speaker N";

function hasValidTiming(segment: SourceTranscriptSegment): segment is SourceTranscriptSegment & {
  startMs: number;
  endMs: number;
} {
  return (
    typeof segment.startMs === "number" &&
    Number.isFinite(segment.startMs) &&
    typeof segment.endMs === "number" &&
    Number.isFinite(segment.endMs) &&
    segment.startMs >= 0 &&
    segment.endMs > segment.startMs
  );
}

export function groupTranscriptTurns(
  segments: SourceTranscriptSegment[],
  speakerIdByTurnId: ReadonlyMap<string, string>,
): PresentationTurn[] {
  const orderedSegments = segments
    .map((segment, index) => ({ segment, index }))
    .sort((left, right) => left.segment.sequence - right.segment.sequence || left.index - right.index)
    .map(({ segment }) => segment);

  const turns: PresentationTurn[] = [];

  for (const segment of orderedSegments) {
    const candidateSpeakerId = speakerIdByTurnId.get(segment.id);
    const speakerId = candidateSpeakerId?.trim() ? candidateSpeakerId : undefined;
    const canGroup = speakerId !== undefined && hasValidTiming(segment);
    const previousTurn = turns.at(-1);
    const canAppend =
      canGroup &&
      previousTurn?.speakerId === speakerId &&
      previousTurn.sourceIds.length > 0 &&
      hasValidTiming(orderedSegments.find((source) => source.id === previousTurn.sourceIds.at(-1))!);

    if (canAppend && previousTurn) {
      previousTurn.sourceIds.push(segment.id);
      if (segment.text.trim()) {
        previousTurn.text = previousTurn.text ? `${previousTurn.text} ${segment.text}` : segment.text;
      }
      continue;
    }

    turns.push({
      id: segment.id,
      sourceIds: [segment.id],
      text: segment.text.trim() ? segment.text : "",
      timestampMs: segment.startMs,
      sequence: segment.sequence,
      ...(speakerId ? { speakerId } : {}),
      speakerLabel: UNKNOWN_SPEAKER_LABEL,
    });
  }

  return turns;
}

export function createPlaybackIntervals(
  segments: SourceTranscriptSegment[],
  turns: PresentationTurn[],
): PlaybackInterval[] {
  const presentationTurnIdBySourceId = new Map<string, string>();
  for (const turn of turns) {
    for (const sourceId of turn.sourceIds) {
      presentationTurnIdBySourceId.set(sourceId, turn.id);
    }
  }

  return segments
    .filter(hasValidTiming)
    .map((segment) => ({
      segment,
      presentationTurnId: presentationTurnIdBySourceId.get(segment.id),
    }))
    .filter((entry): entry is typeof entry & { presentationTurnId: string } => Boolean(entry.presentationTurnId))
    .sort((left, right) => left.segment.sequence - right.segment.sequence)
    .map(({ segment, presentationTurnId }) => ({
      id: segment.id,
      presentationTurnId,
      startMs: segment.startMs,
      endMs: segment.endMs,
      text: segment.text,
      sequence: segment.sequence,
    }));
}
