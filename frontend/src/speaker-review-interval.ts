/** Turn fields the listening interval needs; word turns from GET /transcript provide them. */
export interface IntervalTurn {
  speakerId?: string | null;
  startMs: number;
  endMs: number;
  hasAmbiguous?: boolean;
}

export interface ListeningInterval {
  startMs: number;
  endMs: number;
  short: boolean;
}

export const MAX_PAUSE_MS = 250;
export const MAX_LISTEN_MS = 20_000;
export const SHORT_INTERVAL_MS = 5_000;

interface Span {
  startMs: number;
  endMs: number;
}

function hasValidTiming(turn: IntervalTurn): boolean {
  return Number.isFinite(turn.startMs) && Number.isFinite(turn.endMs) &&
    turn.startMs >= 0 && turn.endMs >= turn.startMs;
}

/** Removes every blocker from the span, returning the remaining non-empty pieces. */
function subtract(span: Span, blockers: readonly Span[]): Span[] {
  let pieces = [span];
  for (const blocker of blockers) {
    pieces = pieces.flatMap((piece) => {
      if (blocker.endMs <= piece.startMs || blocker.startMs >= piece.endMs) return [piece];
      const rest: Span[] = [];
      if (blocker.startMs > piece.startMs) rest.push({ startMs: piece.startMs, endMs: blocker.startMs });
      if (blocker.endMs < piece.endMs) rest.push({ startMs: blocker.endMs, endMs: piece.endMs });
      return rest;
    });
  }
  return pieces;
}

/**
 * Selects where to listen to one speaker on the original recording (design §11).
 *
 * Only that speaker's unambiguous turns count. Any other turn (another speaker, no speaker,
 * or ambiguous words) cuts the stretch, including where it overlaps. Pieces separated by a
 * pause of at most 250 ms with nothing else in between are joined; the longest stretch wins
 * (earliest on ties) and is capped at 20 s. `short` marks stretches under 5 s.
 */
export function selectListeningInterval(
  turns: readonly IntervalTurn[],
  speakerId: string,
): ListeningInterval | null {
  const valid = turns.filter(hasValidTiming);
  const isUsable = (turn: IntervalTurn) => turn.speakerId === speakerId && !turn.hasAmbiguous;
  // A zero-length turn carries no audio, so it cannot cut a stretch.
  const blockers: Span[] = valid.filter((turn) => !isUsable(turn) && turn.endMs > turn.startMs);
  const pieces = valid
    .filter(isUsable)
    .flatMap((turn) => subtract({ startMs: turn.startMs, endMs: turn.endMs }, blockers))
    .filter((piece) => piece.endMs > piece.startMs)
    .sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs);

  const stretches: Span[] = [];
  for (const piece of pieces) {
    const current = stretches.at(-1);
    const blockedGap = current !== undefined && blockers.some((blocker) =>
      blocker.startMs <= piece.startMs && blocker.endMs >= current.endMs);
    if (current && piece.startMs - current.endMs <= MAX_PAUSE_MS && !blockedGap) {
      current.endMs = Math.max(current.endMs, piece.endMs);
    } else {
      stretches.push({ ...piece });
    }
  }

  let best: Span | undefined;
  for (const stretch of stretches) {
    if (!best || stretch.endMs - stretch.startMs > best.endMs - best.startMs) best = stretch;
  }
  if (!best) return null;
  const endMs = Math.min(best.endMs, best.startMs + MAX_LISTEN_MS);
  return { startMs: best.startMs, endMs, short: endMs - best.startMs < SHORT_INTERVAL_MS };
}
