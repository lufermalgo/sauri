import { useEffect, useRef, useState } from "react";
import type { MeetingSummary, SummaryRequestStatus } from "@sauri/shared-types";
import { getLatestSummaryRequest, getMeetingSummary, requestMeetingSummary } from "../api";
import { copy } from "../copy/es";

interface SummaryPanelProps {
  meetingId: string;
  onSeek: (startMs: number) => void;
}

function timestamp(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
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
    const plainText = [summary.topic, ...summary.keyPoints.map((point) =>
      `- ${typeof point === "string" ? point : point.text}`,
    )].join("\n");
    try {
      await navigator.clipboard.writeText(plainText);
      if (mounted.current) setCopyFeedback(text.copied);
    } catch {
      if (mounted.current) setCopyFeedback(text.copyFailed);
    }
  }

  const currentRequest = request && (!summary || request.generation > summary.generation) ? request : null;
  const waiting = currentRequest?.status === "pending" || currentRequest?.status === "running";
  const resultUnavailable = currentRequest?.status === "succeeded";

  if (loading) return <p role="status">{text.loading}</p>;
  if (loadError || resultUnavailable) return (
    <div>
      <p role="alert">{loadError ? text.loadFailed : text.resultUnavailable}</p>
      <button type="button" onClick={() => {
        setAcceptedRequest(null);
        setReload((value) => value + 1);
      }}>{text.retry}</button>
    </div>
  );

  return (
    <section aria-label={text.tab}>
      {requestError && <p role="alert">{text.requestFailed}</p>}
      {submitting ? <p role="status">{text.submitting}</p> : waiting ? (
        <p role="status">{currentRequest.status === "running" ? text.running : text.pending}</p>
      ) : currentRequest?.status === "failed" ? (
        <>
          <p role="alert">{text.failed} {text.failureCause(currentRequest.failureCause)}</p>
          <button type="button" onClick={() => void generate()}>{text.retry}</button>
        </>
      ) : summary ? (
        <>
          <p>{text.draft}</p>
          <h3>{text.topic}</h3>
          <p>{summary.topic}</p>
          <h3>{text.keyPoints}</h3>
          <ul>
            {summary.keyPoints.map((point, index) => (
              <li key={index}>
                <p>{typeof point === "string" ? point : point.text}</p>
                {typeof point !== "string" && point.sources.length > 0 && (
                  <ul aria-label={text.sources}>
                    {point.sources.map((source) => (
                      <li key={source.passageId}>
                        <a
                          href="#meeting-playback"
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
          <button type="button" onClick={() => void copySummary()}>{text.copy}</button>
          {copyFeedback && <p role="status">{copyFeedback}</p>}
        </>
      ) : (
        <>
          <p>{text.empty}</p>
          <button type="button" onClick={() => void generate()}>{text.generate}</button>
        </>
      )}
    </section>
  );
}
