import React, { useEffect, useState } from "react";
import { ArrowLeft, Check, Download, ExternalLink, RotateCcw, TriangleAlert, Upload } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { COMPLETION_STORE, acknowledgeCompletion, getCompletion, getChunksBySession, openDB, type RecordingCompletion } from "../../recording-db";
import { isOutcomeAcknowledged, isTerminalOutcome } from "../../core/completion-visibility";
import { portalDestination } from "../portal";

import { panelCopy as copy } from "../copy";

const outcomes: Record<RecordingCompletion["status"], string> = {
  capturing: copy.recording,
  finalizing: copy.saving,
  upload_pending: copy.saving,
  uploading: copy.saving,
  upload_succeeded: copy.saved,
  upload_failed: copy.uploadFailed,
  upload_outcome_unavailable: copy.uploadUnknown,
  processing: copy.saved,
  processing_assets_unavailable: copy.processingUnavailable,
  processing_status_unavailable: copy.processingUnavailable,
  processing_failed: copy.processingFailed,
  processing_succeeded: copy.reviewReady,
  review_launch_pending: copy.reviewPending,
  review_opened: copy.reviewOpened,
};

/** A lost worker projection may recover the latest durable recording, never an
 * arbitrary successful one. An explicit selection must never fall back. The
 * recovered record is hidden once acknowledged (or stale) and an older record
 * is never resurrected in its place. */
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
      const latest = records[0];
      resolve(latest && !isOutcomeAcknowledged(latest) ? latest : undefined);
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
export function RecordingCompletionStatus({ sessionId, onVisibleChange }: { sessionId?: string; onVisibleChange?: (visible: boolean) => void }) {
  // Keyed by session and status: a later, different outcome must not stay hidden.
  const [dismissedOutcome, setDismissedOutcome] = useState<string | undefined>();
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
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

  const record = feedback && feedback.selection === sessionId ? feedback.record : undefined;
  const unavailable = feedback && feedback.selection === sessionId && feedback.unavailable;
  const visible = Boolean(unavailable || (record && (record.status !== "capturing" || record.captureError))) && (!record || dismissedOutcome !== `${record.sessionId}:${record.status}`);
  useEffect(() => { onVisibleChange?.(visible); }, [visible, onVisibleChange]);
  useEffect(() => { setActionError(null); }, [sessionId]);

  const retry = async () => {
    if (!record || actionPending) return;
    setActionPending(true);
    setActionError(null);
    try {
      // The upload owner handles retries; the panel must not mutate queue state.
      const result = await chrome.runtime.sendMessage({ type: "retry-upload", sessionId: record.sessionId });
      if (!result?.ok) throw new Error("Retry rejected");
    } catch { setActionError(copy.retryError); }
    finally { setActionPending(false); }
  };

  const dismiss = () => {
    if (!record) return;
    setDismissedOutcome(`${record.sessionId}:${record.status}`);
    // Only a finished outcome is acknowledged durably; an in-progress one can still fail later.
    if (isTerminalOutcome(record)) void acknowledgeCompletion(record.sessionId).catch(() => { /* Dismissal still holds while the panel is open. */ });
  };

  const openPortal = async () => {
    if (!record) return;
    try { await chrome.tabs.create({ url: portalDestination(record.meetingId) }); }
    catch { setActionError(copy.commandError); }
  };

  const download = async () => {
    if (!record || actionPending) return;
    setActionPending(true);
    setActionError(null);
    let url: string | undefined;
    try {
      const chunks = await getChunksBySession(record.sessionId);
      if (!chunks.length) throw new Error("Local recording unavailable");
      const blob = new Blob(chunks, { type: chunks[0].type || "video/webm" });
      if (!blob.size) throw new Error("Local recording empty");
      url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `sauri-${record.sessionId}.webm`;
      document.body.append(link);
      link.click();
      link.remove();
    } catch { setActionError(copy.downloadError); }
    finally {
      if (url) { const blobUrl = url; setTimeout(() => URL.revokeObjectURL(blobUrl), 1000); }
      setActionPending(false);
    }
  };

  // Selection guards prevent an old asynchronous read painting another session.
  if (!visible) return null;
  const failed = unavailable || record?.captureError ||
    (record && ["upload_failed", "upload_outcome_unavailable", "processing_failed", "processing_assets_unavailable", "processing_status_unavailable"].includes(record.status));
  const uploading = record && ["finalizing", "upload_pending", "uploading"].includes(record.status) && !record.captureError;
  const uploadFailed = record && record.status === "upload_failed" && !record.captureError;
  const noSpeech = !record?.captureError && record?.status === "processing_failed" && record.failureCause === "no_speech_detected";
  const title = unavailable ? copy.statusUnavailable : record!.captureError ? copy.captureError : noSpeech ? copy.noSpeech : outcomes[record!.status];
  // The portal only knows the recording once the upload was accepted.
  const portalReady = Boolean(record?.recordingId);
  return <section className="panel-completion panel-stack" data-session-id={record?.sessionId ?? sessionId} data-meeting-id={record?.meetingId}>
    <div className="panel-stack panel-card" role={failed ? "alert" : "status"}>
      <h1 className="panel-status-title"><Icon icon={failed ? TriangleAlert : uploading ? Upload : Check} size={24} className={`panel-status-icon panel-status-${failed ? "error" : uploading ? "progress" : "success"}`} />{title}</h1>
      {uploading && <><strong>{copy.uploading}</strong><div className="panel-upload-track" role="progressbar" aria-label={copy.uploading}><span /></div><p>{copy.uploadHelp}</p></>}
      {uploadFailed && <><p>{copy.uploadFailureHelp}</p><button disabled={actionPending} className="panel-primary panel-with-icon" onClick={() => { void retry(); }}><Icon icon={RotateCcw} size={16} />{copy.retry}</button><button disabled={actionPending} className="panel-with-icon" onClick={() => { void download(); }}><Icon icon={Download} size={16} />{copy.download}</button></>}
      {record && ["upload_succeeded", "processing"].includes(record.status) && !record.captureError && <p>{copy.processing}</p>}
      {unavailable && <p>{copy.persistenceError}</p>}
      {record?.captureError && <p>{copy.captureErrorHelp}</p>}
      {record?.status === "processing_failed" && !record.captureError && <p>{noSpeech ? copy.noSpeechHelp : copy.processingFailedHelp}</p>}
      {portalReady && <button className="panel-with-icon" onClick={() => { void openPortal(); }}><Icon icon={ExternalLink} size={16} />{copy.openPortal}</button>}
    </div>
    {actionError && <p role="alert">{actionError}</p>}
    {record && !uploading && <button className="panel-with-icon" onClick={dismiss}><Icon icon={ArrowLeft} size={16} />{copy.back}</button>}
  </section>;
}
