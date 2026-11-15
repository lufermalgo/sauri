import { useEffect, useRef, useState } from "react";
import type { MeetingSummary, SummaryRequestStatus } from "@sauri/shared-types";
import { getLatestSummaryRequest, getMeetingSummary, requestMeetingSummary } from "../api";
import { copy } from "../copy/es";
import { Button, StatusBadge } from "./ui";
import "../styles/summary.css";

interface SummaryPanelProps {
  meetingId: string;
  onSeek: (startMs: number) => void;
}

function timestamp(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

// The exact plain text that "Copy" puts on the clipboard and "Download" saves.
function summaryPlainText(summary: MeetingSummary): string {
  return [summary.topic, ...summary.keyPoints.map((point) =>
    `- ${typeof point === "string" ? point : point.text}`,
  )].join("\n");
}

// A meeting change also cancels pending requests and clears clipboard feedback.
export function SummaryPanel(props: SummaryPanelProps) {
  return <MeetingSummaryPanel key={props.meetingId} {...props} />;
}

function MeetingSummaryPanel({ meetingId, onSeek }: SummaryPanelProps) {
  const [summary, setSummary] = useState<MeetingSummary | null>(null);
  const [request, setRequest] = useState<SummaryRequestStatus | null>(null);
  const [acceptedRequest, setAcceptedRequest] = useState<SummaryRequestStatus | null>(null);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [requestError, setRequestError] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState("");
  const mounted = useRef(false);
  const text = copy.summary;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoadError(false);

    async function refresh() {
      if (cancelled || document.hidden || inFlight) return;
      clearTimeout(timer);
      inFlight = true;
      try {
        const [artifact, latest] = await Promise.all([
          getMeetingSummary(meetingId), getLatestSummaryRequest(meetingId),
        ]);
        if (cancelled) return;
        setSummary(artifact);
        setRequest(latest);
        setLoadError(false);
        if ((latest?.status === "pending" || latest?.status === "running") && !document.hidden) {
          timer = setTimeout(() => void refresh(), 5000);
        }
      } catch {
        if (!cancelled) setLoadError(true);
      } finally {
        inFlight = false;
        if (!cancelled) setLoading(false);
      }
    }

    function onVisibilityChange() {
      clearTimeout(timer);
      if (!document.hidden) void refresh();
    }

    if (acceptedRequest && (acceptedRequest.status === "pending" || acceptedRequest.status === "running")) {
      if (!document.hidden) timer = setTimeout(() => void refresh(), 5000);
    } else {
      void refresh();
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [meetingId, acceptedRequest, reload]);

  async function generate() {
    setSubmitting(true);
    setRequestError(false);
    try {
      const accepted = await requestMeetingSummary(meetingId);
      if (!mounted.current) return;
      setRequest(accepted);
      setAcceptedRequest(accepted);
      setLoading(false);
      setCopyFeedback("");
    } catch {
      if (mounted.current) setRequestError(true);
    } finally {
      if (mounted.current) setSubmitting(false);
    }
  }

  async function copySummary() {
    if (!summary) return;
    try {
      await navigator.clipboard.writeText(summaryPlainText(summary));
      if (mounted.current) setCopyFeedback(text.copied);
    } catch {
      if (mounted.current) setCopyFeedback(text.copyFailed);
    }
  }

  function downloadSummary() {
    if (!summary) return;
    const blob = new Blob([summaryPlainText(summary)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `resumen-${meetingId}.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  const currentRequest = request && (!summary || request.generation > summary.generation) ? request : null;
  const waiting = currentRequest?.status === "pending" || currentRequest?.status === "running";
  const resultUnavailable = currentRequest?.status === "succeeded";

  if (loading) return (
    <div className="summary-panel">
      <p role="status" className="summary-state">{text.loading}</p>
    </div>
  );
  if (loadError || resultUnavailable) return (
    <div className="summary-panel">
      <div className="summary-notice summary-notice--error">
        <p role="alert">{loadError ? text.loadFailed : text.resultUnavailable}</p>
        <Button variant="secondary" onClick={() => {
          setAcceptedRequest(null);
          setReload((value) => value + 1);
        }}>{text.retry}</Button>
      </div>
    </div>
  );

  return (
    <section aria-label={text.tab} className="summary-panel">
      {requestError && <p role="alert" className="summary-notice summary-notice--error">{text.requestFailed}</p>}
      {submitting ? <p role="status" className="summary-state">{text.submitting}</p> : waiting ? (
        <div className="summary-state">
          <span className="summary-pulse" aria-hidden="true" />
          <p role="status">{currentRequest.status === "running" ? text.running : text.pending}</p>
        </div>
      ) : currentRequest?.status === "failed" ? (
        <div className="summary-notice summary-notice--error">
          <p role="alert">{text.failed} {text.failureCause(currentRequest.failureCause)}</p>
          <Button variant="secondary" onClick={() => void generate()}>{text.retry}</Button>
        </div>
      ) : summary ? (
        <>
          <div className="summary-toolbar">
            <StatusBadge tone="neutral">{text.draft}</StatusBadge>
            <div className="summary-actions" role="group" aria-label={text.actions}>
              <Button variant="secondary" onClick={() => void copySummary()}>{text.copy}</Button>
              <Button variant="secondary" onClick={downloadSummary}>{text.download}</Button>
            </div>
          </div>
          {copyFeedback && <p role="status" className="summary-feedback">{copyFeedback}</p>}
          <h3 className="summary-label">{text.topic}</h3>
          <p className="summary-topic">{summary.topic}</p>
          <h3 className="summary-label">{text.keyPoints}</h3>
          <ul className="summary-points">
            {summary.keyPoints.map((point, index) => (
              <li key={index} className="summary-point">
                <p>{typeof point === "string" ? point : point.text}</p>
                {typeof point !== "string" && point.sources.length > 0 && (
                  <ul aria-label={text.sources} className="summary-sources">
                    {point.sources.map((source) => (
                      <li key={source.passageId}>
                        <a
                          href="#meeting-playback"
                          className="summary-source"
                          aria-label={text.sourceAt(timestamp(source.startMs))}
                          onClick={(event) => { event.preventDefault(); onSeek(source.startMs); }}
                        >{timestamp(source.startMs)}</a>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <div className="summary-empty">
          <p>{text.empty}</p>
          <Button variant="primary" onClick={() => void generate()}>{text.generate}</Button>
        </div>
      )}
    </section>
  );
}
