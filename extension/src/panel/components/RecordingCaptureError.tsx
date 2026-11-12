import React, { useEffect, useState } from "react";
import { getCompletion } from "../../recording-db";

/** Read durable capture feedback, not an inferred upload outcome or worker status. */
export function RecordingCaptureError({ sessionId }: { sessionId?: string }) {
  const [feedback, setFeedback] = useState<{ sessionId: string; unavailable: boolean } | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let loading = false;
    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const record = await getCompletion(sessionId);
        if (!cancelled) setFeedback(record?.captureError ? { sessionId, unavailable: false } : null);
      } catch {
        if (!cancelled) setFeedback({ sessionId, unavailable: true });
      } finally {
        loading = false;
      }
    };
    void refresh();
    // IndexedDB changes do not emit chrome.storage events. Refresh while the
    // panel is open, and read again on reopen; never depend on a live worker.
    const timer = setInterval(() => { void refresh(); }, 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [sessionId]);

  if (!feedback || feedback.sessionId !== sessionId) return null;
  return (
    <div role="alert" style={{ margin: "12px", padding: "12px", border: "1px solid currentColor", borderRadius: "8px" }}>
      <strong>{feedback.unavailable ? "Recording status unavailable" : "Recording could not be finalized"}</strong>
      <p>{feedback.unavailable
        ? "The saved recording status could not be read. Saving has not been confirmed."
        : "The recording has a capture error. Saving has not been confirmed; no successful upload is implied."}</p>
      <p>Recording session: {sessionId}</p>
    </div>
  );
}
