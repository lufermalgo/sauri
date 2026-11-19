import React, { useEffect, useState } from "react";
import { ArrowLeft, Check, Download, ExternalLink, RotateCcw, TriangleAlert, Upload } from "lucide-react";
import { Icon } from "../../core/design/Icon";
import { COMPLETION_STORE, acknowledgeCompletion, getCompletion, getChunksBySession, openDB, type RecordingCompletion } from "../../recording-db";
import { isOutcomeAcknowledged, isTerminalOutcome } from "../../core/completion-visibility";
import { portalDestination } from "../portal";

import { useT } from "../../i18n";

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
  const { t } = useT();
  const outcomes: Record<RecordingCompletion["status"], string> = {
    capturing: t("panel:recording"),
    finalizing: t("panel:saving"),
    upload_pending: t("panel:saving"),
    uploading: t("panel:saving"),
    upload_succeeded: t("panel:saved"),
    upload_failed: t("panel:uploadFailed"),
    upload_outcome_unavailable: t("panel:uploadUnknown"),
    processing: t("panel:saved"),
    processing_assets_unavailable: t("panel:processingUnavailable"),
    processing_status_unavailable: t("panel:processingUnavailable"),
    processing_failed: t("panel:processingFailed"),
    processing_succeeded: t("panel:reviewReady"),
    review_launch_pending: t("panel:reviewPending"),
    review_opened: t("panel:reviewOpened"),
  };
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
    } catch { setActionError(t("panel:retryError")); }
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
    try { await chrome.tabs.create({ url: await portalDestination(record.meetingId) }); }
    catch { setActionError(t("panel:commandError")); }
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
    } catch { setActionError(t("panel:downloadError")); }
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
  const title = unavailable ? t("panel:statusUnavailable") : record!.captureError ? t("panel:captureError") : noSpeech ? t("panel:noSpeech") : outcomes[record!.status];
  // The portal only knows the recording once the upload was accepted.
  const portalReady = Boolean(record?.recordingId);
  return <section className="panel-completion panel-stack" data-session-id={record?.sessionId ?? sessionId} data-meeting-id={record?.meetingId}>
    <div className="panel-stack panel-card" role={failed ? "alert" : "status"}>
      <h1 className="panel-status-title"><Icon icon={failed ? TriangleAlert : uploading ? Upload : Check} size={24} className={`panel-status-icon panel-status-${failed ? "error" : uploading ? "progress" : "success"}`} />{title}</h1>
      {uploading && <><strong>{t("panel:uploading")}</strong><div className="panel-upload-track" role="progressbar" aria-label={t("panel:uploading")}><span /></div><p>{t("panel:uploadHelp")}</p></>}
      {uploadFailed && <><p>{t("panel:uploadFailureHelp")}</p><button disabled={actionPending} className="panel-primary panel-with-icon" onClick={() => { void retry(); }}><Icon icon={RotateCcw} size={16} />{t("panel:retry")}</button><button disabled={actionPending} className="panel-with-icon" onClick={() => { void download(); }}><Icon icon={Download} size={16} />{t("panel:download")}</button></>}
      {record && ["upload_succeeded", "processing"].includes(record.status) && !record.captureError && <p>{t("panel:processing")}</p>}
      {unavailable && <p>{t("panel:persistenceError")}</p>}
      {record?.captureError && <p>{t("panel:captureErrorHelp")}</p>}
      {record?.status === "processing_failed" && !record.captureError && <p>{noSpeech ? t("panel:noSpeechHelp") : t("panel:processingFailedHelp")}</p>}
      {portalReady && <button className="panel-with-icon" onClick={() => { void openPortal(); }}><Icon icon={ExternalLink} size={16} />{t("panel:openPortal")}</button>}
    </div>
    {actionError && <p role="alert">{actionError}</p>}
    {record && !uploading && <button className="panel-with-icon" onClick={dismiss}><Icon icon={ArrowLeft} size={16} />{t("panel:back")}</button>}
  </section>;
}
