// Auth lockout after consecutive failures — Req. 13.6
import type { AuthAttempt } from "./types";

const MAX_CONSECUTIVE_FAILURES = 5;
const LOCKOUT_WINDOW_MS = 60_000;

/**
 * Determines whether authentication is locked: true iff at least 5
 * consecutive failures accumulated at the end of the sequence (with no
 * later success) and fewer than 60s have elapsed since the fifth failure
 * (Req. 13.6). `attempts` is assumed sorted ascending by `atMs`.
 */
export function isLocked(attempts: AuthAttempt[], now: number): boolean {
  let consecutive = 0;
  for (let i = attempts.length - 1; i >= 0; i--) {
    if (!attempts[i].success) {
      consecutive++;
    } else {
      break;
    }
  }

  if (consecutive < MAX_CONSECUTIVE_FAILURES) return false;

  const fifthFromEnd = attempts[attempts.length - MAX_CONSECUTIVE_FAILURES].atMs;
  return now - fifthFromEnd < LOCKOUT_WINDOW_MS;
}
