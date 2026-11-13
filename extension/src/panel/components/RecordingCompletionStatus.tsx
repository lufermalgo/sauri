import React, { useEffect, useState } from "react";
import { COMPLETION_STORE, getCompletion, openDB, type RecordingCompletion } from "../../recording-db";

const outcomes: Record<RecordingCompletion["status"], string> = {
  capturing: "Recording in progress",
  finalizing: "Finalizing recording",
  upload_pending: "Upload pending",
  uploading: "Upload in progress",
  upload_succeeded: "Upload succeeded",
  upload_failed: "Upload failed",
  upload_outcome_unavailable: "Upload outcome unavailable",
  processing: "Processing in progress",
  processing_assets_unavailable: "Processing assets unavailable",
  processing_status_unavailable: "Processing status unavailable",
  processing_failed: "Processing failed",
  processing_succeeded: "Review ready",
  review_launch_pending: "Review opening pending",
  review_opened: "Review opened",
};

/** A lost worker projection may recover the latest durable recording, never an
 * arbitrary successful one. An explicit selection must never fall back. */
async function readRecording(sessionId?: string): Promise<RecordingCompletion | undefined> {
  if (sessionId) return getCompletion(sessionId);
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(COMPLETION_STORE, "readonly");
    const request = tx.objectStore(COMPLETION_STORE).getAll();
    tx.oncomplete = () => {
      db.close();
      const records = request.result as RecordingCompletion[];
      records.sort((a, b) => b.updatedAt - a.updatedAt || a.sessionId.localeCompare(b.sessionId));
      resolve(records[0]);
    };
    tx.onabort = tx.onerror = () => { db.close(); reject(tx.error); };
  });
}

interface Feedback {
  selection?: string;
  record?: RecordingCompletion;
  unavailable?: boolean;
}

/** Display only persisted outcomes; never derive upload success from idle/Stop.
 * IndexedDB emits no cross-context storage event, so re-read while open and on
 * reopen. No worker RPC, auth token or raw server error is needed for this UI. */
export function RecordingCompletionStatus({ sessionId }: { sessionId?: string }) {
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  useEffect(() => {
    let cancelled = false;
    let loading = false;
    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const record = await readRecording(sessionId);
        if (!cancelled) setFeedback({ selection: sessionId, record });
      } catch {
        // A failed read must remove any previously displayed successful state.
        if (!cancelled) setFeedback({ selection: sessionId, unavailable: true });
      } finally {
        loading = false;
      }
    };
    void refresh();
    const timer = setInterval(() => { void refresh(); }, 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [sessionId]);

  // The effect runs after rendering: guard the render too, so switching sessions
  // never briefly paints the previous recording's success.
  if (!feedback || feedback.selection !== sessionId) return null;
  const { record, unavailable } = feedback;
  if (!record && !unavailable) return null;
  const failed = unavailable || record?.captureError ||
    (record && ["upload_failed", "upload_outcome_unavailable", "processing_failed", "processing_assets_unavailable", "processing_status_unavailable"].includes(record.status));
  const title = unavailable ? "Recording status unavailable"
    : record!.captureError ? "Recording could not be finalized" : outcomes[record!.status];
  return (
    <div role={failed ? "alert" : "status"} style={{ margin: "12px", padding: "12px", border: "1px solid currentColor", borderRadius: "8px", overflowWrap: "anywhere" }}>
      <strong>{title}</strong>
      {unavailable && <p>The saved recording status could not be read. Saving has not been confirmed.</p>}
      {record?.captureError && <p>The recording has a capture error. Saving has not been confirmed; no successful upload is implied.</p>}
      {(record?.sessionId ?? sessionId) && <p>Recording session: {record?.sessionId ?? sessionId}</p>}
      {record && <p>Meeting: {record.meetingId}</p>}
    </div>
  );
}
