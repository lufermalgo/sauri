import { useEffect, useRef, useState } from "react";
import type { MeetingSummary, SummaryBlock, SummaryKeyPoint, SummaryRequestStatus, SummarySource } from "@sauri/shared-types";
import type { SummarySignal } from "../processing-estimate";
import { getLatestSummaryRequest, getMeetingSummary, requestMeetingSummary } from "../api";
import { copy } from "../copy/es";
import { StageProgress } from "./StageProgress";
import { Button, Skeleton, SkeletonLines, StatusBadge } from "./ui";
import "../styles/summary.css";

interface SummaryPanelProps {
  meetingId: string;
  onSeek: (startMs: number) => void;
  // False while the transcript is still being produced: summary generation starts on its own then.
  transcriptReady?: boolean;
  // Lets the meeting view reuse the loaded summary (e.g. key-point markers) without a second request.
  onSummaryChange?: (summary: MeetingSummary | null) => void;
  // True right after speaker identification: the automatic request may appear any second, so keep checking.
  expectAutoRequest?: boolean;
  // Lets the meeting view show summary progress without a second request.
  onSignalChange?: (signal: SummarySignal) => void;
  // Inputs of the generation progress shown while the summary is being written.
  progress?: { audioSeconds: number | null; createdAt: string | null; stageStartedAt: number | null };
}

const SKELETON_POINT_WIDTHS = ["72%", "58%", "66%"];

