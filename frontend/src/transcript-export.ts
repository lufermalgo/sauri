export interface ExportTurn {
  timestampMs: number | null;
  speakerLabel: string;
  text: string;
}

const HOUR_MS = 3_600_000;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function formatTimestamp(timestampMs: number, withHours: boolean): string {
  const totalSeconds = Math.floor(Math.max(0, timestampMs) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return withHours
    ? `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`;
}

/**
 * Plain-text transcript: one line per turn, "[mm:ss] Speaker: text".
 * Uses "[hh:mm:ss]" for every line when any turn reaches one hour, so the
 * column stays uniform. A turn without a timestamp omits the bracket.
 */
export function transcriptToText(turns: ExportTurn[]): string {
  const withHours = turns.some(
    (turn) => turn.timestampMs !== null && Number.isFinite(turn.timestampMs) && turn.timestampMs >= HOUR_MS,
  );
  return turns
    .map((turn) => {
      const body = `${turn.speakerLabel}: ${turn.text.replace(/\s*\r?\n\s*/g, " ").trim()}`;
      if (turn.timestampMs === null || !Number.isFinite(turn.timestampMs)) return body;
      return `[${formatTimestamp(turn.timestampMs, withHours)}] ${body}`;
    })
    .join("\n");
}
