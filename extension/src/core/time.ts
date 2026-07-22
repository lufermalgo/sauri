// Formatted timestamp — Req. 11.1, 11.2, 11.3, 11.4, 11.5, 3.9, 8.3, 10.3

const NOT_AVAILABLE_PLACEHOLDER = "--:--";
const ONE_HOUR_MS = 3_600_000;

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * Formats a timestamp in milliseconds per Req. 11:
 * - negative/NaN/null/undefined → "--:--"
 * - [0, 3_600_000) → "MM:SS"
 * - >= 3_600_000 → "HH:MM:SS"
 */
export function formatTimestamp(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || typeof ms !== "number" || Number.isNaN(ms) || ms < 0) {
    return NOT_AVAILABLE_PLACEHOLDER;
  }

  const totalSec = Math.floor(ms / 1000);
  const sec = totalSec % 60;
  const min = Math.floor(totalSec / 60) % 60;
  const hours = Math.floor(totalSec / 3600);

  if (ms < ONE_HOUR_MS) {
    return `${pad2(min)}:${pad2(sec)}`;
  }

  return `${pad2(hours)}:${pad2(min)}:${pad2(sec)}`;
}