function GeneratingSkeleton({ progress }: { progress: NonNullable<SummaryPanelProps["progress"]> }) {
  const text = copy.summary;
  return (
    <>
      <div className="summary-generating">
        <div className="summary-generating-head">
          <StatusBadge tone="progress">{text.generatingBadge}</StatusBadge>
          <span role="status" className="summary-generating-status">{text.generating}</span>
        </div>
        <StageProgress stage="summary" label={copy.processing.summarizing} {...progress} />
        <div className="summary-skeleton-block" aria-hidden="true">
          <Skeleton width={60} height={12} />
          <Skeleton height={16} />
          <Skeleton width="70%" height={16} />
        </div>
        <ul className="summary-skeleton-points" aria-hidden="true">
          {SKELETON_POINT_WIDTHS.map((width) => (
            <li key={width} className="summary-skeleton-point">
              <Skeleton width={16} height={16} radius="full" className="summary-skeleton-bullet" />
              <span className="summary-skeleton-body">
                <Skeleton height={14} />
                <Skeleton width={width} height={14} />
                <Skeleton width={110} height={18} radius="full" />
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="summary-help">{text.generatingHelp}</p>
    </>
  );
}

function timestamp(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

function isBlock(point: SummaryKeyPoint | SummaryBlock | string): point is SummaryBlock {
  return typeof point !== "string" && "title" in point;
}

// The exact plain text that "Copy" puts on the clipboard and "Download" saves. It never carries
// minutes or timestamps: sources are only offered as links in the panel.
function summaryPlainText(summary: MeetingSummary): string {
  const text = copy.summary;
  if (summary.schemaVersion !== 2) {
    return [summary.topic, ...summary.keyPoints.map((point) =>
      `- ${typeof point === "string" ? point : isBlock(point) ? point.title : point.text}`,
    )].join("\n");
  }
  const blocks = summary.keyPoints.filter(isBlock).map((block, index) => [
    `${index + 1}. ${block.title}`,
    ...block.items.flatMap((item) => [`- ${item.text}`, ...item.subItems.map((sub) => `  - ${sub}`)]),
  ].join("\n"));
  return [
    `${text.mainTopic}\n${summary.topic}`,
    `${text.detailedKeyPoints}\n${blocks.join("\n\n")}`,
    ...(summary.conclusion ? [`${text.conclusion}\n${summary.conclusion}`] : []),
  ].join("\n\n");
}

function SourceChips({ sources, onSeek }: { sources: SummarySource[]; onSeek: (startMs: number) => void }) {
  const text = copy.summary;
  if (sources.length === 0) return null;
  return (
    <ul aria-label={text.sources} className="summary-sources">
      {sources.map((source) => (
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
  );
}

function StructuredSummary({ summary, onSeek }: { summary: MeetingSummary; onSeek: (startMs: number) => void }) {
  const text = copy.summary;
  return (
    <>
      <h3 className="summary-label">{text.mainTopic}</h3>
      <p className="summary-paragraph">{summary.topic}</p>
      <h3 className="summary-label">{text.detailedKeyPoints}</h3>
      <ol className="summary-blocks">
        {summary.keyPoints.filter(isBlock).map((block, index) => (
          <li key={index} className="summary-block">
            <h4 className="summary-block-title">{block.title}</h4>
            <ul className="summary-items">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  {item.text}
                  {item.subItems.length > 0 && (
                    <ul className="summary-subitems">
                      {item.subItems.map((sub, subIndex) => <li key={subIndex}>{sub}</li>)}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
            <SourceChips sources={block.sources} onSeek={onSeek} />
          </li>
        ))}
      </ol>
      {summary.conclusion && (
        <>
          <h3 className="summary-label">{text.conclusion}</h3>
          <p className="summary-paragraph">{summary.conclusion}</p>
        </>
      )}
    </>
  );
}

// A meeting change also cancels pending requests and clears clipboard feedback.
export function SummaryPanel(props: SummaryPanelProps) {
  return <MeetingSummaryPanel key={props.meetingId} {...props} />;
}

function MeetingSummaryPanel({
  meetingId, onSeek, transcriptReady = true, onSummaryChange, expectAutoRequest = false, onSignalChange,
  progress = { audioSeconds: null, createdAt: null, stageStartedAt: null },
}: SummaryPanelProps) {
  const [summary, setSummary] = useState<MeetingSummary | null>(null);
  useEffect(() => { onSummaryChange?.(summary); }, [summary, onSummaryChange]);
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
  const expectRef = useRef(expectAutoRequest);
  expectRef.current = expectAutoRequest;

  // Look again as soon as an automatic request becomes likely (not on mount: the first load covers it).
  const expectedBefore = useRef(expectAutoRequest);
  useEffect(() => {
    if (expectAutoRequest && !expectedBefore.current) setReload((value) => value + 1);
    expectedBefore.current = expectAutoRequest;
  }, [expectAutoRequest]);

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
        const awaitingAuto = expectRef.current && !artifact && !latest;
        if ((latest?.status === "pending" || latest?.status === "running" || awaitingAuto) && !document.hidden) {
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
  const signal: SummarySignal | null = loading ? null
    : waiting || submitting ? "waiting"
      : summary || currentRequest || loadError ? "settled" : "none";
  useEffect(() => { if (signal) onSignalChange?.(signal); }, [signal, onSignalChange]);

  if (loading) return (
    <div className="summary-panel">
      <p role="status" className="summary-state">{text.loading}</p>
    </div>
  );
  if (loadError || resultUnavailable) return (
    <div className="summary-panel">
      <div className="summary-notice summary-notice--error">
        <p role="alert">{loadError ? text.loadFailed : text.resultUnavailable}</p>
        <Button variant="secondary" size="sm" onClick={() => {
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
        <GeneratingSkeleton progress={progress} />
      ) : currentRequest?.status === "failed" ? (
        <div className="summary-notice summary-notice--error">
          <p role="alert">{text.failed} {text.failureCause(currentRequest.failureCause)}</p>
          {transcriptReady && <Button variant="secondary" size="sm" onClick={() => void generate()}>{text.retry}</Button>}
        </div>
      ) : summary ? (
        <>
          <div className="summary-toolbar">
            <StatusBadge tone="neutral">{text.draft}</StatusBadge>
            <div className="summary-actions" role="group" aria-label={text.actions}>
              <Button variant="secondary" size="sm" onClick={() => void copySummary()}>{text.copy}</Button>
              <Button variant="secondary" size="sm" onClick={downloadSummary}>{text.download}</Button>
            </div>
          </div>
          {copyFeedback && <p role="status" className="summary-feedback">{copyFeedback}</p>}
          {summary.schemaVersion === 2 ? <StructuredSummary summary={summary} onSeek={onSeek} /> : (
            <>
              <h3 className="summary-label">{text.topic}</h3>
              <p className="summary-topic">{summary.topic}</p>
              <h3 className="summary-label">{text.keyPoints}</h3>
              <ul className="summary-points">
                {summary.keyPoints.map((point, index) => (
                  <li key={index} className="summary-point">
                    <p>{typeof point === "string" ? point : isBlock(point) ? point.title : point.text}</p>
                    {typeof point !== "string" && <SourceChips sources={point.sources} onSeek={onSeek} />}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      ) : transcriptReady ? (
        <div className="summary-empty">
          <p>{text.empty}</p>
          <Button variant="primary" size="sm" onClick={() => void generate()}>{text.generate}</Button>
        </div>
      ) : (
        <div className="summary-waiting">
          <p className="summary-waiting-note"><strong>{text.waitingTitle}</strong> {text.waitingBody}</p>
          <SkeletonLines lines={5} lastWidth="84%" />
        </div>
      )}
    </section>
  );
}
