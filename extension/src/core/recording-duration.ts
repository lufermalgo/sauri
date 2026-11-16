// Pure helpers for the recorded duration sent in the ingestion payload.

/**
 * Whole seconds, rounded up, of the media actually recorded (paused time is
 * already excluded by the caller). Never below 1: this is only called when a
 * recorder existed, and the backend contract treats 0 as "unknown".
 */
export function recordedDurationSeconds(recordedMs: number): number {
  if (!Number.isFinite(recordedMs) || recordedMs <= 0) return 1;
  return Math.max(1, Math.ceil(recordedMs / 1000));
}

/** Accepts only a positive whole number of seconds from an untrusted message. */
export function parseDurationSeconds(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1 ? value : undefined;
}
