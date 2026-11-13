import type { MeetingDiarization } from "./api";

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


/** All-or-nothing validation: never combine v2 pieces with v1 identity guesses. */
export function projectTranscript(
  segments: SourceTranscriptSegment[], diarization: MeetingDiarization | null, transcriptId: string,
): { turns: PresentationTurn[]; intervals: PlaybackInterval[] } | null {
  const projection = diarization?.presentation;
  if (projection == null) return null;
  const fallback = () => {
    const turns = groupTranscriptTurns(segments, new Map());
    return { turns, intervals: createPlaybackIntervals(segments, turns) };
  };
  if (projection.version !== 2 || projection.policy_version !== "exclusive-source-v1"
      || !Number.isInteger(projection.processing_revision) || projection.processing_revision < 1
      || projection.transcript_id !== transcriptId
      || projection.transcript_id !== diarization?.transcript_id
      || projection.diarization_id !== diarization?.diarization_id
      || projection.processing_revision !== diarization?.processing_revision
      || !Array.isArray(projection.pieces)) return fallback();
  const ordered = [...segments].sort((a, b) => a.sequence - b.sequence);
  const byId = new Map(ordered.map((source, order) => [source.id, { source, order }]));
  const offsets = new Map(ordered.map((source) => [source.id, 0]));
  const speakerIds = new Set(diarization?.speakers.map((s) => s.id));
  const turns: PresentationTurn[] = [];
  const intervals: PlaybackInterval[] = [];
  let lastOrder = -1;
  for (const piece of projection.pieces) {
    if (!piece || typeof piece !== "object") return fallback();
    const entry = byId.get(piece.source_turn_id);
    if (!entry || entry.order < lastOrder || !hasValidTiming(entry.source)
        || !Number.isInteger(piece.char_start) || !Number.isInteger(piece.char_end)
        || piece.char_start !== offsets.get(piece.source_turn_id)
        || piece.char_end <= piece.char_start || piece.char_end > Array.from(entry.source.text).length
        || (piece.speaker_id !== null && !speakerIds.has(piece.speaker_id))
        || !Array.isArray(piece.intervals) || !piece.intervals.length) return fallback();
    lastOrder = entry.order;
    const id = `${entry.source.id}:${piece.char_start}:${piece.char_end}`;
    const text = Array.from(entry.source.text).slice(piece.char_start, piece.char_end).join("");
    const previousTurn = turns.at(-1);
    const append = piece.speaker_id !== null && previousTurn?.speakerId === piece.speaker_id;
    const presentationTurnId = append && previousTurn ? previousTurn.id : id;
    let previousEnd = -1;
    for (const [index, interval] of piece.intervals.entries()) {
      if (!interval || !Number.isInteger(interval.start_ms) || !Number.isInteger(interval.end_ms)
          || interval.start_ms < entry.source.startMs || interval.end_ms > entry.source.endMs
          || interval.start_ms >= interval.end_ms || interval.start_ms <= previousEnd) return fallback();
      previousEnd = interval.end_ms;
      intervals.push({ id: `${id}:${index}`, presentationTurnId, text,
        startMs: interval.start_ms, endMs: interval.end_ms, sequence: intervals.length + 1 });
    }
    offsets.set(piece.source_turn_id, piece.char_end);
    if (append && previousTurn) {
      const sameSource = previousTurn.sourceIds.at(-1) === entry.source.id;
      previousTurn.text += sameSource ? text : ` ${text}`;
      if (!sameSource) previousTurn.sourceIds.push(entry.source.id);
    } else {
      turns.push({ id, sourceIds: [entry.source.id], text, sequence: turns.length + 1,
        timestampMs: piece.intervals[0].start_ms, speakerLabel: UNKNOWN_SPEAKER_LABEL,
        ...(piece.speaker_id ? { speakerId: piece.speaker_id } : {}) });
    }
  }
  if (ordered.some((source) => offsets.get(source.id) !== Array.from(source.text).length)) return fallback();
  return { turns, intervals };
}
