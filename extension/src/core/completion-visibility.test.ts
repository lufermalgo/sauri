import { expect, it } from "vitest";
import { OUTCOME_EXPIRY_MS, isOutcomeAcknowledged, isTerminalOutcome } from "./completion-visibility";
import type { RecordingCompletion } from "../recording-db";

const NOW = 1_700_000_000_000;
function record(status: RecordingCompletion["status"], extra: Partial<RecordingCompletion> = {}): RecordingCompletion {
  return { sessionId: "s", meetingId: "m", provider: "meet", capturedTabId: 1, status, updatedAt: NOW, ...extra };
}

it.each(["capturing", "finalizing", "upload_pending", "uploading", "upload_succeeded", "processing"] as const)(
  "never treats the in-progress state %s as acknowledged", status => {
    expect(isTerminalOutcome(record(status))).toBe(false);
    expect(isOutcomeAcknowledged(record(status, { acknowledgedAt: NOW, updatedAt: NOW - 30 * OUTCOME_EXPIRY_MS }), NOW)).toBe(false);
  });

it.each(["upload_failed", "upload_outcome_unavailable", "processing_failed", "processing_assets_unavailable",
  "processing_status_unavailable", "processing_succeeded", "review_launch_pending", "review_opened"] as const)(
  "treats the terminal state %s as acknowledged only when dismissed or expired", status => {
    expect(isTerminalOutcome(record(status))).toBe(true);
    expect(isOutcomeAcknowledged(record(status), NOW)).toBe(false);
    expect(isOutcomeAcknowledged(record(status, { acknowledgedAt: NOW }), NOW)).toBe(true);
    expect(isOutcomeAcknowledged(record(status, { updatedAt: NOW - OUTCOME_EXPIRY_MS + 1 }), NOW)).toBe(false);
    expect(isOutcomeAcknowledged(record(status, { updatedAt: NOW - OUTCOME_EXPIRY_MS - 1 }), NOW)).toBe(true);
  });
