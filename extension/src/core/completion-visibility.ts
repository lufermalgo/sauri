import type { RecordingCompletion } from "../recording-db";

/** A terminal outcome that is older than this counts as acknowledged. */
export const OUTCOME_EXPIRY_MS = 7 * 24 * 60 * 60 * 1000;

// Outcomes that no further automatic step is expected to replace. In-progress
// states (capturing, saving, uploading, transcribing) are never terminal.
const TERMINAL_STATUSES: ReadonlySet<RecordingCompletion["status"]> = new Set([
  "upload_failed",
  "upload_outcome_unavailable",
  "processing_assets_unavailable",
  "processing_status_unavailable",
  "processing_failed",
  "processing_succeeded",
  "review_launch_pending",
  "review_opened",
]);

export function isTerminalOutcome(record: RecordingCompletion): boolean {
  return TERMINAL_STATUSES.has(record.status);
}

/**
 * Whether a recovered record must stay out of the panel on reopen: a terminal
 * outcome the user already dismissed, or one old enough to be stale. In-progress
 * records and unacknowledged recent outcomes are always shown.
 */
export function isOutcomeAcknowledged(record: RecordingCompletion, now: number = Date.now()): boolean {
  if (!isTerminalOutcome(record)) return false;
  return record.acknowledgedAt !== undefined || now - record.updatedAt > OUTCOME_EXPIRY_MS;
}
